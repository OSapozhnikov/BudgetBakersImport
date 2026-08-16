"""Unit tests for fingerprint helpers and FingerprintStore."""

from __future__ import annotations

import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

from app.services.csv_export import ExportRow
from app.services.fingerprints import (
    FingerprintStore,
    fingerprint_from_api_item,
    fingerprint_hash,
    fingerprint_parts,
    fingerprint_row,
    normalize_text,
)


def _row(
    *,
    amount: str = "-10.50",
    note: str = "Coffee Shop",
    counter_party: str = "Cafe",
    day: date | None = None,
) -> ExportRow:
    return ExportRow(
        date=day or date(2026, 6, 15),
        account="Cash",
        category="Food",
        amount=Decimal(amount),
        note=note,
        currency="UAH",
        bank_category="Food",
        original_amount=Decimal(amount),
        original_currency="UAH",
        mapped=True,
        fx_converted=False,
        counter_party=counter_party,
    )


class NormalizeAndFingerprintTests(unittest.TestCase):
    def test_normalize_collapse_and_casefold(self) -> None:
        self.assertEqual(normalize_text("  Foo   BAR  "), "foo bar")
        self.assertEqual(normalize_text(None), "")
        self.assertEqual(normalize_text("  "), "")

    def test_fingerprint_stability(self) -> None:
        a = fingerprint_row(_row(note="  Coffee   Shop "), "acc-1")
        b = fingerprint_row(_row(note="coffee shop"), "acc-1")
        self.assertEqual(a, b)
        self.assertEqual(len(a), 64)

    def test_fingerprint_parts_amount_2dp(self) -> None:
        raw = fingerprint_parts(
            account_id="acc",
            date_iso="2026-06-15",
            amount=Decimal("-10.5"),
            note="x",
            counter_party="y",
        )
        self.assertEqual(raw, "acc|2026-06-15|-10.50|x|y")
        self.assertEqual(fingerprint_hash(raw), fingerprint_hash(raw))

    def test_different_account_changes_hash(self) -> None:
        row = _row()
        self.assertNotEqual(fingerprint_row(row, "a"), fingerprint_row(row, "b"))

    def test_api_item_fingerprint_matches_row(self) -> None:
        row = _row()
        expected = fingerprint_row(row, "acc-1")
        item = {
            "accountId": "acc-1",
            "recordDate": "2026-06-15T12:00:00Z",
            "amount": {"value": -10.5, "currencyCode": "UAH"},
            "note": "Coffee Shop",
            "counterParty": "Cafe",
        }
        self.assertEqual(fingerprint_from_api_item(item, "acc-1"), expected)


class FingerprintStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.store = FingerprintStore(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_round_trip_add_contains(self) -> None:
        fp = fingerprint_row(_row(), "acc-1")
        self.assertFalse(self.store.contains(fp))
        added = self.store.add_many([fp, fp, "  "])
        self.assertEqual(added, 1)
        self.assertTrue(self.store.contains(fp))
        path = Path(self._tmp.name) / "import_fingerprints.json"
        self.assertTrue(path.exists())
        self.assertIn(fp, path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
