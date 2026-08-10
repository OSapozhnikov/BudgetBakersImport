from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

import httpx

logger = logging.getLogger(__name__)

NBU_EXCHANGE_URL = (
    "https://bank.gov.ua/NBUStatService/v1/statdirectory/exchange"
)


@dataclass
class FxConversion:
    original_amount: Decimal
    original_currency: str
    amount_uah: Decimal
    rate: Decimal | None
    rate_date: date | None
    converted: bool
    warning: str | None = None


@dataclass
class FxJobResult:
    conversions: list[FxConversion] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class NbuFxConverter:
    """NBU official rates with per-job in-memory cache and lookback fallback."""

    def __init__(
        self,
        *,
        lookback_days: int = 7,
        client: httpx.Client | None = None,
    ) -> None:
        self.lookback_days = max(0, lookback_days)
        self._client = client or httpx.Client(timeout=20.0)
        self._owns_client = client is None
        self._cache: dict[tuple[date, str], tuple[Decimal, date] | None] = {}

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> NbuFxConverter:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    def convert(
        self,
        amount: Decimal,
        currency: str,
        op_date: date,
    ) -> FxConversion:
        code = (currency or "UAH").upper()
        if code in {"UAH", ""}:
            rounded = _round2(amount)
            return FxConversion(
                original_amount=amount,
                original_currency="UAH",
                amount_uah=rounded,
                rate=Decimal("1"),
                rate_date=op_date,
                converted=False,
            )

        rate_info = self._resolve_rate(code, op_date)
        if rate_info is None:
            warning = (
                f"Курс НБУ для {code} на {op_date.isoformat()} "
                f"(і {self.lookback_days} дн. назад) не знайдено"
            )
            return FxConversion(
                original_amount=amount,
                original_currency=code,
                amount_uah=_round2(amount),
                rate=None,
                rate_date=None,
                converted=False,
                warning=warning,
            )

        rate, rate_date = rate_info
        amount_uah = _round2(amount * rate)
        warning = None
        if rate_date != op_date:
            warning = (
                f"Курс {code} за {op_date.isoformat()} відсутній; "
                f"використано курс за {rate_date.isoformat()} ({rate})"
            )
        return FxConversion(
            original_amount=amount,
            original_currency=code,
            amount_uah=amount_uah,
            rate=rate,
            rate_date=rate_date,
            converted=True,
            warning=warning,
        )

    def _resolve_rate(self, currency: str, op_date: date) -> tuple[Decimal, date] | None:
        for offset in range(0, self.lookback_days + 1):
            d = op_date - timedelta(days=offset)
            cached = self._cache.get((d, currency), "__MISS__")
            if cached != "__MISS__":
                if cached is None:
                    continue
                return cached  # type: ignore[return-value]

            rate = self._fetch_rate(currency, d)
            if rate is None:
                self._cache[(d, currency)] = None
                continue
            pair = (rate, d)
            self._cache[(d, currency)] = pair
            return pair
        return None

    def _fetch_rate(self, currency: str, d: date) -> Decimal | None:
        params = {
            "valcode": currency,
            "date": d.strftime("%Y%m%d"),
            "json": "",
        }
        try:
            resp = self._client.get(NBU_EXCHANGE_URL, params=params)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:  # noqa: BLE001
            logger.warning("NBU request failed for %s %s: %s", currency, d, exc)
            return None

        if not data:
            return None
        try:
            rate = Decimal(str(data[0]["rate"]))
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            logger.warning("Unexpected NBU payload for %s %s: %s (%s)", currency, d, data, exc)
            return None
        return rate


def _round2(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
