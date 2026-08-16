"""Shared BudgetBakers Wallet HTTP adapter."""

from __future__ import annotations

from typing import Any

import httpx

from app.errors import AppError

RESOURCE_ACCOUNTS = "/accounts"
RESOURCE_CATEGORIES = "/categories"
RESOURCE_RECORDS = "/records"


def extract_items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if isinstance(payload, dict):
        for key in ("data", "items", "categories", "accounts", "results", "records"):
            value = payload.get(key)
            if isinstance(value, list):
                return [x for x in value if isinstance(x, dict)]
        if "id" in payload and "name" in payload:
            return [payload]
    return []


def response_json(resp: httpx.Response) -> Any:
    try:
        return resp.json()
    except ValueError:
        return None


def http_error_text(resp: httpx.Response) -> str:
    payload = response_json(resp)
    if isinstance(payload, dict):
        text = payload.get("message") or payload.get("error") or payload.get("detail")
        if isinstance(text, dict):
            text = text.get("message") or text.get("error")
        if text:
            return str(text)
    body = (resp.text or "").strip()
    return body[:300] if body else ""


class BudgetBakersClient:
    """Bearer HTTP client with pagination and Wallet error mapping."""

    def __init__(
        self,
        *,
        base_url: str,
        token: str,
        client: httpx.Client | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token.strip()
        self._client = client or httpx.Client(timeout=timeout)
        self._owns_client = client is None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> BudgetBakersClient:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    @property
    def configured(self) -> bool:
        return bool(self.token)

    def require_token(self) -> None:
        if not self.token:
            raise AppError("wallet.token_missing")

    def headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
        }

    def request(
        self,
        method: str,
        path: str,
        *,
        params: Any = None,
        json: Any = None,
    ) -> httpx.Response:
        url = f"{self.base_url}{path}" if path.startswith("/") else f"{self.base_url}/{path}"
        try:
            return self._client.request(
                method,
                url,
                headers=self.headers(),
                params=params,
                json=json,
            )
        except httpx.HTTPError as exc:
            raise AppError("wallet.network", exc=str(exc)) from exc

    def raise_for_status(self, resp: httpx.Response, *, resource: str) -> None:
        if resp.status_code == 401:
            raise AppError("wallet.unauthorized")
        if resp.status_code == 403:
            raise AppError("wallet.forbidden")
        if resp.status_code == 429:
            raise AppError("wallet.rate_limited")
        if resp.status_code == 404:
            raise AppError("wallet.not_found", resource=resource)
        if resp.status_code >= 400:
            text = http_error_text(resp) or f"unexpected response ({resp.status_code})"
            raise AppError("wallet.http_error", status=resp.status_code, text=text)

    def paginate_get(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        page_size: int = 100,
        resource: str,
    ) -> list[dict[str, Any]]:
        self.require_token()
        results: list[dict[str, Any]] = []
        offset = 0
        extra = dict(params or {})
        while True:
            query: dict[str, Any] = {**extra, "limit": page_size, "offset": offset}
            resp = self.request("GET", path, params=query)
            self.raise_for_status(resp, resource=resource)
            payload = response_json(resp)
            items = extract_items(payload)
            if not items:
                break
            results.extend(items)
            next_offset = payload.get("nextOffset") if isinstance(payload, dict) else None
            if next_offset is None or next_offset == offset:
                if len(items) < page_size:
                    break
                offset += len(items)
            else:
                offset = int(next_offset)
        return results
