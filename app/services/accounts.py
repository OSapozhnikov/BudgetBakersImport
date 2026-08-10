from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from app.services.categories import _extract_items


@dataclass(frozen=True)
class BudgetBakersAccount:
    id: str
    name: str
    currency_code: str | None = None
    archived: bool = False


class BudgetBakersAccountsClient:
    """Fetch accounts from BudgetBakers GET /accounts (paginated)."""

    def __init__(
        self,
        *,
        base_url: str,
        token: str,
        client: httpx.Client | None = None,
        page_size: int = 100,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token.strip()
        self.page_size = page_size
        self._client = client or httpx.Client(timeout=30.0)
        self._owns_client = client is None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> BudgetBakersAccountsClient:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    @property
    def configured(self) -> bool:
        return bool(self.token)

    def list_accounts(self, *, include_archived: bool = False) -> list[BudgetBakersAccount]:
        if not self.token:
            raise RuntimeError(
                "BUDGETBAKERS_API_TOKEN не задано. "
                "Додайте токен у .env щоб завантажити рахунки."
            )

        headers = {"Authorization": f"Bearer {self.token}", "Accept": "application/json"}
        results: list[BudgetBakersAccount] = []
        offset = 0

        while True:
            params = {"limit": self.page_size, "offset": offset}
            url = f"{self.base_url}/accounts"
            resp = self._client.get(url, headers=headers, params=params)
            if resp.status_code == 401:
                raise RuntimeError("BudgetBakers API: невірний або протермінований токен (401).")
            if resp.status_code == 404:
                raise RuntimeError(
                    "BudgetBakers API: 404 для /accounts. "
                    "Перевірте BUDGETBAKERS_API_BASE "
                    "(очікується https://rest.budgetbakers.com/wallet/v1/api)."
                )
            resp.raise_for_status()
            payload = resp.json()
            items = _extract_items(payload)
            if not items:
                break
            for item in items:
                acc = _parse_account(item)
                if not acc:
                    continue
                if acc.archived and not include_archived:
                    continue
                results.append(acc)
            next_offset = payload.get("nextOffset") if isinstance(payload, dict) else None
            if next_offset is None or next_offset == offset:
                if len(items) < self.page_size:
                    break
                offset += self.page_size
            else:
                offset = int(next_offset)

        by_id = {a.id: a for a in results}
        return sorted(by_id.values(), key=lambda a: a.name.casefold())


def _parse_account(item: dict[str, Any]) -> BudgetBakersAccount | None:
    account_id = item.get("id") or item.get("_id") or item.get("uuid")
    name = item.get("name") or item.get("title")
    if not account_id or not name:
        return None
    archived = bool(item.get("archived") or item.get("isArchived"))
    currency = item.get("currencyCode") or item.get("currency_code") or item.get("currency")
    return BudgetBakersAccount(
        id=str(account_id),
        name=str(name),
        currency_code=str(currency) if currency else None,
        archived=archived,
    )
