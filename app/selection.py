"""Row index selection for preview forms."""

from __future__ import annotations

from app.services.csv_export import ExportRow


def rows_by_indices(rows: list[ExportRow], indices: list[int]) -> list[ExportRow]:
    """Return rows for valid, unique indices in the order they appear in the form."""
    selected: list[ExportRow] = []
    seen: set[int] = set()
    n = len(rows)
    for idx in indices:
        if idx < 0 or idx >= n or idx in seen:
            continue
        seen.add(idx)
        selected.append(rows[idx])
    return selected


def unique_indices(rows_len: int, indices: list[int]) -> list[int]:
    selected: list[int] = []
    seen: set[int] = set()
    for idx in indices:
        if idx < 0 or idx >= rows_len or idx in seen:
            continue
        seen.add(idx)
        selected.append(idx)
    return selected
