"""Google Gemini APIを使った一括仕訳分類器"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

import google.generativeai as genai

from ..cache import GeminiCache
from ..models import Category, CategorizationSource, Transaction

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

_PROMPT_TEMPLATE = """\
あなたは日本の確定申告に詳しい税理士です。
以下の取引リストについて、それぞれの勘定科目を判定してください。

## 利用可能な勘定科目

{categories_json}

## 判定対象の取引

{transactions_json}

## 出力ルール
- 必ず以下のJSON配列のみを返してください。他のテキストは一切不要です。
- 各要素は `id`, `category_code`, `reasoning` フィールドを持ちます。
- `category_code` は上記リストの `code` 値のいずれかを使用してください。
- `reasoning` は日本語で50文字以内の判断理由を記述してください。
- 判断できない場合は `category_code` を "雑費" にしてください。

## 出力例
[
  {{"id": "abc123", "category_code": "通信費", "reasoning": "AWSはクラウドサービスのため通信費"}},
  {{"id": "def456", "category_code": "消耗品費", "reasoning": "Amazonでの購入は備品・消耗品の可能性が高い"}}
]
"""


class GeminiCategorizer:
    """Gemini APIを使ってルールで分類できなかったトランザクションを一括分類する。

    コスト削減のため:
    - キャッシュヒットの場合はAPIを呼ばない
    - 未キャッシュのトランザクションを1回のAPIコールでまとめて送信
    - max_batch_size を超える場合は複数回に分割して送信
    """

    def __init__(
        self,
        api_key: str,
        cache: GeminiCache,
        categories: list[Category],
        model_name: str = "gemini-2.5-flash",
        temperature: float = 0.0,
        max_batch_size: int = 20,
    ):
        genai.configure(api_key=api_key)
        self._model = genai.GenerativeModel(model_name)
        self._cache = cache
        self._categories = categories
        self._temperature = temperature
        self._max_batch_size = max_batch_size
        self._api_call_count = 0

        self._categories_json = json.dumps(
            [{"code": c.code, "name": c.name_ja, "description": c.description}
             for c in categories],
            ensure_ascii=False,
            indent=2,
        )
        self._valid_codes = {c.code for c in categories}
        self._category_name_map = {c.code: c.name_ja for c in categories}

    @property
    def api_call_count(self) -> int:
        return self._api_call_count

    def categorize_batch(self, transactions: list[Transaction]) -> list[Transaction]:
        """未分類のトランザクションをまとめてGemini APIで分類する。

        キャッシュヒット分はAPIを呼ばない。
        残りをmax_batch_sizeずつに分割してAPI呼び出し。
        """
        if not transactions:
            return transactions

        # キャッシュチェック
        need_api: list[Transaction] = []
        for tx in transactions:
            cached = self._cache.get(tx.cache_key)
            if cached:
                tx.category_code = cached["category_code"]
                tx.category_name = self._category_name_map.get(tx.category_code, tx.category_code)
                tx.categorization_source = CategorizationSource.CACHE
                tx.gemini_reasoning = cached.get("reasoning", "")
                logger.debug(f"キャッシュヒット: {tx.merchant_name} → {tx.category_code}")
            else:
                need_api.append(tx)

        if not need_api:
            return transactions

        # バッチ分割してAPI呼び出し
        for i in range(0, len(need_api), self._max_batch_size):
            batch = need_api[i:i + self._max_batch_size]
            self._call_api(batch)

        self._cache.save()
        return transactions

    def _call_api(self, transactions: list[Transaction]) -> None:
        """1バッチ分のトランザクションをAPIで分類する。"""
        tx_data = [
            {
                "id": tx.cache_key,
                "merchant": tx.merchant_name,
                "amount": str(tx.amount),
                "memo": tx.memo,
            }
            for tx in transactions
        ]

        prompt = _PROMPT_TEMPLATE.format(
            categories_json=self._categories_json,
            transactions_json=json.dumps(tx_data, ensure_ascii=False, indent=2),
        )

        logger.info(f"Gemini API呼び出し: {len(transactions)}件")
        self._api_call_count += 1

        try:
            response = self._model.generate_content(
                prompt,
                generation_config=genai.GenerationConfig(
                    temperature=self._temperature,
                    response_mime_type="application/json",
                ),
            )
            results: list[dict] = json.loads(response.text)
        except json.JSONDecodeError as e:
            logger.warning(f"Gemini APIレスポンスのJSONパース失敗: {e}\n→ 全件を「雑費」に設定")
            results = []
        except Exception as e:
            logger.error(f"Gemini API呼び出しエラー: {e}\n→ 全件を「雑費」に設定")
            results = []

        result_map = {r.get("id", ""): r for r in results if isinstance(r, dict)}

        for tx in transactions:
            result = result_map.get(tx.cache_key)
            if result and result.get("category_code") in self._valid_codes:
                tx.category_code = result["category_code"]
                tx.category_name = self._category_name_map.get(tx.category_code, tx.category_code)
                tx.gemini_reasoning = result.get("reasoning", "")
            else:
                tx.category_code = "雑費"
                tx.category_name = "雑費"
                tx.gemini_reasoning = "自動判定不可"
                if result:
                    logger.debug(
                        f"未知の勘定科目コード '{result.get('category_code')}' → 雑費に変更: {tx.merchant_name}"
                    )

            tx.categorization_source = CategorizationSource.GEMINI

            # キャッシュに保存
            self._cache.set(tx.cache_key, {
                "category_code": tx.category_code,
                "reasoning": tx.gemini_reasoning,
            })
            logger.debug(f"Gemini分類: {tx.merchant_name} → {tx.category_code} ({tx.gemini_reasoning})")
