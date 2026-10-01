from __future__ import annotations

from pathlib import Path
from typing import Any

from app.persistence.json_store import JsonFileStore


class CategoryCacheStore:
    """Cached GET /categories payload ($DATA_DIR/bb_categories_cache.json)."""

    def __init__(self, data_dir: str | Path) -> None:
        self.data_dir = Path(data_dir)
        self._store = JsonFileStore(self.data_dir / "bb_categories_cache.json")

    @property
    def path(self) -> Path:
        return self._store.path

    def load(self) -> list[dict[str, Any]]:
        raw: object = self._store.load(default=[])
        if not isinstance(raw, list):
            return []
        return [x for x in raw if isinstance(x, dict) and x.get("name")]

    def save(self, items: list[dict[str, Any]]) -> None:
        self._store.dump(items)
