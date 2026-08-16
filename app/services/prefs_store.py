from __future__ import annotations

import json
import logging
from pathlib import Path
from threading import Lock
from typing import Any

logger = logging.getLogger(__name__)


class PrefsStore:
    """Durable UI preferences ($DATA_DIR/prefs.json)."""

    def __init__(self, data_dir: str | Path) -> None:
        self.data_dir = Path(data_dir)
        self.path = self.data_dir / "prefs.json"
        self._lock = Lock()
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def get_last_account_name(self) -> str | None:
        prefs = self.load()
        name = str(prefs.get("last_account_name") or "").strip()
        return name or None

    def set_last_account_name(self, name: str) -> None:
        clean = str(name or "").strip()
        with self._lock:
            prefs = self._read_unlocked()
            if clean:
                prefs["last_account_name"] = clean
            else:
                prefs.pop("last_account_name", None)
            self._write_unlocked(prefs)

    def load(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._read_unlocked())

    def _read_unlocked(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Failed to read prefs: %s", exc)
            return {}
        if not isinstance(raw, dict):
            return {}
        return raw

    def _write_unlocked(self, prefs: dict[str, Any]) -> None:
        self.path.write_text(
            json.dumps(prefs, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
