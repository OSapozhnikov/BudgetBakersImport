from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.persistence.json_store import JsonFileStore


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
        self._store = JsonFileStore(self.data_dir / "accounts.json")

    @property
    def path(self) -> Path:
        return self._store.path

    def list(self) -> list[StoredAccount]:
        return _parse_accounts(self._store.load(default=[]))

    def names(self) -> list[str]:
        return [a.name for a in self.list()]

    def merge_from_api(self, accounts: list[tuple[str, str | None]]) -> list[StoredAccount]:
        """Upsert API accounts by name; keep manual-only entries not present in API."""

        def apply(raw: object) -> list[dict]:
            current = _parse_accounts(raw)
            by_name = {a.name.casefold(): a for a in current}
            for name, account_id in accounts:
                clean = str(name).strip()
                if not clean:
                    continue
                key = clean.casefold()
                existing = by_name.get(key)
                by_name[key] = StoredAccount(
                    name=existing.name if existing else clean,
                    id=account_id or (existing.id if existing else None),
                    source="api",
                    primary=existing.primary if existing else False,
                )
            merged = sorted(by_name.values(), key=lambda a: a.name.casefold())
            return _to_payload(merged)

        payload = self._store.mutate(apply, default=[])
        return _parse_accounts(payload)

    def add_manual(self, name: str) -> list[StoredAccount]:
        clean = str(name).strip()
        if not clean:
            raise ValueError("err.account_empty_name")

        def apply(raw: object) -> list[dict]:
            current = _parse_accounts(raw)
            key = clean.casefold()
            for acc in current:
                if acc.name.casefold() == key:
                    return _to_payload(current)
            current.append(StoredAccount(name=clean, id=None, source="manual", primary=False))
            current.sort(key=lambda a: a.name.casefold())
            return _to_payload(current)

        return _parse_accounts(self._store.mutate(apply, default=[]))

    def remove(self, name_or_id: str) -> list[StoredAccount]:
        target = str(name_or_id).strip()
        if not target:
            return self.list()

        def apply(raw: object) -> list[dict]:
            current = _parse_accounts(raw)
            kept = [
                a
                for a in current
                if a.name != target and a.id != target and a.name.casefold() != target.casefold()
            ]
            return _to_payload(kept)

        return _parse_accounts(self._store.mutate(apply, default=[]))

    def set_primary(self, name: str) -> list[StoredAccount]:
        """Mark ``name`` as the exclusive primary account, or unset if already primary."""
        target = str(name).strip()
        if not target:
            return self.list()

        def apply(raw: object) -> list[dict]:
            current = _parse_accounts(raw)
            key = target.casefold()
            if not any(a.name.casefold() == key for a in current):
                return _to_payload(current)
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
            return _to_payload(updated)

        return _parse_accounts(self._store.mutate(apply, default=[]))


def _to_payload(accounts: list[StoredAccount]) -> list[dict]:
    return [
        {
            "name": a.name,
            **({"id": a.id} if a.id else {}),
            "source": a.source,
            **({"primary": True} if a.primary else {}),
        }
        for a in accounts
    ]


def _parse_accounts(raw: object) -> list[StoredAccount]:
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
        result.append(StoredAccount(name=name, id=account_id, source=source, primary=primary))
    result.sort(key=lambda a: a.name.casefold())
    return result
