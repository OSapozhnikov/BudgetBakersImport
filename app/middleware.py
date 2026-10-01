"""Same-origin guard for state-changing HTTP methods."""

from __future__ import annotations

from urllib.parse import urlparse

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response
from starlette.types import ASGIApp

_UNSAFE = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def _origin_host(value: str) -> str:
    parsed = urlparse(value)
    if parsed.netloc:
        return parsed.netloc.lower()
    # Origin can be scheme://host without path; urlparse still fills netloc.
    return value.strip().lower()


class SameOriginMiddleware(BaseHTTPMiddleware):
    """Reject cross-site unsafe requests when the browser sends Origin / Sec-Fetch-Site."""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next) -> Response:  # noqa: ANN001
        if request.method.upper() not in _UNSAFE:
            return await call_next(request)

        fetch_site = (request.headers.get("sec-fetch-site") or "").strip().lower()
        if fetch_site == "cross-site":
            return PlainTextResponse("Forbidden", status_code=403)

        origin = (request.headers.get("origin") or "").strip()
        if origin:
            host = (request.headers.get("host") or "").strip().lower()
            if host and _origin_host(origin) != host:
                return PlainTextResponse("Forbidden", status_code=403)

        return await call_next(request)
