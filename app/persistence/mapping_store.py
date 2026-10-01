from __future__ import annotations

from pathlib import Path

from app.persistence.json_store import JsonFileStore


class CategoryMappingStore:
    """Persistent bank_category → BudgetBakers category name mappings."""

    def __init__(self, data_dir: str | Path) -> None:
        self.data_dir = Path(data_dir)
        self._mappings = JsonFileStore(self.data_dir / "category_mappings.json")
        self._discovered = JsonFileStore(self.data_dir / "discovered_bank_categories.json")

    @property
    def path(self) -> Path:
        return self._mappings.path

    @property
    def discovered_path(self) -> Path:
        return self._discovered.path

    def load(self) -> dict[str, str]:
        return _clean_mappings(self._mappings.load(default={}))

    def save(self, mappings: dict[str, str]) -> None:
        self._mappings.dump(_clean_mappings(mappings))

    def update(self, updates: dict[str, str]) -> dict[str, str]:
        def apply(raw: object) -> dict[str, str]:
            current = _clean_mappings(raw)
            for bank_cat, bb_cat in updates.items():
                key = str(bank_cat).strip()
                val = str(bb_cat).strip()
                if not key:
                    continue
                if val:
                    current[key] = val
                else:
                    current.pop(key, None)
            return current

        return self._mappings.mutate(apply, default={})

    def map_category(self, bank_category: str) -> tuple[str, bool]:
        """Return (mapped_name, was_mapped). Unmapped keeps original name."""
        mappings = self.load()
        if bank_category in mappings and mappings[bank_category]:
            return mappings[bank_category], True
        return bank_category, False

    def remember_bank_categories(self, categories: list[str]) -> list[str]:
        def apply(raw: object) -> list[str]:
            existing = {str(x) for x in raw} if isinstance(raw, list) else set()
            existing.update(c for c in categories if c)
            return sorted(existing)

        return self._discovered.mutate(apply, default=[])

    def load_discovered(self) -> list[str]:
        raw = self._discovered.load(default=[])
        if not isinstance(raw, list):
            return []
        return [str(x) for x in raw if x]


def _clean_mappings(raw: object) -> dict[str, str]:
    if not isinstance(raw, dict):
        return {}
    cleaned = {
        str(k).strip(): str(v).strip()
        for k, v in raw.items()
        if str(k).strip() and str(v).strip()
    }
    return dict(sorted(cleaned.items()))
