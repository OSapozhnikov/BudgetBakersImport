from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.clients.budgetbakers import BudgetBakersClient

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
        client: Any = None,
        page_size: int = 100,
    ) -> None:
        self._http = BudgetBakersClient(base_url=base_url, token=token, client=client)
        self.page_size = page_size

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> BudgetBakersCategoriesClient:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    @property
    def configured(self) -> bool:
        return self._http.configured

    def list_categories(self) -> list[BudgetBakersCategory]:
        items = self._http.paginate_get(
            "/categories",
            page_size=self.page_size,
            resource="/categories",
        )
        results: list[BudgetBakersCategory] = []
        for item in items:
            cat = _parse_category(item)
            if cat:
                results.append(cat)
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
