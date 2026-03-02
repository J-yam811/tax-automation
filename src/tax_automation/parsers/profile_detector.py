"""CSVプロファイル自動検出 - ヘッダー行のカラム名から最適なカードプロファイルを判定する"""

from __future__ import annotations

import logging
from pathlib import Path

import chardet
import yaml

logger = logging.getLogger(__name__)

# デフォルトのプロファイルディレクトリ (このファイルから3階層上の config/)
_PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
_DEFAULT_PROFILES_DIR = _PROJECT_ROOT / "config" / "card_profiles"


def detect_profile(csv_path: Path, profiles_dir: Path | None = None) -> str:
    """CSVのヘッダー行を解析し、最適なカードプロファイル名を返す。

    全プロファイルのdate_column / amount_column / merchant_column と
    CSVヘッダーを照合してスコアリングし、最高スコアのプロファイルを返す。

    Args:
        csv_path: 判定対象のCSVファイルパス
        profiles_dir: プロファイルYAMLを格納したディレクトリ (省略時はデフォルト)

    Returns:
        プロファイル名 (例: "rakuten", "epos")。一致なしの場合は "generic"
    """
    dir_ = profiles_dir or _DEFAULT_PROFILES_DIR
    headers = _read_headers(csv_path)
    if not headers:
        logger.warning("CSVのヘッダーを読み取れませんでした。generic プロファイルを使用します。")
        return "generic"

    logger.info(f"検出されたCSVヘッダー: {headers}")

    best_profile = "generic"
    best_score = 0

    for yaml_path in sorted(dir_.glob("*.yaml")):
        profile_name = yaml_path.stem
        if profile_name == "generic":
            continue  # generic はフォールバック専用

        try:
            score = _score_profile(yaml_path, headers)
        except Exception as e:
            logger.debug(f"プロファイル {profile_name} のスコアリング中にエラー: {e}")
            continue

        logger.debug(f"  {profile_name}: score={score}")
        if score > best_score:
            best_score = score
            best_profile = profile_name

    # スコアが低い (1列しかマッチしない) 場合も generic を使う
    if best_score < 40:
        logger.info(f"明確なプロファイル一致なし (best_score={best_score})。generic を使用します。")
        return "generic"

    logger.info(f"プロファイル自動検出: {best_profile} (score={best_score})")
    return best_profile


def _read_headers(csv_path: Path) -> list[str]:
    """CSVの1行目(ヘッダー行)を読み取り、カラム名のリストを返す。

    文字コードは chardet で自動検出する。
    skip_rows が必要なプロファイル(epos等)を考慮し、
    最初の3行を試して最もカラム数が多い行を採用する。
    """
    raw = csv_path.read_bytes()
    # 先頭10KBで文字コード推定
    detected = chardet.detect(raw[:10240])
    encoding = detected.get("encoding") or "utf-8"
    # cp932/shift_jis 系は cp932 に統一
    if encoding.lower().replace("-", "").replace("_", "") in ("shiftjis", "shiftjisx0208", "sjis"):
        encoding = "cp932"

    try:
        text = raw.decode(encoding, errors="replace")
    except (LookupError, UnicodeDecodeError):
        text = raw.decode("utf-8", errors="replace")

    lines = text.splitlines()
    best_cols: list[str] = []

    # 先頭 3 行の中で最もカラム数が多い行をヘッダーとみなす
    for line in lines[:3]:
        stripped = line.strip()
        if not stripped:
            continue
        cols = [c.strip().strip('"').strip("'") for c in stripped.split(",")]
        if len(cols) > len(best_cols):
            best_cols = cols

    return best_cols


def _score_profile(yaml_path: Path, headers: list[str]) -> int:
    """プロファイルのキーカラムがヘッダーに何列マッチするかでスコアを計算する。

    3列マッチ → 100 / 2列マッチ → 60 / 1列マッチ → 20
    """
    with yaml_path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    key_columns = [
        data.get("date_column"),
        data.get("amount_column"),
        data.get("merchant_column"),
    ]
    # None は除外
    key_columns = [c for c in key_columns if c]

    matched = sum(1 for col in key_columns if col in headers)

    score_map = {3: 100, 2: 60, 1: 20, 0: 0}
    return score_map.get(matched, 0)
