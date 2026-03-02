"""csv_parser.py のユニットテスト"""

from datetime import date
from decimal import Decimal

import pytest

from tax_automation.parsers.csv_parser import CsvParser


class TestCsvParser:
    def test_parse_generic_csv(self, generic_card_profile, sample_csv_path):
        parser = CsvParser(generic_card_profile)
        transactions = parser.parse(sample_csv_path)

        assert len(transactions) == 8

    def test_first_transaction(self, generic_card_profile, sample_csv_path):
        parser = CsvParser(generic_card_profile)
        transactions = parser.parse(sample_csv_path)

        first = transactions[0]
        assert first.date == date(2025, 1, 5)
        assert first.merchant_name == "AWS Tokyo"
        assert first.amount == Decimal("5500")
        assert first.memo == "クラウドサーバー"

    def test_transaction_without_memo(self, generic_card_profile, sample_csv_path):
        parser = CsvParser(generic_card_profile)
        transactions = parser.parse(sample_csv_path)

        # セブンイレブンはmemoなし
        seveneleven = next(t for t in transactions if "セブン" in t.merchant_name)
        assert seveneleven.memo == ""

    def test_all_amounts_are_positive(self, generic_card_profile, sample_csv_path):
        parser = CsvParser(generic_card_profile)
        transactions = parser.parse(sample_csv_path)

        for tx in transactions:
            assert tx.amount > 0, f"{tx.merchant_name} の金額が正でない: {tx.amount}"

    def test_ids_are_unique(self, generic_card_profile, sample_csv_path):
        parser = CsvParser(generic_card_profile)
        transactions = parser.parse(sample_csv_path)

        ids = [tx.id for tx in transactions]
        assert len(ids) == len(set(ids)), "重複したIDが存在します"

    def test_file_not_found(self, generic_card_profile):
        parser = CsvParser(generic_card_profile)
        with pytest.raises(FileNotFoundError):
            parser.parse("/nonexistent/path/to/file.csv")
