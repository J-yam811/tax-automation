"""models.py のユニットテスト"""

from datetime import date
from decimal import Decimal

import pytest

from tax_automation.models import CategorizationSource, Transaction


class TestTransactionAmountParsing:
    def test_plain_number(self):
        tx = Transaction(date=date(2025, 1, 1), merchant_name="店", amount="1234")
        assert tx.amount == Decimal("1234")

    def test_with_comma(self):
        tx = Transaction(date=date(2025, 1, 1), merchant_name="店", amount="1,234")
        assert tx.amount == Decimal("1234")

    def test_with_yen_sign(self):
        tx = Transaction(date=date(2025, 1, 1), merchant_name="店", amount="¥5,500")
        assert tx.amount == Decimal("5500")

    def test_with_yen_kanji(self):
        tx = Transaction(date=date(2025, 1, 1), merchant_name="店", amount="5500円")
        assert tx.amount == Decimal("5500")

    def test_negative_amount(self):
        tx = Transaction(date=date(2025, 1, 1), merchant_name="店", amount="-1000")
        assert tx.amount == Decimal("-1000")

    def test_decimal_amount(self):
        tx = Transaction(date=date(2025, 1, 1), merchant_name="店", amount="1234.50")
        assert tx.amount == Decimal("1234.50")


class TestTransactionId:
    def test_id_auto_generated(self):
        tx = Transaction(date=date(2025, 1, 1), merchant_name="AWS", amount=Decimal("1000"))
        assert tx.id != ""
        assert len(tx.id) == 32  # MD5ハッシュは32文字

    def test_same_transaction_same_id(self):
        tx1 = Transaction(date=date(2025, 1, 1), merchant_name="AWS", amount=Decimal("1000"))
        tx2 = Transaction(date=date(2025, 1, 1), merchant_name="AWS", amount=Decimal("1000"))
        assert tx1.id == tx2.id

    def test_different_merchant_different_id(self):
        tx1 = Transaction(date=date(2025, 1, 1), merchant_name="AWS", amount=Decimal("1000"))
        tx2 = Transaction(date=date(2025, 1, 1), merchant_name="GitHub", amount=Decimal("1000"))
        assert tx1.id != tx2.id


class TestTransactionCacheKey:
    def test_cache_key_is_deterministic(self):
        tx = Transaction(date=date(2025, 1, 1), merchant_name="AWS", amount=Decimal("1000"), memo="test")
        key1 = tx.cache_key
        key2 = tx.cache_key
        assert key1 == key2

    def test_cache_key_differs_from_id(self):
        """cache_key は日付を含まないため、同じ店名・金額なら日付が違っても同じになる"""
        tx1 = Transaction(date=date(2025, 1, 1), merchant_name="AWS", amount=Decimal("1000"))
        tx2 = Transaction(date=date(2025, 2, 1), merchant_name="AWS", amount=Decimal("1000"))
        assert tx1.cache_key == tx2.cache_key  # キャッシュキーは同じ
        assert tx1.id != tx2.id                # IDは異なる (日付込み)


class TestTransactionIsCategorizeed:
    def test_uncategorized_by_default(self):
        tx = Transaction(date=date(2025, 1, 1), merchant_name="店", amount=Decimal("100"))
        assert not tx.is_categorized

    def test_categorized_after_setting_code(self):
        tx = Transaction(date=date(2025, 1, 1), merchant_name="店", amount=Decimal("100"))
        tx.category_code = "通信費"
        assert tx.is_categorized
