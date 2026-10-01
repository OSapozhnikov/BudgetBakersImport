from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.clients.budgetbakers import BudgetBakersClient


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
        client: Any = None,
        page_size: int = 100,
        max_pages: int = 50,
        max_items: int = 10_000,
    ) -> None:
        self._http = BudgetBakersClient(
            base_url=base_url,
            token=token,
            client=client,
            max_pages=max_pages,
            max_items=max_items,
        )
        self.page_size = page_size

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> BudgetBakersAccountsClient:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    @property
    def configured(self) -> bool:
        return self._http.configured

    def list_accounts(self, *, include_archived: bool = False) -> list[BudgetBakersAccount]:
        items = self._http.paginate_get(
            "/accounts",
            page_size=self.page_size,
            resource="/accounts",
        )
        results: list[BudgetBakersAccount] = []
        for item in items:
            acc = _parse_account(item)
            if not acc:
                continue
            if acc.archived and not include_archived:
                continue
            results.append(acc)
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
