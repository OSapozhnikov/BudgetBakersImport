"""FastAPI TestClient smoke tests (no external APIs)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app
from app.settings import Settings
from app.version import __version__


class AppSmokeTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        settings = Settings(
            data_dir=self._tmp.name,
            budgetbakers_api_token="",
            default_account_name="Account",
        )
        self.app = create_app(settings)
        self.client = TestClient(self.app)

    def tearDown(self) -> None:
        self.client.close()
        self._tmp.cleanup()

    def test_healthz(self) -> None:
        resp = self.client.get("/healthz")
        self.assertEqual(resp.status_code, 200)
        payload = resp.json()
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["data_dir"], "ok")

    def test_lang_en_sets_cookie(self) -> None:
        resp = self.client.get("/lang/en", follow_redirects=False)
        self.assertEqual(resp.status_code, 303)
        self.assertIn("bbi_lang=en", resp.headers.get("set-cookie", ""))

    def test_lang_switch_from_convert_referer_goes_home(self) -> None:
        resp = self.client.get(
            "/lang/en",
            headers={"Referer": "http://testserver/convert"},
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 303)
        self.assertEqual(resp.headers.get("location"), "/")

    def test_index_200(self) -> None:
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("text/html", resp.headers.get("content-type", ""))
        self.assertIn(f"Version {__version__}", resp.text)
        self.assertIn(f"/static/style.css?v={__version__}", resp.text)

    def test_accounts_primary_with_temp_data_dir(self) -> None:
        add = self.client.post(
            "/settings/accounts/add",
            data={"name": "Primary Cash"},
            follow_redirects=False,
        )
        self.assertEqual(add.status_code, 200)

        resp = self.client.post(
            "/settings/accounts/primary",
            data={"name": "Primary Cash"},
        )
        self.assertEqual(resp.status_code, 200)

        store = self.app.state.accounts_store
        accounts = store.list()
        self.assertEqual(len(accounts), 1)
        self.assertTrue(accounts[0].primary)

        path = Path(self._tmp.name) / "accounts.json"
        self.assertTrue(path.exists())
        self.assertIn("Primary Cash", path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
