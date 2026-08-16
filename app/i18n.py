"""Ukrainian / English UI translations loaded from app/locales/*.json."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from starlette.requests import Request
from starlette.responses import Response

from app.errors import ErrorMessage

COOKIE_NAME = "bbi_lang"
DEFAULT_LANG = "uk"
SUPPORTED_LANGS = ("uk", "en")
COOKIE_MAX_AGE = 365 * 24 * 60 * 60

_LOCALES_DIR = Path(__file__).resolve().parent / "locales"


@lru_cache
def _locale_table(lang: str) -> dict[str, str]:
    path = _LOCALES_DIR / f"{lang}.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(raw, dict):
        return {}
    return {str(k): str(v) for k, v in raw.items()}


def normalize_lang(code: str | None) -> str:
    if not code:
        return DEFAULT_LANG
    cleaned = str(code).strip().lower().replace("_", "-")
    if cleaned.startswith("uk"):
        return "uk"
    if cleaned.startswith("en"):
        return "en"
    return DEFAULT_LANG


def get_lang(request: Request) -> str:
    cookie = request.cookies.get(COOKIE_NAME)
    if cookie:
        return normalize_lang(cookie)
    return DEFAULT_LANG


def translate(lang: str, key: str, **kwargs: Any) -> str:
    lang = normalize_lang(lang)
    table = _locale_table(lang)
    fallback = _locale_table(DEFAULT_LANG)
    text = table.get(key) or fallback.get(key) or key
    if not kwargs:
        return text

    class _FormatMap(dict):
        def __missing__(self, name: str) -> str:
            return "{" + name + "}"

    mapping = _FormatMap((k, str(v)) for k, v in kwargs.items())
    try:
        return text.format_map(mapping)
    except ValueError:
        result = text
        for k, v in kwargs.items():
            result = result.replace("{" + k + "}", str(v))
        return result


def render_message(lang: str, message: ErrorMessage) -> str:
    params = dict(message.params)
    reason = params.get("reason")
    if isinstance(reason, str):
        nested = {k: v for k, v in params.items() if k != "reason"}
        params["reason"] = translate(lang, reason, **nested)
    return translate(lang, message.code, **params)


def t_for(request: Request):
    lang = get_lang(request)

    def t(key: str, **kwargs: Any) -> str:
        return translate(lang, key, **kwargs)

    return t


def set_lang_cookie(response: Response, lang: str) -> None:
    response.set_cookie(
        key=COOKIE_NAME,
        value=normalize_lang(lang),
        max_age=COOKIE_MAX_AGE,
        httponly=False,
        samesite="lax",
        path="/",
    )


def _get_safe_redirect_path(path: str, query: str = "") -> str:
    """Rewrite POST-only paths to a page that accepts GET (avoids 405 on lang switch)."""
    bare = path or "/"
    if bare == "/convert" or bare.startswith("/import/"):
        return "/"
    if bare.startswith("/settings/categories/"):
        return "/settings/categories"
    if bare.startswith("/settings/accounts/"):
        return "/settings/accounts"
    if bare.startswith("/settings/history"):
        return "/settings/history"
    if bare.startswith("/jobs/"):
        return "/"
    if query:
        return f"{bare}?{query}"
    return bare


def safe_redirect_url(request: Request, fallback: str = "/") -> str:
    """Prefer Referer if it points at this app; otherwise fallback.

    After form POSTs the browser address bar may still show a POST-only path
    (``/convert``, ``/import/...``). Those are rewritten to a GET-safe page.
    """
    referer = (request.headers.get("referer") or "").strip()
    if not referer:
        return fallback
    parsed = urlparse(referer)
    if not parsed.scheme and not parsed.netloc and parsed.path.startswith("/"):
        return _get_safe_redirect_path(parsed.path, parsed.query)
    host = request.headers.get("host", "")
    if parsed.netloc and host and parsed.netloc.lower() == host.lower():
        return _get_safe_redirect_path(parsed.path or "/", parsed.query)
    return fallback


def render_job_not_found(request: Request) -> str:
    t = t_for(request)
    body = t("err.job_not_found")
    body = body.replace("{link}", "<a href='/'>").replace("{/link}", "</a>")
    return f"<p>{body}</p>"
