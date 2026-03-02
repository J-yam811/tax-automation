"""Gemini APIレスポンスの永続キャッシュ"""

from __future__ import annotations

import json
from pathlib import Path


class GeminiCache:
    """Gemini APIの結果をJSONファイルに永続化するキャッシュ。

    同一の (店名, 金額, 摘要) の組み合わせに対して
    再度APIを呼ばずにキャッシュから結果を返す。
    """

    def __init__(self, cache_file: str | Path, enabled: bool = True):
        self._path = Path(cache_file)
        self._enabled = enabled
        self._data: dict[str, dict] = {}
        self._dirty = False

        if enabled:
            self._load()

    def _load(self) -> None:
        if self._path.exists():
            with self._path.open("r", encoding="utf-8") as f:
                self._data = json.load(f)

    def get(self, key: str) -> dict | None:
        if not self._enabled:
            return None
        return self._data.get(key)

    def set(self, key: str, value: dict) -> None:
        if not self._enabled:
            return
        self._data[key] = value
        self._dirty = True

    def save(self) -> None:
        if not self._enabled or not self._dirty:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)
        self._dirty = False

    def __len__(self) -> int:
        return len(self._data)

    def __contains__(self, key: str) -> bool:
        return key in self._data
