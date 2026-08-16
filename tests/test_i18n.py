"""Unit tests for i18n helpers."""

from __future__ import annotations

import unittest

from starlette.requests import Request
from starlette.responses import Response

from app.i18n import (
    COOKIE_NAME,
    DEFAULT_LANG,
    get_lang,
    normalize_lang,
    safe_redirect_url,
    set_lang_cookie,
    translate,
)


class NormalizeLangTests(unittest.TestCase):
    def test_default_and_aliases(self) -> None:
        self.assertEqual(normalize_lang(None), DEFAULT_LANG)
        self.assertEqual(normalize_lang(""), "uk")
        self.assertEqual(normalize_lang("UK"), "uk")
        self.assertEqual(normalize_lang("uk-UA"), "uk")
        self.assertEqual(normalize_lang("en"), "en")
        self.assertEqual(normalize_lang("en_US"), "en")
        self.assertEqual(normalize_lang("de"), "uk")


class TranslateTests(unittest.TestCase):
    def test_t_key_lang_default_uk(self) -> None:
        self.assertEqual(translate("uk", "nav.convert"), "Конвертація")
        self.assertEqual(translate("en", "nav.convert"), "Convert")

    def test_missing_key_fallback(self) -> None:
        self.assertEqual(translate("uk", "does.not.exist"), "does.not.exist")
        self.assertEqual(translate("en", "does.not.exist"), "does.not.exist")

    def test_format_placeholders(self) -> None:
        text = translate("en", "ok.imported", succeeded=3, total=5)
        self.assertEqual(text, "Imported 3 of 5")

    def test_format_with_braces_in_values(self) -> None:
        text = translate("en", "ok.account_added", name="Cash {main}")
        self.assertEqual(text, "Added account “Cash {main}”.")
        text = translate("uk", "err.import_failed", exc="boom {x}")
        self.assertEqual(text, "Помилка імпорту: boom {x}")

    def test_format_fallback_when_template_has_extra_braces(self) -> None:
        # {/link} is not a valid format field; format raises KeyError and
        # fallback must still substitute the provided {link} placeholder.
        text = translate("en", "err.job_not_found", link="<a href='/'>")
        self.assertIn("<a href='/'>", text)
        self.assertNotIn("{link}", text)
        self.assertIn("{/link}", text)

    def test_missing_lang_falls_back_to_uk_entry(self) -> None:
        # Unsupported lang code → entry uses DEFAULT_LANG text.
        text = translate("fr", "nav.convert")
        self.assertEqual(text, "Конвертація")


class CookieAndRedirectTests(unittest.TestCase):
    def _request(
        self,
        *,
        cookies: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Request:
        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/",
            "raw_path": b"/",
            "query_string": b"",
            "headers": [
                (k.lower().encode(), v.encode()) for k, v in (headers or {}).items()
            ],
            "client": ("127.0.0.1", 123),
            "server": ("test", 80),
        }
        request = Request(scope)
        if cookies:
            request._cookies = cookies  # noqa: SLF001 — test helper
        return request

    def test_get_lang_from_cookie(self) -> None:
        self.assertEqual(get_lang(self._request()), "uk")
        self.assertEqual(get_lang(self._request(cookies={COOKIE_NAME: "en"})), "en")

    def test_set_lang_cookie(self) -> None:
        response = Response()
        set_lang_cookie(response, "EN")
        set_cookie = response.headers.get("set-cookie", "")
        self.assertIn(f"{COOKIE_NAME}=en", set_cookie)

    def test_safe_redirect_same_host(self) -> None:
        request = self._request(
            headers={
                "host": "localhost:8000",
                "referer": "http://localhost:8000/settings/accounts",
            }
        )
        self.assertEqual(safe_redirect_url(request), "/settings/accounts")

    def test_safe_redirect_external_falls_back(self) -> None:
        request = self._request(
            headers={
                "host": "localhost:8000",
                "referer": "https://evil.example/phish",
            }
        )
        self.assertEqual(safe_redirect_url(request, "/"), "/")

    def test_safe_redirect_rewrites_post_only_convert(self) -> None:
        request = self._request(
            headers={
                "host": "localhost:8000",
                "referer": "http://localhost:8000/convert",
            }
        )
        self.assertEqual(safe_redirect_url(request), "/")

    def test_safe_redirect_rewrites_post_only_import(self) -> None:
        request = self._request(
            headers={
                "host": "localhost:8000",
                "referer": "http://localhost:8000/import/abc-123",
            }
        )
        self.assertEqual(safe_redirect_url(request), "/")

    def test_safe_redirect_rewrites_accounts_post_actions(self) -> None:
        request = self._request(
            headers={
                "host": "localhost:8000",
                "referer": "http://localhost:8000/settings/accounts/add",
            }
        )
        self.assertEqual(safe_redirect_url(request), "/settings/accounts")


if __name__ == "__main__":
    unittest.main()
