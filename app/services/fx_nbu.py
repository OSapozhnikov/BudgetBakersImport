from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any

import httpx

from app.errors import ErrorMessage
from app.persistence.json_store import JsonFileStore

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
    warning: ErrorMessage | None = None


@dataclass
class FxJobResult:
    conversions: list[FxConversion] = field(default_factory=list)
    warnings: list[ErrorMessage] = field(default_factory=list)


class NbuFxConverter:
    """NBU official rates with L1 memory cache, optional disk cache, and lookback."""

    def __init__(
        self,
        *,
        lookback_days: int = 7,
        client: httpx.Client | None = None,
        data_dir: str | Path | None = None,
    ) -> None:
        self.lookback_days = max(0, lookback_days)
        self._client = client or httpx.Client(timeout=20.0)
        self._owns_client = client is None
        self._cache: dict[tuple[date, str], tuple[Decimal, date] | None] = {}
        self._disk: JsonFileStore | None = None
        if data_dir is not None:
            self._disk = JsonFileStore(Path(data_dir) / "nbu_fx_cache.json")
            self._load_disk()

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
            warning = ErrorMessage(
                "fx.rate_missing",
                {
                    "source_row": "",
                    "currency": code,
                    "op_date": op_date.isoformat(),
                    "lookback": self.lookback_days,
                },
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
            warning = ErrorMessage(
                "fx.rate_lookback",
                {
                    "source_row": "",
                    "currency": code,
                    "op_date": op_date.isoformat(),
                    "rate_date": rate_date.isoformat(),
                    "rate": str(rate),
                },
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
            self._persist_rate(d, currency, rate)
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

    def _load_disk(self) -> None:
        if self._disk is None:
            return
        raw = self._disk.load(default={})
        if not isinstance(raw, dict):
            return
        rates = raw.get("rates") if "rates" in raw else raw
        if not isinstance(rates, dict):
            return
        for key, value in rates.items():
            if not isinstance(key, str) or "|" not in key or value in (None, ""):
                continue
            day_s, currency = key.split("|", 1)
            try:
                day = date.fromisoformat(day_s)
                rate = Decimal(str(value))
            except (ValueError, TypeError):
                continue
            self._cache[(day, currency)] = (rate, day)

    def _persist_rate(self, d: date, currency: str, rate: Decimal) -> None:
        if self._disk is None:
            return
        key = f"{d.isoformat()}|{currency}"

        def apply(raw: object) -> dict[str, Any]:
            payload = dict(raw) if isinstance(raw, dict) else {}
            rates = dict(payload.get("rates") or {})
            rates[key] = str(rate)
            payload["rates"] = rates
            return payload

        try:
            self._disk.mutate(apply, default={"rates": {}})
        except OSError as exc:
            logger.warning("Failed to persist NBU rate %s: %s", key, exc)


def _round2(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
