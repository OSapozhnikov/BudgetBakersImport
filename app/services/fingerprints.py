from __future__ import annotations

import hashlib
import json
import logging
import re
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from threading import Lock
from typing import Iterable

from app.services.csv_export import ExportRow

logger = logging.getLogger(__name__)

_WHITESPACE = re.compile(r"\s+")
_TWO_PLACES = Decimal("0.01")


def normalize_text(value: str | None) -> str:
    """Strip, collapse whitespace, casefold."""
    text = str(value or "").strip()
    if not text:
        return ""
    return _WHITESPACE.sub(" ", text).casefold()


def fingerprint_parts(
    *,
    account_id: str,
    date_iso: str,
    amount: Decimal | float | str,
    note: str | None,
    counter_party: str | None,
) -> str:
    """Stable fingerprint string before hashing."""
    amount_dec = Decimal(str(amount)).quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)
    return "|".join(
        [
            str(account_id or "").strip(),
            str(date_iso or "").strip(),
            f"{amount_dec:.2f}",
            normalize_text(note),
            normalize_text(counter_party),
        ]
    )


def fingerprint_hash(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def fingerprint_row(row: ExportRow, account_id: str) -> str:
    """SHA-256 hex fingerprint for an export row on a given account."""
    raw = fingerprint_parts(
        account_id=account_id,
        date_iso=row.date.isoformat(),
        amount=row.amount,
        note=row.note,
        counter_party=row.counter_party,
    )
    return fingerprint_hash(raw)


def fingerprint_from_api_item(item: dict, account_id: str) -> str | None:
    """Best-effort fingerprint from a Wallet GET /records item."""
    if not isinstance(item, dict):
        return None
    acc = str(item.get("accountId") or account_id or "").strip()
    if not acc:
        return None

    record_date = item.get("recordDate") or item.get("date") or ""
    date_iso = str(record_date)[:10]
    if len(date_iso) != 10:
        return None

    amount_raw = item.get("amount")
    if isinstance(amount_raw, dict):
        value = amount_raw.get("value")
    else:
        value = amount_raw
    if value is None:
        return None

    note = item.get("note")
    counter_party = item.get("counterParty") or item.get("counter_party")
    raw = fingerprint_parts(
        account_id=acc,
        date_iso=date_iso,
        amount=value,
        note=str(note) if note is not None else "",
        counter_party=str(counter_party) if counter_party is not None else "",
    )
    return fingerprint_hash(raw)


class FingerprintStore:
    """Durable set of imported-row fingerprints ($DATA_DIR/import_fingerprints.json)."""

    def __init__(self, data_dir: str | Path) -> None:
        self.data_dir = Path(data_dir)
        self.path = self.data_dir / "import_fingerprints.json"
        self._lock = Lock()
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def load(self) -> set[str]:
        with self._lock:
            return set(self._read_unlocked())

    def contains(self, fp: str) -> bool:
        return fp in self.load()

    def add_many(self, fingerprints: Iterable[str]) -> int:
        """Add fingerprints; returns how many were newly inserted."""
        incoming = {str(x).strip() for x in fingerprints if str(x).strip()}
        if not incoming:
            return 0
        with self._lock:
            current = set(self._read_unlocked())
            before = len(current)
            current |= incoming
            self._write_unlocked(sorted(current))
            return len(current) - before

    def _read_unlocked(self) -> list[str]:
        if not self.path.exists():
            return []
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Failed to read fingerprints: %s", exc)
            return []
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

    def _write_unlocked(self, fingerprints: list[str]) -> None:
        payload = {"fingerprints": fingerprints}
        self.path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
