"""Gemini Vision APIを使ったレシート読み取りモジュール

1枚の画像に複数レシートが写っていても、個別に読み取り可能。
"""

from __future__ import annotations

import json
import logging
import mimetypes
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import google.generativeai as genai

from .models import PaymentMethod, ReceiptData, ReceiptItem

logger = logging.getLogger(__name__)

# レシート読み取り用プロンプト（複数レシート対応）
_RECEIPT_PROMPT = """\
あなたは日本のレシート・領収書を正確に読み取る専門家です。
この画像に写っているレシート・領収書を全て読み取ってください。

## 重要なルール
- 画像に **1枚** のレシートがある場合も、**複数枚** 並んでいる場合も、
  必ず JSON **配列** で返してください。
- 1枚なら要素1つの配列、3枚なら要素3つの配列です。
- 日付は YYYY-MM-DD 形式で出力してください。
- 金額は整数（円単位）で出力してください。
- 決済方法は "cash"（現金）, "card"（クレカ/電子マネー）, "unknown"（不明）のいずれか。
- 品目は可能な限り全て読み取ってください。
- 読み取れない項目は null にしてください。

## 出力形式（必ず配列で返す）
[
  {
    "store_name": "店名A",
    "date": "2025-01-20",
    "total_amount": 1234,
    "payment_method": "cash",
    "items": [
      {"name": "品名1", "quantity": 1, "unit_price": 100, "amount": 100, "tax_rate": "10%"},
      {"name": "品名2", "quantity": 2, "unit_price": 200, "amount": 400, "tax_rate": "8%"}
    ]
  },
  {
    "store_name": "店名B",
    "date": "2025-01-20",
    "total_amount": 5678,
    "payment_method": "card",
    "items": [
      {"name": "品名3", "quantity": 1, "unit_price": 5678, "amount": 5678, "tax_rate": "10%"}
    ]
  }
]
"""

# 対応する画像形式
_SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp", ".bmp"}


class ReceiptScanner:
    """Gemini Vision APIでレシート画像を読み取り、構造化データに変換する。

    1枚の画像に複数レシートが写っていても、個別に分割して読み取る。
    """

    def __init__(
        self,
        api_key: str,
        model_name: str = "gemini-2.5-flash",
        temperature: float = 0.0,
    ):
        genai.configure(api_key=api_key)
        self._model = genai.GenerativeModel(model_name)
        self._temperature = temperature
        self._scan_count = 0

    @property
    def scan_count(self) -> int:
        return self._scan_count

    def scan_folder(self, folder_path: Path | str) -> list[ReceiptData]:
        """フォルダ内の全レシート画像を一括スキャンする。

        1枚の画像に複数レシートが含まれていても、個別にリスト化して返す。
        """
        folder = Path(folder_path)
        if not folder.exists():
            raise FileNotFoundError(f"フォルダが見つかりません: {folder}")

        image_files = sorted([
            f for f in folder.iterdir()
            if f.is_file() and f.suffix.lower() in _SUPPORTED_EXTENSIONS
        ])

        if not image_files:
            logger.warning(f"レシート画像が見つかりません: {folder}")
            return []

        logger.info(f"レシート画像 {len(image_files)} 枚を検出: {folder}")

        results = []
        for img_path in image_files:
            try:
                receipts = self.scan_image(img_path)
                if receipts:
                    for r in receipts:
                        logger.info(
                            f"  ✅ {img_path.name}: {r.store_name} "
                            f"¥{r.total_amount:,} ({len(r.items)}品目)"
                        )
                    results.extend(receipts)
                else:
                    logger.warning(f"  ⚠️ {img_path.name}: レシートを検出できませんでした")
            except Exception as e:
                logger.error(f"  ❌ {img_path.name}: スキャン失敗 - {e}")

        logger.info(f"スキャン完了: {len(image_files)}枚の画像から {len(results)}枚のレシートを読み取り")
        return results

    def scan_image(self, image_path: Path | str) -> list[ReceiptData]:
        """1枚の画像をスキャンし、含まれる全レシートを返す。

        1枚の画像に1枚のレシートでも、複数枚並んでいても対応する。

        Returns:
            ReceiptDataのリスト（画像内の各レシートに対応）
        """
        path = Path(image_path)
        if not path.exists():
            raise FileNotFoundError(f"画像が見つかりません: {path}")

        # 画像をアップロード
        mime_type = mimetypes.guess_type(str(path))[0] or "image/jpeg"
        uploaded_file = genai.upload_file(path, mime_type=mime_type)

        logger.debug(f"Gemini Vision API呼び出し: {path.name}")
        self._scan_count += 1

        try:
            response = self._model.generate_content(
                [_RECEIPT_PROMPT, uploaded_file],
                generation_config=genai.GenerationConfig(
                    temperature=self._temperature,
                    response_mime_type="application/json",
                ),
            )
            data = json.loads(response.text)
        except json.JSONDecodeError as e:
            logger.warning(f"レシートJSON解析失敗 ({path.name}): {e}")
            return []
        except Exception as e:
            logger.error(f"Gemini Vision APIエラー ({path.name}): {e}")
            return []

        return self._parse_response(data, str(path))

    # 後方互換: 旧APIの scan_single も維持
    def scan_single(self, image_path: Path | str) -> ReceiptData | None:
        """1枚の画像から最初のレシートを返す（後方互換用）。"""
        results = self.scan_image(image_path)
        return results[0] if results else None

    def _parse_response(self, data: object, image_path: str) -> list[ReceiptData]:
        """APIレスポンスをReceiptDataモデルのリストに変換する。

        レスポンスが配列でもオブジェクトでも対応する。
        """
        # 配列でない場合は配列に変換（1枚のレシートが直接返された場合）
        if isinstance(data, dict):
            receipt_list = [data]
        elif isinstance(data, list):
            receipt_list = data
        else:
            logger.warning(f"予期しないレスポンス形式: {type(data)}")
            return []

        results = []
        for idx, receipt_data in enumerate(receipt_list):
            if not isinstance(receipt_data, dict):
                logger.debug(f"レシート#{idx+1}: dict以外のデータをスキップ")
                continue

            parsed = self._parse_single_receipt(receipt_data, image_path)
            if parsed:
                results.append(parsed)

        return results

    def _parse_single_receipt(self, data: dict, image_path: str) -> ReceiptData | None:
        """1件のレシートデータをパースする。"""
        try:
            # 日付パース
            raw_date = data.get("date", "")
            if raw_date:
                parsed_date = datetime.strptime(raw_date, "%Y-%m-%d").date()
            else:
                parsed_date = date.today()

            # 合計金額
            total = data.get("total_amount", 0)
            if total is None:
                total = 0

            # 決済方法
            pm_str = data.get("payment_method", "unknown")
            try:
                payment_method = PaymentMethod(pm_str)
            except ValueError:
                payment_method = PaymentMethod.UNKNOWN

            # 品目リスト
            items = []
            for item_data in data.get("items", []):
                try:
                    items.append(ReceiptItem(
                        name=str(item_data.get("name", "不明")),
                        quantity=int(item_data.get("quantity", 1) or 1),
                        unit_price=Decimal(str(item_data["unit_price"])) if item_data.get("unit_price") else None,
                        amount=Decimal(str(item_data.get("amount", 0))),
                        tax_rate=str(item_data.get("tax_rate", "")),
                    ))
                except (ValueError, KeyError) as e:
                    logger.debug(f"品目パース失敗: {item_data} - {e}")

            return ReceiptData(
                image_path=image_path,
                store_name=data.get("store_name", "不明"),
                date=parsed_date,
                total_amount=Decimal(str(total)),
                items=items,
                payment_method=payment_method,
            )

        except Exception as e:
            logger.error(f"レシートデータ変換失敗: {e}")
            return None
