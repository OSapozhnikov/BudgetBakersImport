"""Tests for preview dedup marking, category patch, history route, account select."""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
from app.errors import AppError
from app.main import create_app
from app.services.accounts_store import StoredAccount
from app.services.csv_export import ConversionResult, ExportRow
from app.services.fingerprints import FingerprintStore, fingerprint_row
from app.services.records import BudgetBakersRecordsClient, RecordImportResult
from app.settings import Settings
from app.use_cases.convert import mark_duplicates, select_account
from fastapi.testclient import TestClient


def _row(
    *,
    amount: str = "-10.00",
    note: str = "Coffee",
    counter_party: str = "",
    category: str = "Food",
    day: date | None = None,
) -> ExportRow:
    return ExportRow(
        date=day or date(2026, 6, 15),
        account="Cash",
        category=category,
        amount=Decimal(amount),
        note=note,
        currency="UAH",
        bank_category=category,
        original_amount=Decimal(amount),
        original_currency="UAH",
        mapped=True,
        fx_converted=False,
        counter_party=counter_party,
    )


class SelectAccountTests(unittest.TestCase):
    def test_priority_preferred_last_primary_default_first(self) -> None:
        accounts = [
            StoredAccount(name="A", primary=False),
            StoredAccount(name="B", primary=True),
            StoredAccount(name="Account", primary=False),
            StoredAccount(name="Last", primary=False),
        ]
        settings = Settings(default_account_name="Account")
        self.assertEqual(
            select_account(accounts, settings, preferred="A"),
            "A",
        )
        self.assertEqual(
            select_account(
                accounts, settings, preferred=None, last_account_name="Last"
            ),
            "Last",
        )
        self.assertEqual(
            select_account(accounts, settings, preferred=None, last_account_name=None),
            "B",
        )
        no_primary = [StoredAccount(name="X"), StoredAccount(name="Account")]
        self.assertEqual(select_account(no_primary, settings), "Account")
        self.assertEqual(
            select_account([StoredAccount(name="Only")], settings),
            "Only",
        )


class MarkDuplicatesTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.store = FingerprintStore(self._tmp.name)
        self.settings = Settings(
            data_dir=self._tmp.name,
            budgetbakers_api_token="",
        )

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_local_hit_marks_duplicate(self) -> None:
        row = _row()
        fp = fingerprint_row(row, "acc-1")
        self.store.add_many([fp])
        warn = mark_duplicates(
            [row],
            account_id="acc-1",
            fingerprint_store=self.store,
            settings=self.settings,
            lang="en",
        )
        self.assertEqual(warn, [])
        self.assertTrue(row.is_duplicate)

    def test_no_account_id_clears_flag(self) -> None:
        row = _row()
        row.is_duplicate = True
        mark_duplicates(
            [row],
            account_id=None,
            fingerprint_store=self.store,
            settings=self.settings,
            lang="en",
        )
        self.assertFalse(row.is_duplicate)

    def test_api_match_hybrid(self) -> None:
        row = _row(note="Match Me", counter_party="Shop")
        settings = Settings(
            data_dir=self._tmp.name,
            budgetbakers_api_token="tok",
            budgetbakers_api_base="https://example.test/wallet/v1/api",
        )
        api_items = [
            {
                "accountId": "acc-1",
                "recordDate": "2026-06-15T12:00:00Z",
                "amount": {"value": -10.0, "currencyCode": "UAH"},
                "note": "Match Me",
                "counterParty": "Shop",
            }
        ]

        with patch("app.use_cases.convert.BudgetBakersRecordsClient") as client_cls:
            client = MagicMock()
            client.__enter__.return_value = client
            client.__exit__.return_value = None
            client.list_records.return_value = api_items
            client_cls.return_value = client
            warn = mark_duplicates(
                [row],
                account_id="acc-1",
                fingerprint_store=self.store,
                settings=settings,
                lang="en",
            )

        self.assertEqual(warn, [])
        self.assertTrue(row.is_duplicate)
        client.list_records.assert_called_once()

    def test_api_failure_non_fatal(self) -> None:
        row = _row()
        settings = Settings(
            data_dir=self._tmp.name,
            budgetbakers_api_token="tok",
        )
        with patch("app.use_cases.convert.BudgetBakersRecordsClient") as client_cls:
            client = MagicMock()
            client.__enter__.return_value = client
            client.__exit__.return_value = None
            client.list_records.side_effect = RuntimeError("boom")
            client_cls.return_value = client
            warn = mark_duplicates(
                [row],
                account_id="acc-1",
                fingerprint_store=self.store,
                settings=settings,
                lang="en",
            )
        self.assertEqual(len(warn), 1)
        self.assertEqual(warn[0].code, "preview.dedup_api_warn")
        self.assertFalse(row.is_duplicate)

    def test_within_file_fingerprint_collision(self) -> None:
        rows = [_row(note="same"), _row(note="same")]
        warn = mark_duplicates(
            rows,
            account_id="acc-1",
            fingerprint_store=self.store,
            settings=self.settings,
            lang="en",
        )
        self.assertTrue(all(r.fp_collision for r in rows))
        self.assertTrue(any(w.code == "preview.fp_collision_warn" for w in warn))


class ListRecordsClientTests(unittest.TestCase):
    def test_list_records_paginated(self) -> None:
        calls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(str(request.url))
            offset = int(request.url.params.get("offset", "0"))
            if offset == 0:
                return httpx.Response(
                    200,
                    json={
                        "items": [
                            {
                                "id": "1",
                                "accountId": "acc-1",
                                "recordDate": "2026-06-01T12:00:00Z",
                                "amount": {"value": -1, "currencyCode": "UAH"},
                            }
                        ]
                    },
                )
            return httpx.Response(200, json={"items": []})

        client = BudgetBakersRecordsClient(
            base_url="https://example.test/wallet/v1/api",
            token="tok",
            client=httpx.Client(transport=httpx.MockTransport(handler)),
        )
        with client:
            items = client.list_records(
                account_id="acc-1",
                date_from=date(2026, 6, 1),
                date_to=date(2026, 6, 30),
                page_size=1,
            )
        self.assertEqual(len(items), 1)
        self.assertGreaterEqual(len(calls), 1)
        self.assertIn("accountId=acc-1", calls[0])

    def test_list_records_hits_page_ceiling(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            offset = int(request.url.params.get("offset", "0"))
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": str(offset),
                            "accountId": "acc-1",
                            "recordDate": "2026-06-01T12:00:00Z",
                            "amount": {"value": -1, "currencyCode": "UAH"},
                        }
                    ],
                    "nextOffset": offset + 1,
                },
            )

        client = BudgetBakersRecordsClient(
            base_url="https://example.test/wallet/v1/api",
            token="tok",
            client=httpx.Client(transport=httpx.MockTransport(handler)),
            max_pages=2,
            max_items=10_000,
        )
        with client:
            with self.assertRaises(AppError) as ctx:
                client.list_records(
                    account_id="acc-1",
                    date_from=date(2026, 6, 1),
                    date_to=date(2026, 6, 30),
                    page_size=1,
                )
        self.assertEqual(ctx.exception.code, "wallet.pagination_limit")


class PreviewUxRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        settings = Settings(
            data_dir=self._tmp.name,
            budgetbakers_api_token="tok",
            default_account_name="Cash",
        )
        self.app = create_app(settings)
        self.client = TestClient(self.app)
        self.app.state.accounts_store.add_manual("Cash")
        path = Path(self._tmp.name) / "accounts.json"
        path.write_text(
            json.dumps(
                [{"name": "Cash", "id": "acc-cash", "source": "manual", "primary": True}]
            )
            + "\n",
            encoding="utf-8",
        )
        cache = Path(self._tmp.name) / "bb_categories_cache.json"
        cache.write_text(
            json.dumps([{"id": "c1", "name": "Food", "parentName": "Living"}]) + "\n",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.client.close()
        self._tmp.cleanup()

    def _put_job(self) -> str:
        result = ConversionResult(rows=[_row(category="BankCat")])
        result.rows[0].mapped = False
        result.rows[0].unmapped = True
        job_id = self.app.state.jobs.put(result, "Cash", "stmt.xlsx", account_id="acc-cash")
        return job_id

    def test_history_page_smoke(self) -> None:
        resp = self.client.get("/settings/history")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("text/html", resp.headers.get("content-type", ""))

    def test_patch_category_job_only(self) -> None:
        job_id = self._put_job()
        mapping_path = Path(self._tmp.name) / "category_mappings.json"
        before = mapping_path.read_text(encoding="utf-8") if mapping_path.exists() else ""

        resp = self.client.post(
            f"/jobs/{job_id}/rows/0/category",
            data={"category": "Food"},
        )
        self.assertEqual(resp.status_code, 204)

        job = self.app.state.jobs.get(job_id)
        assert job is not None
        row: ExportRow = job.result.rows[0]
        self.assertEqual(row.category, "Food")
        self.assertTrue(row.mapped)
        self.assertFalse(row.unmapped)

        after = mapping_path.read_text(encoding="utf-8") if mapping_path.exists() else ""
        self.assertEqual(before, after)

    def test_nav_includes_history(self) -> None:
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("/settings/history", resp.text)

    def test_import_retry_remaining_rows(self) -> None:
        result = ConversionResult(
            rows=[
                _row(note="first", amount="-1.00"),
                _row(note="second", amount="-2.00"),
            ]
        )
        job_id = self.app.state.jobs.put(
            result, "Cash", "stmt.xlsx", account_id="acc-cash"
        )
        first = RecordImportResult(succeeded=1, failed=1, succeeded_indices=[0])
        second = RecordImportResult(succeeded=1, failed=0, succeeded_indices=[0])

        with patch("app.use_cases.import_records.BudgetBakersRecordsClient") as client_cls:
            client = MagicMock()
            client.__enter__.return_value = client
            client.__exit__.return_value = None
            client.import_rows.side_effect = [first, second]
            client_cls.return_value = client

            resp = self.client.post(f"/import/{job_id}", data={"row": ["0", "1"]})
            self.assertEqual(resp.status_code, 200)
            job = self.app.state.jobs.get(job_id)
            assert job is not None
            self.assertEqual(job.imported_indices, {0})
            self.assertFalse(job.imported)

            resp2 = self.client.post(f"/import/{job_id}", data={"row": ["1"]})
            self.assertEqual(resp2.status_code, 200)
            self.assertEqual(job.imported_indices, {0, 1})
            self.assertTrue(job.imported)

        self.assertEqual(client.import_rows.call_count, 2)


if __name__ == "__main__":
    unittest.main()
