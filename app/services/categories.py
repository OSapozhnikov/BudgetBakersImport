from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BudgetBakersCategory:
    id: str
    name: str
    color: str | None = None
    parent_id: str | None = None


class BudgetBakersCategoriesClient:
    """Fetch categories from BudgetBakers GET /categories (paginated)."""

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

    def __enter__(self) -> BudgetBakersCategoriesClient:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    @property
    def configured(self) -> bool:
        return bool(self.token)

    def list_categories(self) -> list[BudgetBakersCategory]:
        if not self.token:
            raise RuntimeError(
                "BUDGETBAKERS_API_TOKEN не задано. "
                "Додайте токен у .env щоб завантажити категорії."
            )

        headers = {"Authorization": f"Bearer {self.token}", "Accept": "application/json"}
        results: list[BudgetBakersCategory] = []
        offset = 0

        while True:
            params = {"limit": self.page_size, "offset": offset}
            url = f"{self.base_url}/categories"
            resp = self._client.get(url, headers=headers, params=params)
            if resp.status_code == 401:
                raise RuntimeError("BudgetBakers API: невірний або протермінований токен (401).")
            resp.raise_for_status()
            payload = resp.json()
            items = _extract_items(payload)
            if not items:
                break
            for item in items:
                cat = _parse_category(item)
                if cat:
                    results.append(cat)
            if len(items) < self.page_size:
                break
            offset += self.page_size

        # Deduplicate by id, then sort by name
        by_id = {c.id: c for c in results}
        return sorted(by_id.values(), key=lambda c: c.name.casefold())


def _extract_items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if isinstance(payload, dict):
        for key in ("data", "items", "categories", "accounts", "results"):
            value = payload.get(key)
            if isinstance(value, list):
                return [x for x in value if isinstance(x, dict)]
        # Single object wrapped
        if "id" in payload and "name" in payload:
            return [payload]
    return []


def _parse_category(item: dict[str, Any]) -> BudgetBakersCategory | None:
    cat_id = item.get("id") or item.get("_id") or item.get("uuid")
    name = item.get("name") or item.get("title")
    if not cat_id or not name:
        return None
    return BudgetBakersCategory(
        id=str(cat_id),
        name=str(name),
        color=str(item["color"]) if item.get("color") else None,
        parent_id=str(item["parentId"]) if item.get("parentId") else (
            str(item["parent_id"]) if item.get("parent_id") else None
        ),
    )
