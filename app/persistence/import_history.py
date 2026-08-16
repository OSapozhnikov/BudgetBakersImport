from __future__ import annotations

import secrets
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.persistence.json_store import JsonFileStore

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
        self.cap = max(1, int(cap))
        self._store = JsonFileStore(self.data_dir / "import_history.json")

    @property
    def path(self) -> Path:
        return self._store.path

    def list(self) -> list[ImportHistoryEntry]:
        return _parse_entries(self._store.load(default={"entries": []}))

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

        def apply(raw: object) -> dict[str, Any]:
            current = _parse_entries(raw)
            current.insert(0, entry)
            if len(current) > self.cap:
                current = current[: self.cap]
            return {"entries": [asdict(e) for e in current]}

        self._store.mutate(apply, default={"entries": []})
        return entry


def _parse_entries(raw: object) -> list[ImportHistoryEntry]:
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
