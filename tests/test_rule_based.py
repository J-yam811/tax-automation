"""rule_based.py のユニットテスト"""

from datetime import date
from decimal import Decimal

import pytest

from tax_automation.categorizers.rule_based import RuleBasedCategorizer
from tax_automation.models import CategorizationSource, Transaction


class TestRuleBasedCategorizer:
    def test_matches_aws_to_tsushinhi(self, sample_rules, sample_categories):
        categorizer = RuleBasedCategorizer(sample_rules, sample_categories)
        tx = Transaction(date=date(2025, 1, 1), merchant_name="AWS Tokyo", amount=Decimal("5500"))
        result = categorizer.categorize(tx)

        assert result is True
        assert tx.category_code == "通信費"
        assert tx.categorization_source == CategorizationSource.RULE

    def test_matches_starbucks_to_kaigishi(self, sample_rules, sample_categories):
        categorizer = RuleBasedCategorizer(sample_rules, sample_categories)
        tx = Transaction(date=date(2025, 1, 1), merchant_name="スターバックス 新宿", amount=Decimal("880"))
        result = categorizer.categorize(tx)

        assert result is True
        assert tx.category_code == "会議費"

    def test_no_match_returns_false(self, sample_rules, sample_categories):
        categorizer = RuleBasedCategorizer(sample_rules, sample_categories)
        tx = Transaction(date=date(2025, 1, 1), merchant_name="謎の店 XYZ", amount=Decimal("1000"))
        result = categorizer.categorize(tx)

        assert result is False
        assert tx.category_code is None

    def test_case_insensitive_matching(self, sample_categories):
        from tax_automation.models import Rule
        rules = [Rule(keywords=["aws"], category_code="通信費", case_sensitive=False)]
        categorizer = RuleBasedCategorizer(rules, sample_categories)
        tx = Transaction(date=date(2025, 1, 1), merchant_name="AWS Tokyo", amount=Decimal("100"))
        assert categorizer.categorize(tx) is True

    def test_case_sensitive_matching(self, sample_categories):
        from tax_automation.models import Rule
        rules = [Rule(keywords=["aws"], category_code="通信費", case_sensitive=True)]
        categorizer = RuleBasedCategorizer(rules, sample_categories)
        tx = Transaction(date=date(2025, 1, 1), merchant_name="AWS Tokyo", amount=Decimal("100"))
        assert categorizer.categorize(tx) is False  # 大文字なのでマッチしない

    def test_priority_higher_wins(self, sample_categories):
        """優先度の高いルールが先に適用される"""
        from tax_automation.models import Rule
        rules = [
            Rule(keywords=["Amazon Kindle"], category_code="新聞図書費", priority=15),
            Rule(keywords=["Amazon"], category_code="消耗品費", priority=5),
        ]
        # priority降順でソート済み想定
        rules_sorted = sorted(rules, key=lambda r: r.priority, reverse=True)
        categorizer = RuleBasedCategorizer(rules_sorted, sample_categories + [
            from_code("新聞図書費"),
            from_code("消耗品費"),
        ])
        tx = Transaction(date=date(2025, 1, 1), merchant_name="Amazon Kindle", amount=Decimal("1000"))
        categorizer.categorize(tx)
        assert tx.category_code == "新聞図書費"

    def test_categorize_all_splits_correctly(self, sample_transactions, sample_rules, sample_categories):
        categorizer = RuleBasedCategorizer(sample_rules, sample_categories)
        categorized, uncategorized = categorizer.categorize_all(sample_transactions)

        assert len(categorized) + len(uncategorized) == len(sample_transactions)
        for tx in categorized:
            assert tx.is_categorized
        for tx in uncategorized:
            assert not tx.is_categorized

    def test_memo_field_matching(self, sample_categories):
        """memo フィールドでのマッチング"""
        from tax_automation.models import Rule
        rules = [Rule(keywords=["打ち合わせ"], category_code="会議費", match_fields=["memo"], priority=5)]
        categorizer = RuleBasedCategorizer(rules, sample_categories)
        tx = Transaction(
            date=date(2025, 1, 1),
            merchant_name="不明な食堂",
            amount=Decimal("1200"),
            memo="打ち合わせ費用",
        )
        assert categorizer.categorize(tx) is True
        assert tx.category_code == "会議費"


def from_code(code: str):
    """テスト用のCategory生成ヘルパー"""
    from tax_automation.models import Category
    return Category(code=code, name_ja=code, is_deductible=True)
