"""仕訳結果をCSVファイルに出力するエクスポーター"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pandas as pd

from ..models import CategorizationSource, Transaction

# 出力CSVのカラム定義
_OUTPUT_COLUMNS = [
    "日付",
    "金額",
    "利用店名",
    "勘定科目",
    "摘要",
    "事業割合",
    "経費計上額",
    "分類方法",
    "Gemini判断理由",
]

_SOURCE_LABELS = {
    CategorizationSource.RULE: "ルール",
    CategorizationSource.GEMINI: "Gemini",
    CategorizationSource.CACHE: "キャッシュ",
    CategorizationSource.MANUAL: "手動",
    CategorizationSource.UNCLASSIFIED: "未分類",
}


class CsvExporter:
    """Transaction リストを確定申告用CSVに変換して出力する。

    出力エンコードは utf-8-sig (BOM付きUTF-8) のため
    Windows の Excel でも文字化けなく開ける。
    """

    def __init__(self, encoding: str = "utf-8-sig"):
        self.encoding = encoding

    def export(
        self,
        transactions: list[Transaction],
        output_path: Path | str,
        year: int | None = None,
    ) -> Path:
        """トランザクションをCSVに書き出す。

        Args:
            transactions: 出力するトランザクションのリスト
            output_path: 出力先ファイルパス
            year: 指定した年のみ出力 (None の場合は全件)

        Returns:
            書き出したファイルのパス
        """
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        rows = []
        for tx in sorted(transactions, key=lambda t: t.date):
            if year and tx.date.year != year:
                continue
            rows.append(self._to_row(tx))

        df = pd.DataFrame(rows, columns=_OUTPUT_COLUMNS)
        df.to_csv(path, index=False, encoding=self.encoding)
        return path

    def _to_row(self, tx: Transaction) -> list:
        """Transaction を出力CSV の1行に変換する。"""
        business_ratio = float(tx.business_ratio)
        amount = float(tx.amount)
        expense_amount = round(amount * business_ratio)

        return [
            tx.date.strftime("%Y/%m/%d"),
            int(tx.amount),
            tx.merchant_name,
            tx.category_name or tx.category_code or "未分類",
            tx.memo,
            f"{int(business_ratio * 100)}%",
            expense_amount,
            _SOURCE_LABELS.get(tx.categorization_source, tx.categorization_source.value),
            tx.gemini_reasoning,
        ]

    def export_summary(
        self,
        transactions: list[Transaction],
        year: int | None = None,
    ) -> str:
        """勘定科目別の集計サマリーを文字列で返す。"""
        from collections import defaultdict

        totals: dict[str, int] = defaultdict(int)
        for tx in transactions:
            if year and tx.date.year != year:
                continue
            if tx.category_code == "プライベート":
                continue
            code = tx.category_name or tx.category_code or "未分類"
            amount = int(float(tx.amount) * float(tx.business_ratio))
            totals[code] += amount

        if not totals:
            return "集計対象のトランザクションがありません。"

        lines = ["勘定科目別合計:", "-" * 30]
        for code, total in sorted(totals.items(), key=lambda x: -x[1]):
            lines.append(f"  {code:<15} ¥{total:>10,}")
        lines.append("-" * 30)
        lines.append(f"  {'合計':<15} ¥{sum(totals.values()):>10,}")
        return "\n".join(lines)
