from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Iterable, Mapping, Sequence

import httpx

from app.services.counterparty import COUNTERPARTY_MAX_LEN
from app.services.csv_export import ExportRow

RECORDS_BATCH_SIZE = 20
NOTE_MAX_LEN = 255
RECORDS_PAGE_SIZE = 100
_TWO_PLACES = Decimal("0.01")


@dataclass(frozen=True)
class RecordItemError:
    """One failed (or unparsed) item from POST /records."""

    row_index: int
    date: str
    note: str
    error: str
    error_type: str | None = None


@dataclass
class RecordImportResult:
    """Outcome of posting ExportRow items to BudgetBakers.

    For a complete run (no abort):
        succeeded + failed + skipped_zero == number of input rows.
    After an abort (401/403/429/etc.), ``not_sent`` is the remainder that
    never left the client; those rows are not in ``failed``.

    ``succeeded_indices`` are indices into the original ``rows`` iterable
    passed to ``import_rows`` (not batch-local positions).
    """

    succeeded: int = 0
    failed: int = 0
    skipped_zero: int = 0
    not_sent: int = 0
    errors: list[RecordItemError] = field(default_factory=list)
    succeeded_indices: list[int] = field(default_factory=list)
    fatal_error: str | None = None
    aborted: bool = False

    @property
    def posted(self) -> int:
        """Rows actually included in an HTTP request."""
        return self.succeeded + self.failed


@dataclass(frozen=True)
class _PreparedRecord:
    row_index: int
    date: str
    note: str
    payload: dict[str, Any]


class BudgetBakersRecordsClient:
    """Create records via BudgetBakers POST /records (batches of 20)."""

    def __init__(
        self,
        *,
        base_url: str,
        token: str,
        client: httpx.Client | None = None,
        batch_size: int = RECORDS_BATCH_SIZE,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token.strip()
        self.batch_size = min(max(int(batch_size), 1), RECORDS_BATCH_SIZE)
        self._client = client or httpx.Client(timeout=30.0)
        self._owns_client = client is None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> BudgetBakersRecordsClient:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    @property
    def configured(self) -> bool:
        return bool(self.token)

    def list_records(
        self,
        *,
        account_id: str,
        date_from: date,
        date_to: date,
        page_size: int = RECORDS_PAGE_SIZE,
    ) -> list[dict[str, Any]]:
        """Fetch Wallet records for an account in a date range (paginated).

        Uses ``recordDate=gte.`` / ``lte.`` and ``accountId`` filters.
        """
        if not self.token:
            raise RuntimeError(
                "BUDGETBAKERS_API_TOKEN не задано. "
                "Додайте токен у .env щоб завантажити записи."
            )
        account = str(account_id or "").strip()
        if not account:
            raise ValueError("accountId порожній.")

        headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
        }
        url = f"{self.base_url}/records"
        limit = min(max(int(page_size), 1), 200)
        start = date_from.isoformat()
        end = date_to.isoformat()
        results: list[dict[str, Any]] = []
        offset = 0

        while True:
            params: dict[str, Any] = {
                "limit": limit,
                "offset": offset,
                "accountId": account,
                "recordDate": [f"gte.{start}", f"lte.{end}"],
            }
            resp = self._client.get(url, headers=headers, params=params)
            if resp.status_code in (401, 403, 404, 429):
                raise RuntimeError(_auth_or_limit_message(resp))
            if resp.status_code >= 400:
                raise RuntimeError(_http_error_message(resp))
            payload = _response_json(resp)
            items = _result_items(payload)
            if not items:
                break
            results.extend(items)
            if len(items) < limit:
                break
            offset += len(items)

        return results

    def import_rows(
        self,
        rows: Iterable[ExportRow],
        *,
        account_id: str,
        category_cache: Iterable[Mapping[str, Any]] | None = None,
        category_ids: Mapping[str, str] | None = None,
    ) -> RecordImportResult:
        """Skip zero amounts, resolve category IDs, POST in batches of 20.

        ``category_ids`` is a casefolded name → UUID map. If omitted, it is
        built from ``category_cache`` (items from ``bb_categories_cache.json``).
        Unknown / empty category names omit ``categoryId``.
        """
        if not self.token:
            raise RuntimeError(
                "BUDGETBAKERS_API_TOKEN не задано. "
                "Додайте токен у .env щоб імпортувати записи."
            )
        account = str(account_id or "").strip()
        if not account:
            raise ValueError("accountId порожній.")

        if category_ids is not None:
            id_map = {
                str(name).strip().casefold(): str(cat_id)
                for name, cat_id in category_ids.items()
                if str(name).strip() and cat_id not in (None, "")
            }
        else:
            id_map = category_ids_by_name(category_cache or [])

        result = RecordImportResult()
        prepared: list[_PreparedRecord] = []
        for index, row in enumerate(rows):
            name = (row.category or "").strip()
            cat_id = id_map.get(name.casefold()) if name else None
            payload = build_record_payload(row, account_id=account, category_id=cat_id)
            if payload is None:
                result.skipped_zero += 1
                continue
            note = str(payload.get("note") or "")
            prepared.append(
                _PreparedRecord(
                    row_index=index,
                    date=row.date.isoformat(),
                    note=note,
                    payload=payload,
                )
            )

        if not prepared:
            return result

        headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
        }
        url = f"{self.base_url}/records"

        for offset in range(0, len(prepared), self.batch_size):
            batch = prepared[offset : offset + self.batch_size]
            try:
                resp = self._client.post(
                    url,
                    headers=headers,
                    json=[item.payload for item in batch],
                )
            except httpx.HTTPError as exc:
                _fail_batch(result, batch, f"Помилка мережі: {exc}", error_type="network")
                result.fatal_error = str(exc)
                result.aborted = True
                result.not_sent = len(prepared) - offset - len(batch)
                return result

            if resp.status_code in (401, 403, 404, 429):
                message = _auth_or_limit_message(resp)
                _fail_batch(result, batch, message, error_type="http")
                result.fatal_error = message
                result.aborted = True
                result.not_sent = len(prepared) - offset - len(batch)
                return result

            if resp.status_code not in (200, 207):
                message = _http_error_message(resp)
                _fail_batch(result, batch, message, error_type="http")
                result.fatal_error = message
                result.aborted = True
                result.not_sent = len(prepared) - offset - len(batch)
                return result

            payload = _response_json(resp)
            succeeded_indices, errors = _parse_batch_results(
                resp.status_code, payload, batch
            )
            result.succeeded += len(succeeded_indices)
            result.failed += len(batch) - len(succeeded_indices)
            result.succeeded_indices.extend(succeeded_indices)
            result.errors.extend(errors)

        return result


def category_ids_by_name(cache_items: Iterable[Mapping[str, Any]]) -> dict[str, str]:
    """Case-insensitive mapped category name → BudgetBakers UUID.

    Built from ``bb_categories_cache.json`` dicts (``id`` + ``name``).
    First occurrence of a name wins.
    """
    mapping: dict[str, str] = {}
    for item in cache_items:
        name = str(item.get("name") or "").strip()
        cat_id = item.get("id")
        if not name or cat_id in (None, ""):
            continue
        key = name.casefold()
        if key not in mapping:
            mapping[key] = str(cat_id)
    return mapping


def build_record_payload(
    row: ExportRow,
    *,
    account_id: str,
    category_id: str | None = None,
) -> dict[str, Any] | None:
    """Build one POST /records item, or None if the amount is zero at 2 dp."""
    amount = _quantize_amount(row.amount)
    if amount == 0:
        return None

    currency = (row.currency or "").strip().upper() or "UAH"
    payload: dict[str, Any] = {
        "accountId": account_id,
        "amount": {"value": float(str(amount)), "currencyCode": currency},
        "recordDate": f"{row.date.isoformat()}T12:00:00Z",
        "recordState": "cleared",
    }
    if category_id:
        payload["categoryId"] = str(category_id)
    note = (row.note or "").strip()
    if note:
        payload["note"] = note[:NOTE_MAX_LEN]
    counter_party = (row.counter_party or "").strip()
    if counter_party:
        payload["counterParty"] = counter_party[:COUNTERPARTY_MAX_LEN]
    return payload


def _quantize_amount(amount: Decimal) -> Decimal:
    return amount.quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)


def _fail_batch(
    result: RecordImportResult,
    batch: Sequence[_PreparedRecord],
    message: str,
    *,
    error_type: str,
) -> None:
    result.failed += len(batch)
    for item in batch:
        result.errors.append(
            RecordItemError(
                row_index=item.row_index,
                date=item.date,
                note=item.note,
                error=message,
                error_type=error_type,
            )
        )


def _parse_batch_results(
    status_code: int,
    payload: Any,
    batch: Sequence[_PreparedRecord],
) -> tuple[list[int], list[RecordItemError]]:
    """Return (original-row indices that succeeded, item errors)."""
    items = _result_items(payload)
    if status_code == 200 and not items:
        return [item.row_index for item in batch], []

    errors: list[RecordItemError] = []
    seen: set[int] = set()
    succeeded_indices: list[int] = []

    for position, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        idx = _result_index(item, position, len(batch))
        if idx in seen:
            continue
        seen.add(idx)
        prepared = batch[idx]
        if _item_succeeded(item):
            succeeded_indices.append(prepared.row_index)
            continue
        errors.append(
            RecordItemError(
                row_index=prepared.row_index,
                date=prepared.date,
                note=prepared.note,
                error=_item_error_message(item),
                error_type=_item_error_type(item),
            )
        )

    for idx, prepared in enumerate(batch):
        if idx in seen:
            continue
        if status_code == 200:
            succeeded_indices.append(prepared.row_index)
            continue
        errors.append(
            RecordItemError(
                row_index=prepared.row_index,
                date=prepared.date,
                note=prepared.note,
                error="Немає результату для цього рядка в відповіді API.",
                error_type="unknown",
            )
        )

    return succeeded_indices, errors


def _result_items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if isinstance(payload, dict):
        for key in ("results", "data", "items", "records"):
            value = payload.get(key)
            if isinstance(value, list):
                return [x for x in value if isinstance(x, dict)]
    return []


def _result_index(item: dict[str, Any], position: int, batch_len: int) -> int:
    raw = item.get("inputIndex", item.get("index"))
    if isinstance(raw, int) and 0 <= raw < batch_len:
        return raw
    if isinstance(raw, str) and raw.isdigit():
        parsed = int(raw)
        if 0 <= parsed < batch_len:
            return parsed
    return min(position, batch_len - 1)


def _item_succeeded(item: dict[str, Any]) -> bool:
    if "success" in item:
        return bool(item["success"])
    if item.get("error") or item.get("errorType") or item.get("error_type"):
        return False
    return bool(item.get("id"))


def _item_error_message(item: dict[str, Any]) -> str:
    err = item.get("error")
    if isinstance(err, dict):
        text = err.get("message") or err.get("error") or err.get("code")
        if text:
            return str(text)
    if err not in (None, "", False):
        return str(err)
    for key in ("message", "detail", "title"):
        value = item.get(key)
        if value:
            return str(value)
    return "Помилка створення запису."


def _item_error_type(item: dict[str, Any]) -> str | None:
    raw = item.get("errorType") or item.get("error_type")
    if raw:
        return str(raw)
    return None


def _response_json(resp: httpx.Response) -> Any:
    try:
        return resp.json()
    except ValueError:
        return None


def _http_error_message(resp: httpx.Response) -> str:
    payload = _response_json(resp)
    if isinstance(payload, dict):
        text = payload.get("message") or payload.get("error") or payload.get("detail")
        if isinstance(text, dict):
            text = text.get("message") or text.get("error")
        if text:
            return f"BudgetBakers API ({resp.status_code}): {text}"
    body = (resp.text or "").strip()
    if body:
        return f"BudgetBakers API ({resp.status_code}): {body[:300]}"
    return f"BudgetBakers API: неочікувана відповідь ({resp.status_code})."


def _auth_or_limit_message(resp: httpx.Response) -> str:
    if resp.status_code == 401:
        return "BudgetBakers API: невірний або протермінований токен (401)."
    if resp.status_code == 403:
        return "BudgetBakers API: доступ заборонено (403)."
    if resp.status_code == 429:
        return "BudgetBakers API: перевищено ліміт запитів (429)."
    if resp.status_code == 404:
        return (
            "BudgetBakers API: 404 для /records. "
            "Перевірте BUDGETBAKERS_API_BASE "
            "(очікується https://rest.budgetbakers.com/wallet/v1/api)."
        )
    return _http_error_message(resp)
