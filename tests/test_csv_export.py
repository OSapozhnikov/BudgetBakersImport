"""Unit tests for CSV export conversion and serialization."""

from __future__ import annotations

import csv
import tempfile
import unittest
from datetime import date
from decimal import Decimal
from io import StringIO
from pathlib import Path

from app.services.csv_export import (
    CSV_COLUMNS,
    ExportRow,
    build_csv,
    build_export_filename,
    convert_rows,
)
from app.services.excel_parser import ParsedRow
from app.services.fx_nbu import FxConversion, NbuFxConverter
from app.services.mapping_store import CategoryMappingStore


class _PassthroughFx(NbuFxConverter):
    """FX stub that never calls NBU — UAH passthrough only."""

    def __init__(self) -> None:
        pass

    def convert(self, amount: Decimal, currency: str, op_date: date) -> FxConversion:
        code = (currency or "UAH").upper() or "UAH"
        return FxConversion(
            original_amount=amount,
            original_currency=code,
            amount_uah=amount.quantize(Decimal("0.01")),
            rate=Decimal("1") if code == "UAH" else None,
            rate_date=op_date if code == "UAH" else None,
            converted=False,
            warning=None,
        )

    def close(self) -> None:
        return None


def _parsed(
    *,
    note: str = "Оплата товарів\\послуг\\SILPO KIYEV UKR : Google Pay ****8801.",
    counter_party: str = "SILPO",
    bank_category: str = "Продукти",
    amount: str = "-100.50",
) -> ParsedRow:
    return ParsedRow(
        date=date(2026, 3, 1),
        note=note,
        card="*1234",
        bank_category=bank_category,
        amount=Decimal(amount),
        currency="UAH",
        status="Виконано",
        source_row=2,
        counter_party=counter_party,
    )


class ConvertRowsTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.store = CategoryMappingStore(Path(self._tmp.name))
        self.store.save({"Продукти": "Groceries"})

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_convert_rows_carries_counter_party_and_mapping(self) -> None:
        result = convert_rows(
            [_parsed()],
            account_name="My Cash",
            mapping_store=self.store,
            fx=_PassthroughFx(),
        )
        self.assertEqual(len(result.rows), 1)
        row = result.rows[0]
        self.assertEqual(row.counter_party, "SILPO")
        self.assertEqual(row.category, "Groceries")
        self.assertTrue(row.mapped)
        self.assertEqual(row.account, "My Cash")
        self.assertEqual(row.amount, Decimal("-100.50"))
        self.assertEqual(row.currency, "UAH")


class BuildCsvTests(unittest.TestCase):
    def test_csv_columns_unchanged_no_counterparty_column(self) -> None:
        self.assertEqual(
            CSV_COLUMNS,
            (
                "Cтатус",
                "Дата операції",
                "Опис операції",
                "Рахунок/картка",
                "Категорія",
                "Сума",
                "Валюта",
            ),
        )
        self.assertNotIn("counterParty", CSV_COLUMNS)
        self.assertNotIn("Контрагент", CSV_COLUMNS)

        row = ExportRow(
            date=date(2026, 3, 1),
            account="Cash",
            category="Food",
            amount=Decimal("-1003"),
            note="SILPO purchase",
            currency="UAH",
            bank_category="Продукти",
            original_amount=Decimal("-1003"),
            original_currency="UAH",
            mapped=True,
            fx_converted=False,
            counter_party="SILPO",
        )
        raw = build_csv([row]).decode("utf-8-sig")
        self.assertNotIn("counterParty", raw)
        self.assertNotIn("Контрагент", raw)
        self.assertIn("SILPO purchase", raw)

        reader = csv.DictReader(StringIO(raw))
        self.assertEqual(tuple(reader.fieldnames or ()), CSV_COLUMNS)
        data = list(reader)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["Cтатус"], "Виконано")
        self.assertEqual(data[0]["Дата операції"], "01.03.2026")
        self.assertEqual(data[0]["Опис операції"], "SILPO purchase")
        self.assertEqual(data[0]["Рахунок/картка"], "Cash")
        self.assertEqual(data[0]["Категорія"], "Food")
        self.assertEqual(data[0]["Сума"], "-1003")
        self.assertEqual(data[0]["Валюта"], "₴")

    def test_amount_strips_trailing_zeros(self) -> None:
        row = ExportRow(
            date=date(2026, 1, 2),
            account="A",
            category="C",
            amount=Decimal("-4397.90"),
            note="n",
            currency="UAH",
            bank_category="b",
            original_amount=Decimal("-4397.90"),
            original_currency="UAH",
            mapped=False,
            fx_converted=False,
        )
        raw = build_csv([row]).decode("utf-8-sig")
        self.assertIn("-4397.9", raw)

    def test_export_filename(self) -> None:
        rows = [
            ExportRow(
                date=date(2026, 1, 5),
                account="X",
                category="C",
                amount=Decimal("1"),
                note="n",
                currency="UAH",
                bank_category="b",
                original_amount=Decimal("1"),
                original_currency="UAH",
                mapped=False,
                fx_converted=False,
            ),
            ExportRow(
                date=date(2026, 1, 10),
                account="X",
                category="C",
                amount=Decimal("2"),
                note="n",
                currency="UAH",
                bank_category="b",
                original_amount=Decimal("2"),
                original_currency="UAH",
                mapped=False,
                fx_converted=False,
            ),
        ]
        name = build_export_filename("My Cash", rows)
        self.assertEqual(name, "bbi-MyCash-05.01.2026-10.01.2026.csv")


if __name__ == "__main__":
    unittest.main()
