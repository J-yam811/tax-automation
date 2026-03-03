"""設定ファイルローダー - YAML設定を読み込んでPydanticモデルに変換する"""

from __future__ import annotations

import os
from pathlib import Path

import yaml

from .models import AppConfig, CardProfile, Category, Rule

# プロジェクトルートを自動検出
_PROJECT_ROOT = Path(__file__).parent.parent.parent
_CONFIG_DIR = _PROJECT_ROOT / "config"


def _load_yaml(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_categories(path: Path | None = None) -> list[Category]:
    """勘定科目マスタを読み込む"""
    p = path or (_CONFIG_DIR / "categories.yaml")
    data = _load_yaml(p)
    return [Category(**item) for item in data.get("categories", [])]


def load_rules(path: Path | None = None) -> list[Rule]:
    """仕訳ルールを読み込む (priority降順でソート済み)"""
    p = path or (_CONFIG_DIR / "rules.yaml")
    data = _load_yaml(p)
    rules = [Rule(**item) for item in data.get("rules", [])]
    return sorted(rules, key=lambda r: r.priority, reverse=True)


def load_card_profile(profile: str) -> CardProfile:
    """カードプロファイルを読み込む。

    Args:
        profile: プロファイル名 (例: "rakuten") またはYAMLファイルパス

    Returns:
        CardProfile オブジェクト
    """
    path = Path(profile)

    # 直接パスとして指定されている場合
    if path.suffix in (".yaml", ".yml") and path.exists():
        data = _load_yaml(path)
        return CardProfile(**data)

    # プロファイル名として解釈: config/card_profiles/{name}.yaml
    profile_path = _CONFIG_DIR / "card_profiles" / f"{profile}.yaml"
    if profile_path.exists():
        data = _load_yaml(profile_path)
        return CardProfile(**data)

    # プロジェクトルートからの相対パスとして解釈
    relative_path = _PROJECT_ROOT / profile
    if relative_path.exists():
        data = _load_yaml(relative_path)
        return CardProfile(**data)

    available = list_available_profiles()
    raise FileNotFoundError(
        f"プロファイル '{profile}' が見つかりません。\n"
        f"利用可能なプロファイル: {', '.join(available)}\n"
        f"または YAML ファイルのパスを直接指定してください。"
    )


def list_available_profiles() -> list[str]:
    """利用可能なカードプロファイル名の一覧を返す"""
    profiles_dir = _CONFIG_DIR / "card_profiles"
    if not profiles_dir.exists():
        return []
    return sorted(
        p.stem for p in profiles_dir.glob("*.yaml")
    )


def _default_cache_path() -> str:
    """キャッシュファイルのデフォルトパスを返す。

    Streamlit Cloud などファイルシステムが読み取り専用の環境では /tmp を使う。
    """
    local_path = _PROJECT_ROOT / "cache" / "gemini_cache.json"
    try:
        local_path.parent.mkdir(parents=True, exist_ok=True)
        return str(local_path)
    except (PermissionError, OSError):
        return "/tmp/gemini_cache.json"


def load_app_config() -> AppConfig:
    """環境変数からアプリケーション設定を読み込む"""
    return AppConfig(
        gemini_model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
        cache_file=os.getenv("CACHE_FILE", _default_cache_path()),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
    )
