"""Locked JSON file with atomic writes."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from pathlib import Path
from threading import Lock
from typing import Any

from app.errors import AppError
from app.persistence.atomic import atomic_write_json

logger = logging.getLogger(__name__)


class JsonFileStore:
    """One JSON file: mutex + atomic replace. ``mutate`` is a single read-modify-write."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()

    def load(self, default: Any = None) -> Any:
        with self._lock:
            return self._read_unlocked(default)

    def dump(self, payload: Any) -> None:
        with self._lock:
            self._write_unlocked(payload)

    def mutate(self, fn: Callable[[Any], Any], default: Any = None) -> Any:
        with self._lock:
            current = self._read_unlocked(default)
            updated = fn(current)
            self._write_unlocked(updated)
            return updated

    def _read_unlocked(self, default: Any) -> Any:
        if not self.path.exists():
            return default
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except OSError as exc:
            logger.warning("Failed to read %s: %s", self.path, exc)
            raise AppError("err.data_unreadable", path=str(self.path), exc=str(exc)) from exc
        except json.JSONDecodeError as exc:
            logger.error("Corrupt JSON at %s: %s", self.path, exc)
            raise AppError("err.data_corrupt", path=str(self.path)) from exc

    def _write_unlocked(self, payload: Any) -> None:
        atomic_write_json(self.path, payload)
