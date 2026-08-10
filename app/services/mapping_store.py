from __future__ import annotations

import json
import logging
from pathlib import Path
from threading import Lock

logger = logging.getLogger(__name__)


class CategoryMappingStore:
    """Persistent bank_category → BudgetBakers category name mappings."""

    def __init__(self, data_dir: str | Path) -> None:
        self.data_dir = Path(data_dir)
        self.path = self.data_dir / "category_mappings.json"
        self.discovered_path = self.data_dir / "discovered_bank_categories.json"
        self._lock = Lock()
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def load(self) -> dict[str, str]:
        with self._lock:
            if not self.path.exists():
                return {}
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                logger.warning("Failed to read mappings: %s", exc)
                return {}
            if not isinstance(raw, dict):
                return {}
            return {str(k): str(v) for k, v in raw.items() if k and v}

    def save(self, mappings: dict[str, str]) -> None:
        cleaned = {str(k).strip(): str(v).strip() for k, v in mappings.items() if str(k).strip()}
        # Drop empty targets (unmapped)
        cleaned = {k: v for k, v in cleaned.items() if v}
        with self._lock:
            self.path.write_text(
                json.dumps(cleaned, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

    def update(self, updates: dict[str, str]) -> dict[str, str]:
        current = self.load()
        for bank_cat, bb_cat in updates.items():
            key = str(bank_cat).strip()
            val = str(bb_cat).strip()
            if not key:
                continue
            if val:
                current[key] = val
            else:
                current.pop(key, None)
        self.save(current)
        return current

    def map_category(self, bank_category: str) -> tuple[str, bool]:
        """Return (mapped_name, was_mapped). Unmapped keeps original name."""
        mappings = self.load()
        if bank_category in mappings and mappings[bank_category]:
            return mappings[bank_category], True
        return bank_category, False

    def remember_bank_categories(self, categories: list[str]) -> list[str]:
        existing = set(self.load_discovered())
        existing.update(c for c in categories if c)
        ordered = sorted(existing)
        with self._lock:
            self.discovered_path.write_text(
                json.dumps(ordered, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        return ordered

    def load_discovered(self) -> list[str]:
        with self._lock:
            if not self.discovered_path.exists():
                return []
            try:
                raw = json.loads(self.discovered_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return []
            if not isinstance(raw, list):
                return []
            return [str(x) for x in raw if x]
