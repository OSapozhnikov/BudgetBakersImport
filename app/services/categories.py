from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# Non-assignable system categories (Wallet hides these from normal expense mapping).
EXCLUDED_CATEGORY_NAMES = frozenset(
    {"Debt", "Transfer", "Shopping list", "Uncategorized"}
)
EXCLUDED_GROUP_IDS = frozenset({"system_categories"})


@dataclass(frozen=True)
class BudgetBakersCategory:
    id: str
    name: str
    color: str | None = None
    group_id: str | None = None
    group_name: str | None = None
    archived: bool = False
    enabled: bool = True
    system_id: str | None = None
    custom_category: bool | None = None


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
            if resp.status_code == 404:
                raise RuntimeError(
                    "BudgetBakers API: 404 для /categories. "
                    "Перевірте BUDGETBAKERS_API_BASE "
                    "(очікується https://rest.budgetbakers.com/wallet/v1/api)."
                )
            resp.raise_for_status()
            payload = resp.json()
            items = _extract_items(payload)
            if not items:
                break
            for item in items:
                cat = _parse_category(item)
                if cat:
                    results.append(cat)
            next_offset = payload.get("nextOffset") if isinstance(payload, dict) else None
            if next_offset is None or next_offset == offset:
                if len(items) < self.page_size:
                    break
                offset += self.page_size
            else:
                offset = int(next_offset)

        # Deduplicate by id, then sort by group → category name (Wallet order)
        by_id = {c.id: c for c in results}
        return sorted(
            by_id.values(),
            key=lambda c: ((c.group_name or "").casefold(), c.name.casefold()),
        )


def category_to_cache_dict(cat: BudgetBakersCategory) -> dict[str, Any]:
    return {
        "id": cat.id,
        "name": cat.name,
        "group_id": cat.group_id,
        "group_name": cat.group_name,
        "color": cat.color,
        "archived": cat.archived,
        "enabled": cat.enabled,
        "system_id": cat.system_id,
        "custom_category": cat.custom_category,
    }


def is_assignable_category(item: dict[str, Any] | BudgetBakersCategory) -> bool:
    """Whether a category can appear in the mapping dropdown."""
    if isinstance(item, BudgetBakersCategory):
        archived = item.archived
        enabled = item.enabled
        name = item.name
        group_id = item.group_id or ""
        group_name = item.group_name or ""
    else:
        archived = bool(item.get("archived", False))
        enabled_raw = item.get("enabled", True)
        enabled = True if enabled_raw is None else bool(enabled_raw)
        name = str(item.get("name") or "")
        group_id = str(item.get("group_id") or "")
        group_name = str(item.get("group_name") or "")

    if archived or not enabled:
        return False
    if name in EXCLUDED_CATEGORY_NAMES:
        return False
    if group_id in EXCLUDED_GROUP_IDS:
        return False
    if group_name.casefold() == "system categories":
        return False
    return bool(name)


def grouped_bb_categories(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Build ordered groups for mapping selects:
    [{ "group_name": "Food & Drinks", "items": [{name, color, id}, ...] }, ...]
    """
    buckets: dict[str, list[dict[str, Any]]] = {}
    group_order: list[str] = []

    for item in items:
        if not is_assignable_category(item):
            continue
        group_name = str(item.get("group_name") or "").strip() or "—"
        entry = {
            "id": item.get("id"),
            "name": str(item["name"]),
            "color": item.get("color"),
        }
        if group_name not in buckets:
            buckets[group_name] = []
            group_order.append(group_name)
        buckets[group_name].append(entry)

    result: list[dict[str, Any]] = []
    for group_name in sorted(group_order, key=str.casefold):
        cats = sorted(buckets[group_name], key=lambda c: c["name"].casefold())
        result.append({"group_name": group_name, "items": cats})
    return result


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

    group_id: str | None = None
    group_name: str | None = None
    group = item.get("group")
    if isinstance(group, dict):
        if group.get("id") is not None:
            group_id = str(group["id"])
        if group.get("name") is not None:
            group_name = str(group["name"])
    elif isinstance(group, str) and group.strip():
        group_name = group.strip()

    enabled_raw = item.get("enabled", True)
    enabled = True if enabled_raw is None else bool(enabled_raw)

    custom_raw = item.get("customCategory", item.get("custom_category"))
    custom_category: bool | None
    if custom_raw is None:
        custom_category = None
    else:
        custom_category = bool(custom_raw)

    system_id = item.get("systemId") or item.get("system_id")

    return BudgetBakersCategory(
        id=str(cat_id),
        name=str(name),
        color=str(item["color"]) if item.get("color") else None,
        group_id=group_id,
        group_name=group_name,
        archived=bool(item.get("archived", False)),
        enabled=enabled,
        system_id=str(system_id) if system_id else None,
        custom_category=custom_category,
    )
