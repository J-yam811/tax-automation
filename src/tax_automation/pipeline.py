"""処理パイプライン - パーサー・分類器・エクスポーターを統括する"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from .cache import GeminiCache
from .categorizers.gemini import GeminiCategorizer
from .categorizers.rule_based import RuleBasedCategorizer
from .config import load_app_config, load_card_profile, load_categories, load_rules
from .exporters.csv_exporter import CsvExporter
from .models import AppConfig, ProcessingStats, Transaction
from .parsers.csv_parser import CsvParser
from .parsers.profile_detector import detect_profile

load_dotenv()

logger = logging.getLogger(__name__)


class Pipeline:
    """クレジットカード明細CSV → 仕訳済みCSVの全処理を担う。

    処理の流れ:
    1. CSVパース
    2. ルールベース分類
    3. キャッシュチェック (Gemini結果の再利用)
    4. Gemini API一括分類 (ルールで分類できなかったもののみ)
    5. CSVエクスポート
    """

    def __init__(
        self,
        profile_name: str | None = None,
        app_config: AppConfig | None = None,
        rules_path: Path | None = None,
        categories_path: Path | None = None,
        use_gemini: bool = True,
        default_business_ratio: float = 1.0,
    ):
        self._app_config = app_config or load_app_config()
        self._profile_name = profile_name  # None の場合は run() で自動検出
        self._profile = load_card_profile(profile_name) if profile_name else None
        self._rules = load_rules(rules_path)
        self._categories = load_categories(categories_path)
        self._use_gemini = use_gemini
        self._default_business_ratio = default_business_ratio

    @property
    def detected_profile_name(self) -> str | None:
        """run() 後に確定したプロファイル名を返す。run() 前は None の可能性あり。"""
        return self._profile_name

    def run(
        self,
        input_csv: Path | str,
        output_csv: Path | str | None = None,
        year: int | None = None,
        dry_run: bool = False,
        verbose: bool = False,
    ) -> tuple[list[Transaction], ProcessingStats]:
        """パイプラインを実行する。

        Args:
            input_csv: 入力CSVファイルのパス
            output_csv: 出力CSVのパス (None の場合は data/output/ 以下に自動生成)
            year: 絞り込む年 (None の場合は全件)
            dry_run: True の場合はCSV出力をスキップ
            verbose: True の場合は各トランザクションの分類結果をログ出力

        Returns:
            (分類済みトランザクションリスト, 統計情報)
        """
        stats = ProcessingStats()

        # プロファイルが未指定の場合は自動検出
        if self._profile is None:
            detected_name = detect_profile(Path(input_csv))
            logger.info(f"プロファイル自動検出: {detected_name}")
            self._profile = load_card_profile(detected_name)
            self._profile_name = detected_name

        # ステップ1: CSVパース
        logger.info(f"CSVパース中: {input_csv}")
        parser = CsvParser(self._profile)
        transactions = parser.parse(Path(input_csv))
        stats.total = len(transactions)
        logger.info(f"  {stats.total}件を読み込みました")

        if not transactions:
            logger.warning("トランザクションが0件です。CSVの内容やプロファイル設定を確認してください。")
            return transactions, stats

        # 事業割合のデフォルト設定
        from decimal import Decimal
        for tx in transactions:
            tx.business_ratio = Decimal(str(self._default_business_ratio))

        # ステップ2: ルールベース分類
        logger.info("ルールベース分類中...")
        rule_categorizer = RuleBasedCategorizer(self._rules, self._categories)
        categorized, uncategorized = rule_categorizer.categorize_all(transactions)
        stats.rule_matched = len(categorized)
        logger.info(f"  ルールマッチ: {stats.rule_matched}件 / 未分類: {len(uncategorized)}件")

        # ステップ3 & 4: Gemini分類
        if uncategorized:
            if self._use_gemini:
                api_key = os.getenv("GEMINI_API_KEY", "")
                if not api_key:
                    logger.warning(
                        "GEMINI_API_KEY が設定されていません。"
                        "未分類トランザクションは「雑費」になります。"
                        ".env ファイルに GEMINI_API_KEY を設定してください。"
                    )
                    for tx in uncategorized:
                        tx.category_code = "雑費"
                        tx.category_name = "雑費"
                        tx.gemini_reasoning = "APIキー未設定"
                    stats.unclassified = len(uncategorized)
                else:
                    logger.info(f"Gemini API分類中: {len(uncategorized)}件...")
                    cache = GeminiCache(
                        self._app_config.cache_file,
                        enabled=self._app_config.cache_enabled,
                    )
                    gemini_categorizer = GeminiCategorizer(
                        api_key=api_key,
                        cache=cache,
                        categories=self._categories,
                        model_name=self._app_config.gemini_model,
                        temperature=self._app_config.gemini_temperature,
                        max_batch_size=self._app_config.gemini_max_batch_size,
                    )
                    gemini_categorizer.categorize_batch(uncategorized)

                    # 統計集計
                    from .models import CategorizationSource
                    for tx in uncategorized:
                        if tx.categorization_source == CategorizationSource.CACHE:
                            stats.cache_hit += 1
                        else:
                            stats.gemini_categorized += 1
                    stats.gemini_api_calls = gemini_categorizer.api_call_count
            else:
                logger.info("Gemini API をスキップ。未分類は「雑費」に設定します。")
                for tx in uncategorized:
                    tx.category_code = "雑費"
                    tx.category_name = "雑費"
                    tx.gemini_reasoning = "Geminiスキップ"
                stats.unclassified = len(uncategorized)

        # verboseモード: 各トランザクションを表示
        if verbose:
            all_tx = categorized + uncategorized
            for tx in sorted(all_tx, key=lambda t: t.date):
                logger.info(
                    f"  [{tx.date}] {tx.merchant_name[:25]:<25} "
                    f"¥{int(tx.amount):>8,}  →  {tx.category_name or '未分類'}"
                    f" ({tx.categorization_source.value})"
                )

        all_transactions = categorized + uncategorized

        # ステップ5: CSVエクスポート
        if not dry_run:
            if output_csv is None:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                output_csv = Path("data/output") / f"output_{timestamp}.csv"

            exporter = CsvExporter(encoding=self._app_config.output_encoding)
            out_path = exporter.export(all_transactions, output_csv, year=year)
            logger.info(f"出力完了: {out_path}")
        else:
            logger.info("ドライラン: CSV出力をスキップしました")

        return all_transactions, stats
