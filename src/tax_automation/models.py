"""確定申告自動化ツール - コアデータモデル"""

from __future__ import annotations

import hashlib
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator


class PaymentMethod(str, Enum):
    """決済方法"""
    CARD = "card"       # クレジットカード払い
    CASH = "cash"       # 現金払い
    UNKNOWN = "unknown" # 不明


class ReceiptItem(BaseModel):
    """レシートの個別品目"""
    name: str                    # 品名
    quantity: int = 1            # 数量
    unit_price: Decimal | None = None  # 単価
    amount: Decimal              # 金額
    tax_rate: str = ""           # 税率表示 ("10%", "8%", "*" 等)


class ReceiptData(BaseModel):
    """レシートから読み取ったデータ"""
    image_path: str              # 元画像のパス
    store_name: str              # 店名
    date: date                   # 日付
    total_amount: Decimal        # 合計金額
    items: list[ReceiptItem] = Field(default_factory=list)  # 品目リスト
    payment_method: PaymentMethod = PaymentMethod.UNKNOWN   # 決済方法
    raw_text: str = ""           # OCR全文（デバッグ用）


class CategorizationSource(str, Enum):
    RULE = "rule"
    GEMINI = "gemini"
    CACHE = "cache"
    MANUAL = "manual"
    UNCLASSIFIED = "unclassified"


class Category(BaseModel):
    """勘定科目の定義"""

    code: str
    name_ja: str
    description: str = ""
    is_deductible: bool = True


class Rule(BaseModel):
    """キーワードベースの仕訳ルール"""

    keywords: list[str]
    category_code: str
    match_fields: list[str] = Field(default=["merchant_name"])
    priority: int = 0
    case_sensitive: bool = False
    comment: str = ""


class Transaction(BaseModel):
    """取引明細（カード・現金共通）"""

    id: str = ""
    date: date
    merchant_name: str
    amount: Decimal
    memo: str = ""
    raw_row: dict[str, str] = Field(default_factory=dict, exclude=True)

    # 仕訳結果 (パイプライン処理中に設定)
    category_code: str | None = None
    category_name: str | None = None
    business_ratio: Decimal = Decimal("1.0")
    categorization_source: CategorizationSource = CategorizationSource.UNCLASSIFIED
    gemini_reasoning: str = ""

    # レシート・決済関連
    payment_method: PaymentMethod = PaymentMethod.CARD
    receipt_items: list[ReceiptItem] = Field(default_factory=list)
    receipt_image_path: str = ""
    matched_receipt: bool = False  # レシートとマッチ済みフラグ

    def model_post_init(self, __context: object) -> None:
        if not self.id:
            raw = f"{self.date}|{self.merchant_name}|{self.amount}|{self.memo}"
            object.__setattr__(self, "id", hashlib.md5(raw.encode()).hexdigest())

    @field_validator("amount", mode="before")
    @classmethod
    def parse_amount(cls, v: object) -> Decimal:
        """カンマや通貨記号を除去してDecimalに変換"""
        if isinstance(v, str):
            v = v.replace(",", "").replace("¥", "").replace("円", "").strip()
            if not v:
                return Decimal("0")
        return Decimal(str(v))

    @property
    def cache_key(self) -> str:
        """Geminiレスポンスキャッシュ用のキー (店名+金額+メモのMD5)"""
        raw = f"{self.merchant_name}|{self.amount}|{self.memo}"
        return hashlib.md5(raw.encode()).hexdigest()

    @property
    def is_categorized(self) -> bool:
        return self.category_code is not None


class CardProfile(BaseModel):
    """クレジットカードCSVフォーマットのプロファイル"""

    name: str
    encoding: str = "utf-8"
    skip_rows: int = 0
    skip_footer_rows: int = 0
    delimiter: str = ","
    has_header: bool = True  # CSVにヘッダー行があるかどうか
    date_column: str
    date_format: str
    amount_column: str
    amount_sign: Literal["positive", "negative"] = "positive"
    merchant_column: str
    memo_column: str | None = None
    columns_to_skip: list[str] = Field(default_factory=list)


class AppConfig(BaseModel):
    """アプリケーション設定"""

    gemini_model: str = "gemini-2.5-flash"
    gemini_max_batch_size: int = 20
    gemini_temperature: float = 0.0
    default_business_ratio: Decimal = Decimal("1.0")
    cache_enabled: bool = True
    cache_file: str = "cache/gemini_cache.json"
    output_encoding: str = "utf-8-sig"
    log_level: str = "INFO"


class ProcessingStats(BaseModel):
    """処理結果の統計情報"""

    total: int = 0
    rule_matched: int = 0
    cache_hit: int = 0
    gemini_categorized: int = 0
    unclassified: int = 0
    gemini_api_calls: int = 0

    # レシート関連
    receipts_scanned: int = 0
    receipts_matched: int = 0    # カード明細とマッチしたレシート
    receipts_cash: int = 0       # 現金取引として新規追加
    receipts_unmatched: int = 0  # マッチ不明（要確認）

    def summary(self) -> str:
        lines = [
            f"合計: {self.total}件",
            f"  ルールマッチ:   {self.rule_matched}件",
            f"  キャッシュヒット: {self.cache_hit}件",
            f"  Gemini分類:     {self.gemini_categorized}件 (API呼び出し: {self.gemini_api_calls}回)",
            f"  未分類:         {self.unclassified}件",
        ]
        if self.receipts_scanned > 0:
            lines.append(f"")
            lines.append(f"レシート処理:")
            lines.append(f"  スキャン:     {self.receipts_scanned}枚")
            lines.append(f"  カードと統合: {self.receipts_matched}枚")
            lines.append(f"  現金取引:     {self.receipts_cash}枚")
            if self.receipts_unmatched > 0:
                lines.append(f"  要確認:       {self.receipts_unmatched}枚")
        return "\n".join(lines)
