"""Unit tests for preview row selection helper in main."""

from __future__ import annotations

import unittest
from datetime import date
from decimal import Decimal

from app.selection import rows_by_indices
from app.services.csv_export import ExportRow


def _row(note: str) -> ExportRow:
    return ExportRow(
        date=date(2026, 1, 1),
        account="A",
        category="C",
        amount=Decimal("1"),
        note=note,
        currency="UAH",
        bank_category="b",
        original_amount=Decimal("1"),
        original_currency="UAH",
        mapped=False,
        fx_converted=False,
    )


class RowsByIndicesTests(unittest.TestCase):
    def test_selects_valid_unique_in_form_order(self) -> None:
        rows = [_row("a"), _row("b"), _row("c"), _row("d")]
        selected = rows_by_indices(rows, [2, 0, 2, 1, -1, 99])
        self.assertEqual([r.note for r in selected], ["c", "a", "b"])

    def test_empty_indices(self) -> None:
        rows = [_row("a")]
        self.assertEqual(rows_by_indices(rows, []), [])

    def test_empty_rows(self) -> None:
        self.assertEqual(rows_by_indices([], [0, 1]), [])


if __name__ == "__main__":
    unittest.main()
