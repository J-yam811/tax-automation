"""レシートとカード明細の突合（マッチング）モジュール"""

from __future__ import annotations

import logging
from datetime import timedelta
from decimal import Decimal

from .models import PaymentMethod, ReceiptData, Transaction, ReceiptItem

logger = logging.getLogger(__name__)


class MatchResult:
    """マッチング結果を保持するクラス"""

    def __init__(self):
        self.matched_pairs: list[tuple[Transaction, ReceiptData]] = []  # カード+レシート統合
        self.card_only: list[Transaction] = []                          # カードのみ（レシートなし）
        self.cash_transactions: list[Transaction] = []                  # 現金取引（レシートのみ）
        self.unmatched_receipts: list[ReceiptData] = []                 # マッチ不明

    @property
    def all_transactions(self) -> list[Transaction]:
        """統合済みの全トランザクションを返す"""
        result = []
        # マッチしたカード取引（レシート情報付き）
        for tx, _ in self.matched_pairs:
            result.append(tx)
        # カードのみの取引
        result.extend(self.card_only)
        # 現金取引
        result.extend(self.cash_transactions)
        return sorted(result, key=lambda t: t.date)


class ReceiptMatcher:
    """レシートデータとカード明細を突合するマッチャー。

    マッチング条件:
    - 金額が完全一致
    - 日付が±date_tolerance_days以内
    - 同じレシートが複数のカード明細にマッチしないよう制御
    """

    def __init__(self, date_tolerance_days: int = 3):
        self.date_tolerance = timedelta(days=date_tolerance_days)

    def match(
        self,
        card_transactions: list[Transaction],
        receipts: list[ReceiptData],
    ) -> MatchResult:
        """カード取引とレシートデータを突合する。

        Returns:
            MatchResult: マッチング結果（統合済み/カードのみ/現金取引）
        """
        result = MatchResult()

        if not receipts:
            # レシートがない場合、全てカードのみ
            result.card_only = list(card_transactions)
            return result

        # レシートの使用済みフラグ
        used_receipts: set[int] = set()
        # カード取引のマッチ済みフラグ
        matched_card_ids: set[str] = set()

        # 各レシートについて最適なカード取引を探す
        for receipt_idx, receipt in enumerate(receipts):
            best_match: Transaction | None = None
            best_score: float = 0.0

            for tx in card_transactions:
                if tx.id in matched_card_ids:
                    continue

                score = self._calculate_match_score(tx, receipt)
                if score > best_score:
                    best_score = score
                    best_match = tx

            if best_match and best_score >= 0.8:
                # マッチ成功 → カード取引にレシート情報を統合
                self._merge_receipt_into_transaction(best_match, receipt)
                result.matched_pairs.append((best_match, receipt))
                matched_card_ids.add(best_match.id)
                used_receipts.add(receipt_idx)
                logger.info(
                    f"✅ マッチ: {receipt.store_name} ¥{receipt.total_amount:,} "
                    f"↔ {best_match.merchant_name} ¥{best_match.amount:,} "
                    f"(スコア: {best_score:.2f})"
                )
            elif receipt.payment_method == PaymentMethod.CARD:
                # レシートにカード決済と書いてあるがマッチしない → 要確認
                result.unmatched_receipts.append(receipt)
                logger.warning(
                    f"⚠️ マッチ不明: {receipt.store_name} ¥{receipt.total_amount:,} "
                    f"(カード決済表示だがマッチするカード明細なし)"
                )
            else:
                # 現金取引として新規作成
                cash_tx = self._create_cash_transaction(receipt)
                result.cash_transactions.append(cash_tx)
                used_receipts.add(receipt_idx)
                logger.info(
                    f"💵 現金取引: {receipt.store_name} ¥{receipt.total_amount:,} "
                    f"({len(receipt.items)}品目)"
                )

        # マッチしなかったカード取引
        for tx in card_transactions:
            if tx.id not in matched_card_ids:
                result.card_only.append(tx)

        # サマリーログ
        logger.info(
            f"\nマッチング結果: "
            f"統合={len(result.matched_pairs)} "
            f"カードのみ={len(result.card_only)} "
            f"現金={len(result.cash_transactions)} "
            f"要確認={len(result.unmatched_receipts)}"
        )

        return result

    def _calculate_match_score(
        self, tx: Transaction, receipt: ReceiptData
    ) -> float:
        """カード取引とレシートのマッチスコアを計算する (0.0〜1.0)。"""
        score = 0.0

        # 金額チェック（最重要: 完全一致で0.6点）
        if abs(tx.amount - receipt.total_amount) == 0:
            score += 0.6
        elif abs(tx.amount - receipt.total_amount) <= 1:
            # 1円の誤差（丸め）は許容
            score += 0.5
        else:
            return 0.0  # 金額が違えば絶対マッチしない

        # 日付チェック（±3日以内で0.3点、近いほど高得点）
        date_diff = abs((tx.date - receipt.date).days)
        if date_diff == 0:
            score += 0.3
        elif date_diff <= self.date_tolerance.days:
            score += 0.3 * (1 - date_diff / (self.date_tolerance.days + 1))
        else:
            return 0.0  # 日付が離れすぎ

        # 店名の類似度チェック（0.1点）
        name_score = self._name_similarity(tx.merchant_name, receipt.store_name)
        score += 0.1 * name_score

        return score

    def _name_similarity(self, card_name: str, receipt_name: str) -> float:
        """店名の類似度を簡易計算する (0.0〜1.0)。"""
        # 全角→半角、小文字化で正規化
        import unicodedata
        def normalize(s: str) -> str:
            s = unicodedata.normalize("NFKC", s)
            return s.lower().strip()

        n1 = normalize(card_name)
        n2 = normalize(receipt_name)

        if n1 == n2:
            return 1.0

        # 一方が他方を含む
        if n1 in n2 or n2 in n1:
            return 0.8

        # 共通文字の割合
        common = set(n1) & set(n2)
        if not common:
            return 0.0
        return len(common) / max(len(set(n1)), len(set(n2)))

    def _merge_receipt_into_transaction(
        self, tx: Transaction, receipt: ReceiptData
    ) -> None:
        """レシートデータをカード取引に統合する。"""
        tx.receipt_items = receipt.items
        tx.receipt_image_path = receipt.image_path
        tx.matched_receipt = True
        tx.payment_method = PaymentMethod.CARD

    def _create_cash_transaction(self, receipt: ReceiptData) -> Transaction:
        """レシートデータから現金取引のTransactionを作成する。"""
        # 品目名の要約をメモに
        items_summary = ", ".join(
            item.name for item in receipt.items[:5]
        )
        if len(receipt.items) > 5:
            items_summary += f" 他{len(receipt.items) - 5}品"

        return Transaction(
            date=receipt.date,
            merchant_name=receipt.store_name,
            amount=receipt.total_amount,
            memo=items_summary,
            payment_method=PaymentMethod.CASH,
            receipt_items=receipt.items,
            receipt_image_path=receipt.image_path,
            matched_receipt=True,
        )
