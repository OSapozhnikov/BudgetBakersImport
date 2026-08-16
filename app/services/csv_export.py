from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from io import StringIO
from typing import Iterable

from app.services.excel_parser import ParsedRow
from app.services.fx_nbu import FxConversion, NbuFxConverter
from app.services.mapping_store import CategoryMappingStore

# BudgetBakers-accepted CSV layout. First letter of "Cтатус" is Latin C (U+0043).
CSV_COLUMNS = (
    "Cтатус",
    "Дата операції",
    "Опис операції",
    "Рахунок/картка",
    "Категорія",
    "Сума",
    "Валюта",
)

COMPLETED_STATUS_LABEL = "Виконано"
CURRENCY_UAH_SYMBOL = "₴"


@dataclass
class ExportRow:
    date: date
    account: str
    category: str
    amount: Decimal
    note: str
    currency: str
    bank_category: str
    original_amount: Decimal
    original_currency: str
    mapped: bool
    fx_converted: bool
    fx_warning: str | None = None
    unmapped: bool = False
    counter_party: str = ""
    is_duplicate: bool = False


@dataclass
class ConversionResult:
    rows: list[ExportRow] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    converted_fx_count: int = 0
    fx_failures: int = 0
    unmapped_categories: list[str] = field(default_factory=list)
    skipped: int = 0
    bank_categories: list[str] = field(default_factory=list)


def convert_rows(
    parsed_rows: Iterable[ParsedRow],
    *,
    account_name: str,
    mapping_store: CategoryMappingStore,
    fx: NbuFxConverter,
) -> ConversionResult:
    result = ConversionResult()
    unmapped: set[str] = set()

    for parsed in parsed_rows:
        fx_conv: FxConversion = fx.convert(parsed.amount, parsed.currency, parsed.date)
        mapped_name, was_mapped = mapping_store.map_category(parsed.bank_category)
        if not was_mapped and parsed.bank_category:
            unmapped.add(parsed.bank_category)

        if fx_conv.warning:
            result.warnings.append(
                f"Рядок {parsed.source_row} ({parsed.date.isoformat()}): {fx_conv.warning}"
            )
        if fx_conv.converted:
            result.converted_fx_count += 1
        elif fx_conv.original_currency != "UAH" and fx_conv.rate is None:
            result.fx_failures += 1

        result.rows.append(
            ExportRow(
                date=parsed.date,
                account=account_name,
                category=mapped_name,
                amount=fx_conv.amount_uah,
                note=parsed.note,
                currency="UAH",
                bank_category=parsed.bank_category,
                original_amount=parsed.amount,
                original_currency=parsed.currency,
                mapped=was_mapped,
                fx_converted=fx_conv.converted,
                fx_warning=fx_conv.warning,
                unmapped=not was_mapped and bool(parsed.bank_category),
                counter_party=parsed.counter_party or "",
            )
        )

    result.unmapped_categories = sorted(unmapped)
    return result


def _format_amount(amount: Decimal) -> str:
    """Strip trailing zeros (-1003, -4397.9, -2039.32) for BudgetBakers CSV amounts."""
    text = f"{amount:.2f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def build_export_filename(account_name: str, rows: Iterable[ExportRow]) -> str:
    """Build download name: bbi-<accountName>-<dateStart>-<dateEnd>.csv.

    Spaces are stripped from the account name. Dates are DD.MM.YYYY from the
    min/max operation dates among converted rows (single-day range allowed).
    """
    account = "".join((account_name or "").split()) or "Account"
    row_list = list(rows)
    if row_list:
        dates = [r.date for r in row_list]
        start = min(dates).strftime("%d.%m.%Y")
        end = max(dates).strftime("%d.%m.%Y")
    else:
        today = date.today().strftime("%d.%m.%Y")
        start = end = today
    return f"bbi-{account}-{start}-{end}.csv"


def build_csv(rows: Iterable[ExportRow]) -> bytes:
    """Build BudgetBakers-accepted CSV (utf-8-sig, comma, CRLF, DD.MM.YYYY, ₴)."""
    buf = StringIO()
    writer = csv.DictWriter(
        buf,
        fieldnames=list(CSV_COLUMNS),
        delimiter=",",
        lineterminator="\r\n",
        quoting=csv.QUOTE_MINIMAL,
    )
    writer.writeheader()
    for row in rows:
        writer.writerow(
            {
                "Cтатус": COMPLETED_STATUS_LABEL,
                "Дата операції": row.date.strftime("%d.%m.%Y"),
                "Опис операції": row.note,
                "Рахунок/картка": row.account,
                "Категорія": row.category,
                "Сума": _format_amount(row.amount),
                "Валюта": CURRENCY_UAH_SYMBOL,
            }
        )
    return buf.getvalue().encode("utf-8-sig")
