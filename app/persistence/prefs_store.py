from __future__ import annotations

from pathlib import Path
from typing import Any

from app.persistence.json_store import JsonFileStore


class PrefsStore:
    """Durable UI preferences ($DATA_DIR/prefs.json)."""

    def __init__(self, data_dir: str | Path) -> None:
        self.data_dir = Path(data_dir)
        self._store = JsonFileStore(self.data_dir / "prefs.json")

    @property
    def path(self) -> Path:
        return self._store.path

    def get_last_account_name(self) -> str | None:
        prefs = self.load()
        name = str(prefs.get("last_account_name") or "").strip()
        return name or None

    def set_last_account_name(self, name: str) -> None:
        clean = str(name or "").strip()

        def apply(raw: object) -> dict[str, Any]:
            prefs = dict(raw) if isinstance(raw, dict) else {}
            if clean:
                prefs["last_account_name"] = clean
            else:
                prefs.pop("last_account_name", None)
            return prefs

        self._store.mutate(apply, default={})

    def load(self) -> dict[str, Any]:
        raw: Any = self._store.load(default={})
        return dict(raw) if isinstance(raw, dict) else {}
