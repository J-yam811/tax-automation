"""GeminiCategorizer のユニットテスト (APIをモック)"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from tax_automation.cache import GeminiCache
from tax_automation.models import CategorizationSource, Transaction


@pytest.fixture
def uncategorized_transactions():
    return [
        Transaction(date=date(2025, 1, 25), merchant_name="謎の店舗 XYZ", amount=Decimal("12000")),
        Transaction(date=date(2025, 1, 26), merchant_name="不明サービス ABC", amount=Decimal("3000")),
    ]


@pytest.fixture
def gemini_cache(tmp_path: Path):
    return GeminiCache(tmp_path / "test_cache.json", enabled=True)


class TestGeminiCategorizer:
    def test_categorize_batch_calls_api_once(
        self, mocker, uncategorized_transactions, gemini_cache, sample_categories
    ):
        """複数件でも1回のAPIコールで処理することを確認"""
        from tax_automation.categorizers.gemini import GeminiCategorizer

        # モックレスポンスを準備
        mock_response = mocker.MagicMock()
        mock_response.text = json.dumps([
            {
                "id": uncategorized_transactions[0].cache_key,
                "category_code": "雑費",
                "reasoning": "判別不能",
            },
            {
                "id": uncategorized_transactions[1].cache_key,
                "category_code": "通信費",
                "reasoning": "通信サービスと判断",
            },
        ])

        mock_generate = mocker.patch(
            "google.generativeai.GenerativeModel.generate_content",
            return_value=mock_response,
        )
        mocker.patch("google.generativeai.configure")

        categorizer = GeminiCategorizer(
            api_key="dummy_key",
            cache=gemini_cache,
            categories=sample_categories,
            max_batch_size=20,
        )
        categorizer.categorize_batch(uncategorized_transactions)

        # 2件でも1回しかAPIを呼ばない
        assert mock_generate.call_count == 1
        assert categorizer.api_call_count == 1

    def test_cache_hit_skips_api(
        self, mocker, uncategorized_transactions, gemini_cache, sample_categories
    ):
        """キャッシュヒット時はAPIを呼ばない"""
        from tax_automation.categorizers.gemini import GeminiCategorizer

        # 事前にキャッシュに設定
        for tx in uncategorized_transactions:
            gemini_cache.set(tx.cache_key, {"category_code": "雑費", "reasoning": "キャッシュ"})

        mock_generate = mocker.patch(
            "google.generativeai.GenerativeModel.generate_content",
        )
        mocker.patch("google.generativeai.configure")

        categorizer = GeminiCategorizer(
            api_key="dummy_key",
            cache=gemini_cache,
            categories=sample_categories,
        )
        categorizer.categorize_batch(uncategorized_transactions)

        assert mock_generate.call_count == 0
        for tx in uncategorized_transactions:
            assert tx.categorization_source == CategorizationSource.CACHE

    def test_invalid_json_response_falls_back_to_zatsubi(
        self, mocker, uncategorized_transactions, gemini_cache, sample_categories
    ):
        """API応答がJSONでない場合は雑費にフォールバック"""
        from tax_automation.categorizers.gemini import GeminiCategorizer

        mock_response = mocker.MagicMock()
        mock_response.text = "これはJSONではありません"

        mocker.patch(
            "google.generativeai.GenerativeModel.generate_content",
            return_value=mock_response,
        )
        mocker.patch("google.generativeai.configure")

        categorizer = GeminiCategorizer(
            api_key="dummy_key",
            cache=gemini_cache,
            categories=sample_categories,
        )
        categorizer.categorize_batch(uncategorized_transactions)

        for tx in uncategorized_transactions:
            assert tx.category_code == "雑費"

    def test_unknown_category_code_falls_back(
        self, mocker, uncategorized_transactions, gemini_cache, sample_categories
    ):
        """存在しない勘定科目コードが返ってきた場合は雑費にフォールバック"""
        from tax_automation.categorizers.gemini import GeminiCategorizer

        mock_response = mocker.MagicMock()
        mock_response.text = json.dumps([
            {
                "id": uncategorized_transactions[0].cache_key,
                "category_code": "存在しない科目",
                "reasoning": "テスト",
            },
        ])

        mocker.patch(
            "google.generativeai.GenerativeModel.generate_content",
            return_value=mock_response,
        )
        mocker.patch("google.generativeai.configure")

        categorizer = GeminiCategorizer(
            api_key="dummy_key",
            cache=gemini_cache,
            categories=sample_categories,
        )
        categorizer.categorize_batch(uncategorized_transactions[:1])

        assert uncategorized_transactions[0].category_code == "雑費"


class TestGeminiCache:
    def test_set_and_get(self, tmp_path):
        cache = GeminiCache(tmp_path / "cache.json")
        cache.set("key1", {"category_code": "通信費", "reasoning": "test"})
        result = cache.get("key1")
        assert result == {"category_code": "通信費", "reasoning": "test"}

    def test_cache_miss_returns_none(self, tmp_path):
        cache = GeminiCache(tmp_path / "cache.json")
        assert cache.get("nonexistent_key") is None

    def test_persist_and_reload(self, tmp_path):
        cache_path = tmp_path / "cache.json"
        cache1 = GeminiCache(cache_path)
        cache1.set("key1", {"category_code": "通信費"})
        cache1.save()

        cache2 = GeminiCache(cache_path)
        assert cache2.get("key1") == {"category_code": "通信費"}

    def test_disabled_cache_always_misses(self, tmp_path):
        cache = GeminiCache(tmp_path / "cache.json", enabled=False)
        cache.set("key1", {"category_code": "通信費"})
        assert cache.get("key1") is None
