"""Domain errors with stable i18n codes."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ErrorMessage:
    """Translatable warning or error (code + format params)."""

    code: str
    params: dict[str, Any] = field(default_factory=dict)

    def key(self) -> tuple[Any, ...]:
        return (self.code, tuple(sorted((k, str(v)) for k, v in self.params.items())))


class AppError(Exception):
    """Raised by domain/clients; routers translate ``code`` for the UI."""

    def __init__(self, code: str, **params: Any) -> None:
        self.code = code
        self.params = params
        super().__init__(code)

    def as_message(self) -> ErrorMessage:
        return ErrorMessage(self.code, dict(self.params))


def merge_messages(*groups: list[ErrorMessage]) -> list[ErrorMessage]:
    seen: set[tuple[Any, ...]] = set()
    out: list[ErrorMessage] = []
    for group in groups:
        for item in group:
            key = item.key()
            if key in seen:
                continue
            seen.add(key)
            out.append(item)
    return out
