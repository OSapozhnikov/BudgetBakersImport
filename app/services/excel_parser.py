from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from io import BytesIO
from typing import Any

import pandas as pd

# Some bank exports use Latin "C" instead of Cyrillic "С" in "Статус" / "Cтатус".
COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    "status": ("статус", "cтатус"),
    "date": ("дата операції", "дата"),
    "note": ("опис операції", "опис"),
    "card": ("рахунок/картка", "рахунок", "картка"),
    "category": ("категорія",),
    "amount": ("сума",),
    "currency": ("валюта",),
}

COMPLETED_STATUS = "виконано"

CURRENCY_ALIASES: dict[str, str] = {
    "₴": "UAH",
    "грн": "UAH",
    "грн.": "UAH",
    "uah": "UAH",
    "usd": "USD",
    "$": "USD",
    "eur": "EUR",
    "€": "EUR",
}


@dataclass
class ParsedRow:
    date: date
    note: str
    card: str
    bank_category: str
    amount: Decimal
    currency: str
    status: str
    source_row: int


@dataclass
class ParseResult:
    rows: list[ParsedRow] = field(default_factory=list)
    skipped: int = 0
    bank_categories: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _norm_header(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).replace("\xa0", " ").strip().lower()
    # Normalize lookalike Latin C/c before Cyrillic letters in "статус"
    return text


def _find_columns(headers: list[Any]) -> dict[str, int]:
    normalized = [_norm_header(h) for h in headers]
    found: dict[str, int] = {}
    for key, aliases in COLUMN_ALIASES.items():
        for idx, header in enumerate(normalized):
            if not header:
                continue
            if header in aliases or any(header.startswith(a) for a in aliases):
                found[key] = idx
                break
    required = ("date", "note", "category", "amount", "currency")
    missing = [k for k in required if k not in found]
    if missing:
        raise ValueError(
            "Не знайдено обов'язкові колонки: "
            + ", ".join(missing)
            + f". Заголовки файлу: {headers}"
        )
    return found


def _parse_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if value is None or (isinstance(value, float) and pd.isna(value)):
        raise ValueError("порожня дата")
    text = str(value).strip()
    for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(text[:10], fmt).date()
        except ValueError:
            continue
    # Excel serial date
    try:
        parsed = pd.to_datetime(value, dayfirst=True)
        return parsed.date()
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"невідомий формат дати: {value!r}") from exc


def _parse_amount(value: Any) -> Decimal:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        raise ValueError("порожня сума")
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    text = (
        str(value)
        .strip()
        .replace("\xa0", "")
        .replace(" ", "")
        .replace(",", ".")
    )
    try:
        return Decimal(text)
    except InvalidOperation as exc:
        raise ValueError(f"невідома сума: {value!r}") from exc


def normalize_currency(value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "UAH"
    raw = str(value).strip()
    key = raw.lower()
    return CURRENCY_ALIASES.get(key, CURRENCY_ALIASES.get(raw, raw.upper()))


def _is_completed(status: Any) -> bool:
    if status is None or (isinstance(status, float) and pd.isna(status)):
        # No status column / empty → keep row
        return True
    text = str(status).strip().splitlines()[0].strip().lower()
    return text == COMPLETED_STATUS


def parse_excel(content: bytes) -> ParseResult:
    """Parse bank Excel export (BudgetBakers-compatible column layout) into rows."""
    bio = BytesIO(content)
    # Prefer openpyxl via pandas; engine auto for xlsx
    df = pd.read_excel(bio, dtype=object, engine="openpyxl")
    if df.empty:
        return ParseResult(warnings=["Файл порожній."])

    columns = list(df.columns)
    colmap = _find_columns(columns)
    result = ParseResult()
    categories: set[str] = set()

    for idx, series in df.iterrows():
        source_row = int(idx) + 2  # header is row 1
        status_val = series.iloc[colmap["status"]] if "status" in colmap else None
        if not _is_completed(status_val):
            result.skipped += 1
            continue
        try:
            op_date = _parse_date(series.iloc[colmap["date"]])
            amount = _parse_amount(series.iloc[colmap["amount"]])
            currency = normalize_currency(series.iloc[colmap["currency"]])
            note = series.iloc[colmap["note"]]
            category = series.iloc[colmap["category"]]
            card = series.iloc[colmap["card"]] if "card" in colmap else ""
            note_s = "" if note is None or (isinstance(note, float) and pd.isna(note)) else str(note).strip()
            cat_s = (
                ""
                if category is None or (isinstance(category, float) and pd.isna(category))
                else str(category).strip()
            )
            card_s = (
                ""
                if card is None or (isinstance(card, float) and pd.isna(card))
                else str(card).strip()
            )
            status_s = (
                ""
                if status_val is None or (isinstance(status_val, float) and pd.isna(status_val))
                else str(status_val).strip().splitlines()[0].strip()
            )
        except ValueError as exc:
            result.warnings.append(f"Рядок {source_row}: пропущено ({exc})")
            result.skipped += 1
            continue

        if cat_s:
            categories.add(cat_s)
        result.rows.append(
            ParsedRow(
                date=op_date,
                note=note_s,
                card=card_s,
                bank_category=cat_s,
                amount=amount,
                currency=currency,
                status=status_s,
                source_row=source_row,
            )
        )

    result.bank_categories = sorted(categories)
    if not result.rows:
        result.warnings.append("Немає рядків зі статусом «Виконано».")
    return result
