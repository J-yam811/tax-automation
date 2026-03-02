"""テスト共通フィクスチャ"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from tax_automation.models import AppConfig, CardProfile, Category, Rule, Transaction

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def sample_transactions() -> list[Transaction]:
    return [
        Transaction(
            date=date(2025, 1, 5),
            merchant_name="AWS Tokyo",
            amount=Decimal("5500"),
            memo="クラウドサーバー",
        ),
        Transaction(
            date=date(2025, 1, 10),
            merchant_name="スターバックス 渋谷店",
            amount=Decimal("880"),
            memo="",
        ),
        Transaction(
            date=date(2025, 1, 20),
            merchant_name="セブンイレブン",
            amount=Decimal("450"),
            memo="",
        ),
        Transaction(
            date=date(2025, 1, 25),
            merchant_name="謎の店舗 XYZ",
            amount=Decimal("12000"),
            memo="",
        ),
    ]


@pytest.fixture
def sample_categories() -> list[Category]:
    return [
        Category(code="通信費", name_ja="通信費", description="通信関連費用", is_deductible=True),
        Category(code="会議費", name_ja="会議費", description="会議・打ち合わせ費用", is_deductible=True),
        Category(code="プライベート", name_ja="プライベート（経費外）", description="個人支出", is_deductible=False),
        Category(code="雑費", name_ja="雑費", description="その他経費", is_deductible=True),
    ]


@pytest.fixture
def sample_rules() -> list[Rule]:
    return [
        Rule(keywords=["AWS", "GitHub", "Zoom"], category_code="通信費", priority=10),
        Rule(keywords=["スターバックス", "ドトール"], category_code="会議費", priority=3),
        Rule(keywords=["セブンイレブン", "ファミリーマート"], category_code="プライベート", priority=2),
    ]


@pytest.fixture
def generic_card_profile() -> CardProfile:
    return CardProfile(
        name="Generic Card",
        encoding="utf-8",
        date_column="date",
        date_format="%Y-%m-%d",
        amount_column="amount",
        merchant_column="merchant",
        memo_column="memo",
    )


@pytest.fixture
def sample_csv_path() -> Path:
    return FIXTURES_DIR / "sample_generic.csv"


@pytest.fixture
def app_config(tmp_path: Path) -> AppConfig:
    return AppConfig(
        cache_file=str(tmp_path / "test_cache.json"),
        cache_enabled=True,
    )
