"""キーワードマッチングによるルールベース仕訳分類器"""

from __future__ import annotations

from ..models import Category, CategorizationSource, Rule, Transaction


class RuleBasedCategorizer:
    """YAML設定のルールを使ってトランザクションを分類する。

    ルールはpriority降順でソートされており、最初にマッチしたルールが適用される。
    """

    def __init__(self, rules: list[Rule], categories: list[Category]):
        self.rules = rules  # priority降順でソート済みであることを期待
        self._category_map: dict[str, Category] = {c.code: c for c in categories}

    def categorize(self, transaction: Transaction) -> bool:
        """トランザクションを分類する。

        マッチしたルールがあれば Transaction を更新して True を返す。
        マッチしなければ False を返す。
        """
        for rule in self.rules:
            if self._matches(transaction, rule):
                category = self._category_map.get(rule.category_code)
                transaction.category_code = rule.category_code
                transaction.category_name = category.name_ja if category else rule.category_code
                transaction.categorization_source = CategorizationSource.RULE
                return True
        return False

    def categorize_all(self, transactions: list[Transaction]) -> tuple[list[Transaction], list[Transaction]]:
        """トランザクションのリストをまとめて分類する。

        Returns:
            (分類済みリスト, 未分類リスト)
        """
        categorized = []
        uncategorized = []
        for tx in transactions:
            if self.categorize(tx):
                categorized.append(tx)
            else:
                uncategorized.append(tx)
        return categorized, uncategorized

    def _matches(self, transaction: Transaction, rule: Rule) -> bool:
        """トランザクションがルールにマッチするか判定する。"""
        for keyword in rule.keywords:
            for field in rule.match_fields:
                target = self._get_field(transaction, field)
                if not target:
                    continue
                if rule.case_sensitive:
                    if keyword in target:
                        return True
                else:
                    if keyword.lower() in target.lower():
                        return True
        return False

    def _get_field(self, transaction: Transaction, field: str) -> str:
        """トランザクションから指定フィールドの値を取得する。"""
        if field == "merchant_name":
            return transaction.merchant_name
        if field == "memo":
            return transaction.memo
        return ""
