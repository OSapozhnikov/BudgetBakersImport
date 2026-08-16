from __future__ import annotations

import hashlib
import re
from decimal import ROUND_HALF_UP, Decimal

from app.persistence.fingerprints import FingerprintStore
from app.services.csv_export import ExportRow

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

