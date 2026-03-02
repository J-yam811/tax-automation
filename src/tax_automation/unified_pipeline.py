"""統合パイプライン - カードCSV + レシート画像 → 仕訳済みExcel出力

カード明細CSVとレシート画像フォルダを丸投げすると、
AIが自動で重複判定・統合・仕訳してfreee用Excelを出力する。
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from dotenv import load_dotenv

from .cache import GeminiCache
from .categorizers.gemini import GeminiCategorizer
from .categorizers.rule_based import RuleBasedCategorizer
from .config import load_app_config, load_card_profile, load_categories, load_rules
from .exporters.freee_exporter import FreeeExcelExporter
from .matcher import ReceiptMatcher
from .models import (
    AppConfig, CategorizationSource, PaymentMethod,
    ProcessingStats, Transaction,
)
from .parsers.csv_parser import CsvParser
from .receipt_scanner import ReceiptScanner

load_dotenv()

logger = logging.getLogger(__name__)


class UnifiedPipeline:
    """カード明細CSV + レシート画像 → 仕訳済みExcelの全自動パイプライン。

    処理フロー:
    1. カードCSVパース → カード取引リスト
    2. レシート画像スキャン → レシートデータリスト
    3. マッチング（カード取引 ↔ レシート）→ 統合/カードのみ/現金取引
    4. ルールベース分類
    5. Gemini API分類（未分類のもの）
    6. freee用Excel出力
    """

    def __init__(
        self,
        profile_name: str = "gougin",
        settlement_account: str = "ごうぎんVISAカード",
        app_config: AppConfig | None = None,
        rules_path: Path | None = None,
        categories_path: Path | None = None,
        use_gemini: bool = True,
        default_business_ratio: float = 1.0,
        date_tolerance_days: int = 3,
    ):
        self._app_config = app_config or load_app_config()
        self._profile = load_card_profile(profile_name)
        self._rules = load_rules(rules_path)
        self._categories = load_categories(categories_path)
        self._use_gemini = use_gemini
        self._default_business_ratio = default_business_ratio
        self._settlement_account = settlement_account
        self._date_tolerance = date_tolerance_days
        self._api_key = os.getenv("GEMINI_API_KEY", "")

    def run(
        self,
        card_csv: Path | str | None = None,
        receipt_folder: Path | str | None = None,
        output_path: Path | str | None = None,
        year: int | None = None,
        dry_run: bool = False,
        verbose: bool = False,
    ) -> tuple[list[Transaction], ProcessingStats]:
        """統合パイプラインを実行する。

        Args:
            card_csv: カード明細CSVファイルのパス (Noneならレシートのみ)
            receipt_folder: レシート画像フォルダのパス (Noneならカードのみ)
            output_path: 出力Excelのパス (Noneなら自動生成)
            year: 絞り込む年
            dry_run: True なら出力をスキップ
            verbose: 詳細ログ

        Returns:
            (全トランザクション, 統計情報)
        """
        stats = ProcessingStats()

        # ==============================
        # ステップ1: カードCSVパース
        # ==============================
        card_transactions = []
        if card_csv:
            logger.info(f"📋 カードCSVパース中: {card_csv}")
            parser = CsvParser(self._profile)
            card_transactions = parser.parse(Path(card_csv))
            for tx in card_transactions:
                tx.payment_method = PaymentMethod.CARD
                tx.business_ratio = Decimal(str(self._default_business_ratio))
            logger.info(f"  {len(card_transactions)}件のカード取引を読み込み")

        # ==============================
        # ステップ2: レシート画像スキャン
        # ==============================
        receipts = []
        if receipt_folder and self._api_key:
            logger.info(f"📸 レシートスキャン中: {receipt_folder}")
            scanner = ReceiptScanner(
                api_key=self._api_key,
                model_name=self._app_config.gemini_model,
            )
            receipts = scanner.scan_folder(Path(receipt_folder))
            stats.receipts_scanned = len(receipts)
            logger.info(f"  {len(receipts)}枚のレシートを読み取り")

        # ==============================
        # ステップ3: マッチング
        # ==============================
        if card_transactions and receipts:
            logger.info("🔗 カード明細とレシートをマッチング中...")
            matcher = ReceiptMatcher(date_tolerance_days=self._date_tolerance)
            match_result = matcher.match(card_transactions, receipts)

            all_transactions = match_result.all_transactions
            stats.receipts_matched = len(match_result.matched_pairs)
            stats.receipts_cash = len(match_result.cash_transactions)
            stats.receipts_unmatched = len(match_result.unmatched_receipts)

            logger.info(
                f"  統合: {stats.receipts_matched}件 / "
                f"カードのみ: {len(match_result.card_only)}件 / "
                f"現金: {stats.receipts_cash}件"
            )
            if stats.receipts_unmatched > 0:
                logger.warning(f"  ⚠️ マッチ不明: {stats.receipts_unmatched}件 (要確認)")
        elif card_transactions:
            all_transactions = card_transactions
        elif receipts:
            # レシートのみの場合 → 全て現金取引
            logger.info("💵 レシートのみモード: 全て現金取引として処理")
            matcher = ReceiptMatcher()
            match_result = matcher.match([], receipts)
            all_transactions = match_result.cash_transactions
            stats.receipts_cash = len(all_transactions)
        else:
            logger.warning("カードCSVもレシートも指定されていません")
            return [], stats

        stats.total = len(all_transactions)

        if not all_transactions:
            logger.warning("取引が0件です")
            return all_transactions, stats

        # 事業割合のデフォルト設定
        for tx in all_transactions:
            if tx.business_ratio == Decimal("1.0"):
                tx.business_ratio = Decimal(str(self._default_business_ratio))

        # ==============================
        # ステップ4: ルールベース分類
        # ==============================
        logger.info("📂 ルールベース分類中...")
        rule_categorizer = RuleBasedCategorizer(self._rules, self._categories)
        categorized, uncategorized = rule_categorizer.categorize_all(all_transactions)
        stats.rule_matched = len(categorized)
        logger.info(f"  ルールマッチ: {stats.rule_matched}件 / 未分類: {len(uncategorized)}件")

        # ==============================
        # ステップ5: Gemini API分類
        # ==============================
        if uncategorized:
            if self._use_gemini and self._api_key:
                logger.info(f"🤖 Gemini API分類中: {len(uncategorized)}件...")
                cache = GeminiCache(
                    self._app_config.cache_file,
                    enabled=self._app_config.cache_enabled,
                )
                gemini = GeminiCategorizer(
                    api_key=self._api_key,
                    cache=cache,
                    categories=self._categories,
                    model_name=self._app_config.gemini_model,
                    temperature=self._app_config.gemini_temperature,
                    max_batch_size=self._app_config.gemini_max_batch_size,
                )
                gemini.categorize_batch(uncategorized)

                for tx in uncategorized:
                    if tx.categorization_source == CategorizationSource.CACHE:
                        stats.cache_hit += 1
                    else:
                        stats.gemini_categorized += 1
                stats.gemini_api_calls = gemini.api_call_count
            else:
                for tx in uncategorized:
                    tx.category_code = "雑費"
                    tx.category_name = "雑費"
                    tx.gemini_reasoning = "Geminiスキップ" if not self._api_key else "APIキー未設定"
                stats.unclassified = len(uncategorized)

        # verbose: 結果表示
        if verbose:
            for tx in sorted(all_transactions, key=lambda t: t.date):
                pay = "💵" if tx.payment_method == PaymentMethod.CASH else "💳"
                receipt = "📄" if tx.matched_receipt else "  "
                logger.info(
                    f"  {pay}{receipt} [{tx.date}] {tx.merchant_name[:22]:<22} "
                    f"¥{int(tx.amount):>8,}  →  {tx.category_name or '未分類'}"
                    f" ({tx.categorization_source.value})"
                )

        # ==============================
        # ステップ6: Excel出力
        # ==============================
        if not dry_run:
            if output_path is None:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                output_path = Path("data/output") / f"freee_unified_{timestamp}.xlsx"

            exporter = FreeeExcelExporter(settlement_account=self._settlement_account)
            out_path = exporter.export(all_transactions, output_path, year=year)
            logger.info(f"✅ 出力完了: {out_path}")
        else:
            logger.info("(ドライラン: ファイル出力なし)")

        return all_transactions, stats
