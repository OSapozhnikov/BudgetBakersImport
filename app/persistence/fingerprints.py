from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from app.persistence.json_store import JsonFileStore


class FingerprintStore:
    """Durable set of imported-row fingerprints ($DATA_DIR/import_fingerprints.json)."""

    def __init__(self, data_dir: str | Path) -> None:
        self.data_dir = Path(data_dir)
        self._store = JsonFileStore(self.data_dir / "import_fingerprints.json")

    @property
    def path(self) -> Path:
        return self._store.path

    def load(self) -> set[str]:
        return set(_parse_fingerprints(self._store.load(default={"fingerprints": []})))

    def contains(self, fp: str) -> bool:
        return fp in self.load()

    def add_many(self, fingerprints: Iterable[str]) -> int:
        """Add fingerprints; returns how many were newly inserted."""
        incoming = {str(x).strip() for x in fingerprints if str(x).strip()}
        if not incoming:
            return 0
        added = {"n": 0}

        def apply(raw: object) -> dict:
            current = set(_parse_fingerprints(raw))
            before = len(current)
            current |= incoming
            added["n"] = len(current) - before
            return {"fingerprints": sorted(current)}

        self._store.mutate(apply, default={"fingerprints": []})
        return added["n"]


def _parse_fingerprints(raw: object) -> list[str]:
    if isinstance(raw, dict):
        items = raw.get("fingerprints") or raw.get("items") or []
    elif isinstance(raw, list):
        items = raw
    else:
        return []
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        fp = str(item).strip()
        if not fp or fp in seen:
            continue
        seen.add(fp)
        result.append(fp)
    return result
