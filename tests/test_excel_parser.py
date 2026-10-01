"""Unit tests for Excel parser counter_party population."""

from __future__ import annotations

import unittest
from datetime import date
from io import BytesIO

from app.services.excel_parser import parse_excel
from openpyxl import Workbook


def _minimal_xlsx_bytes() -> bytes:
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.append(
        [
            "Статус",
            "Дата операції",
            "Опис операції",
            "Рахунок/картка",
            "Категорія",
            "Сума",
            "Валюта",
        ]
    )
    ws.append(
        [
            "Виконано",
            date(2026, 6, 23),
            r"Оплата товарів\послуг\SILPO KIYEV UKR : Google Pay ****8801.",
            "*8801",
            "Продукти",
            -250.5,
            "₴",
        ]
    )
    ws.append(
        [
            "Відхилено",
            date(2026, 6, 22),
            r"Оплата товарів\послуг\Glovo Kyiv UKR : Google Pay ****8801.",
            "*8801",
            "Їжа",
            -100,
            "₴",
        ]
    )
    ws.append(
        [
            "Виконано",
            date(2026, 6, 21),
            "Переказ на карту 536354****4120",
            "*8801",
            "Перекази",
            -50,
            "UAH",
        ]
    )
    bio = BytesIO()
    wb.save(bio)
    return bio.getvalue()


class ExcelParserCounterpartyTests(unittest.TestCase):
    def test_counter_party_populated_on_parsed_rows(self) -> None:
        result = parse_excel(_minimal_xlsx_bytes())
        self.assertEqual(result.skipped, 1)
        self.assertEqual(len(result.rows), 2)

        silpo = result.rows[0]
        self.assertEqual(silpo.counter_party, "SILPO")
        self.assertEqual(silpo.currency, "UAH")
        self.assertEqual(silpo.bank_category, "Продукти")

        card_transfer = result.rows[1]
        self.assertEqual(card_transfer.counter_party, "")
        self.assertEqual(card_transfer.note, "Переказ на карту 536354****4120")


if __name__ == "__main__":
    unittest.main()
