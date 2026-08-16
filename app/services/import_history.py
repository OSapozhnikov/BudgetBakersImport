from __future__ import annotations

import json
import logging
import secrets
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any

logger = logging.getLogger(__name__)

HISTORY_CAP = 100


@dataclass(frozen=True)
class ImportHistoryEntry:
    id: str
    created_at: str
    filename: str
    account_name: str
    account_id: str
    requested: int
    succeeded: int
    failed: int
    skipped_zero: int
    job_id: str


class ImportHistoryStore:
    """Append-only import history ($DATA_DIR/import_history.json), newest first."""

    def __init__(self, data_dir: str | Path, *, cap: int = HISTORY_CAP) -> None:
        self.data_dir = Path(data_dir)
        self.path = self.data_dir / "import_history.json"
        self.cap = max(1, int(cap))
        self._lock = Lock()
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def list(self) -> list[ImportHistoryEntry]:
        with self._lock:
            return self._read_unlocked()

    def append(
        self,
        *,
        filename: str,
        account_name: str,
        account_id: str,
        requested: int,
        succeeded: int,
        failed: int,
        skipped_zero: int,
        job_id: str,
    ) -> ImportHistoryEntry:
        entry = ImportHistoryEntry(
            id=secrets.token_urlsafe(12),
            created_at=datetime.now(timezone.utc).isoformat(),
            filename=str(filename or ""),
            account_name=str(account_name or ""),
            account_id=str(account_id or ""),
            requested=int(requested),
            succeeded=int(succeeded),
            failed=int(failed),
            skipped_zero=int(skipped_zero),
            job_id=str(job_id or ""),
        )
        with self._lock:
            current = self._read_unlocked()
            current.insert(0, entry)
            if len(current) > self.cap:
                current = current[: self.cap]
            self._write_unlocked(current)
        return entry

    def _read_unlocked(self) -> list[ImportHistoryEntry]:
        if not self.path.exists():
            return []
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Failed to read import history: %s", exc)
            return []
        if isinstance(raw, dict):
            items = raw.get("entries") or raw.get("items") or []
        elif isinstance(raw, list):
            items = raw
        else:
            return []
        result: list[ImportHistoryEntry] = []
        for item in items:
            parsed = _parse_entry(item)
            if parsed:
                result.append(parsed)
        return result

    def _write_unlocked(self, entries: list[ImportHistoryEntry]) -> None:
        payload = {"entries": [asdict(e) for e in entries]}
        self.path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )


def _parse_entry(item: Any) -> ImportHistoryEntry | None:
    if not isinstance(item, dict):
        return None
    entry_id = str(item.get("id") or "").strip()
    if not entry_id:
        return None
    try:
        return ImportHistoryEntry(
            id=entry_id,
            created_at=str(item.get("created_at") or ""),
            filename=str(item.get("filename") or ""),
            account_name=str(item.get("account_name") or ""),
            account_id=str(item.get("account_id") or ""),
            requested=int(item.get("requested") or 0),
            succeeded=int(item.get("succeeded") or 0),
            failed=int(item.get("failed") or 0),
            skipped_zero=int(item.get("skipped_zero") or 0),
            job_id=str(item.get("job_id") or ""),
        )
    except (TypeError, ValueError):
        return None
