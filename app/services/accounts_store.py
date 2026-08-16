from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from threading import Lock

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StoredAccount:
    name: str
    id: str | None = None
    source: str = "manual"  # "api" | "manual"
    primary: bool = False


class AccountsStore:
    """Durable BudgetBakers account directory ($DATA_DIR/accounts.json)."""

    def __init__(self, data_dir: str | Path) -> None:
        self.data_dir = Path(data_dir)
        self.path = self.data_dir / "accounts.json"
        self._lock = Lock()
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def list(self) -> list[StoredAccount]:
        with self._lock:
            return self._read_unlocked()

    def names(self) -> list[str]:
        return [a.name for a in self.list()]

    def merge_from_api(self, accounts: list[tuple[str, str | None]]) -> list[StoredAccount]:
        """Upsert API accounts by name; keep manual-only entries not present in API."""
        with self._lock:
            current = self._read_unlocked()
            by_name = {a.name.casefold(): a for a in current}
            api_names: set[str] = set()

            for name, account_id in accounts:
                clean = str(name).strip()
                if not clean:
                    continue
                key = clean.casefold()
                api_names.add(key)
                existing = by_name.get(key)
                by_name[key] = StoredAccount(
                    name=existing.name if existing else clean,
                    id=account_id or (existing.id if existing else None),
                    source="api",
                    primary=existing.primary if existing else False,
                )

            # Keep manual entries not returned by API
            merged = list(by_name.values())
            merged.sort(key=lambda a: a.name.casefold())
            self._write_unlocked(merged)
            return merged

    def add_manual(self, name: str) -> list[StoredAccount]:
        clean = str(name).strip()
        if not clean:
            raise ValueError("Назва рахунку порожня.")
        with self._lock:
            current = self._read_unlocked()
            key = clean.casefold()
            for acc in current:
                if acc.name.casefold() == key:
                    return current
            current.append(StoredAccount(name=clean, id=None, source="manual", primary=False))
            current.sort(key=lambda a: a.name.casefold())
            self._write_unlocked(current)
            return current

    def remove(self, name_or_id: str) -> list[StoredAccount]:
        target = str(name_or_id).strip()
        if not target:
            return self.list()
        with self._lock:
            current = self._read_unlocked()
            kept = [
                a
                for a in current
                if a.name != target and a.id != target and a.name.casefold() != target.casefold()
            ]
            self._write_unlocked(kept)
            return kept

    def set_primary(self, name: str) -> list[StoredAccount]:
        """Mark ``name`` as the exclusive primary account, or unset if already primary."""
        target = str(name).strip()
        if not target:
            return self.list()
        with self._lock:
            current = self._read_unlocked()
            key = target.casefold()
            if not any(a.name.casefold() == key for a in current):
                return current
            currently_primary = any(a.name.casefold() == key and a.primary for a in current)
            updated = [
                StoredAccount(
                    name=a.name,
                    id=a.id,
                    source=a.source,
                    primary=(a.name.casefold() == key) and not currently_primary,
                )
                for a in current
            ]
            self._write_unlocked(updated)
            return updated

    def _read_unlocked(self) -> list[StoredAccount]:
        if not self.path.exists():
            return []
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Failed to read accounts: %s", exc)
            return []
        if not isinstance(raw, list):
            return []
        result: list[StoredAccount] = []
        seen: set[str] = set()
        for item in raw:
            if isinstance(item, str):
                name = item.strip()
                account_id = None
                source = "manual"
                primary = False
            elif isinstance(item, dict):
                name = str(item.get("name") or "").strip()
                account_id = item.get("id")
                account_id = str(account_id) if account_id else None
                source = str(item.get("source") or ("api" if account_id else "manual"))
                primary = bool(item.get("primary"))
            else:
                continue
            if not name:
                continue
            key = name.casefold()
            if key in seen:
                continue
            seen.add(key)
            result.append(
                StoredAccount(name=name, id=account_id, source=source, primary=primary)
            )
        result.sort(key=lambda a: a.name.casefold())
        return result

    def _write_unlocked(self, accounts: list[StoredAccount]) -> None:
        payload = [
            {
                "name": a.name,
                **({"id": a.id} if a.id else {}),
                "source": a.source,
                **({"primary": True} if a.primary else {}),
            }
            for a in accounts
        ]
        self.path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
