"""Unit tests for BudgetBakers records client and payload builders."""

from __future__ import annotations

import json
import unittest
from datetime import date
from decimal import Decimal

import httpx

from app.services.csv_export import ExportRow
from app.services.records import (
    BudgetBakersRecordsClient,
    build_record_payload,
    category_ids_by_name,
)


def _row(
    *,
    amount: str = "10.00",
    note: str = "Coffee",
    category: str = "Food",
    currency: str = "UAH",
    counter_party: str = "",
    day: date | None = None,
) -> ExportRow:
    return ExportRow(
        date=day or date(2026, 6, 15),
        account="Cash",
        category=category,
        amount=Decimal(amount),
        note=note,
        currency=currency,
        bank_category=category,
        original_amount=Decimal(amount),
        original_currency=currency,
        mapped=True,
        fx_converted=False,
        counter_party=counter_party,
    )


class BuildRecordPayloadTests(unittest.TestCase):
    def test_amount_and_noon_utc_date(self) -> None:
        payload = build_record_payload(_row(amount="-12.345"), account_id="acc-1")
        assert payload is not None
        self.assertEqual(payload["accountId"], "acc-1")
        self.assertEqual(payload["amount"], {"value": -12.35, "currencyCode": "UAH"})
        self.assertEqual(payload["recordDate"], "2026-06-15T12:00:00Z")
        self.assertEqual(payload["recordState"], "cleared")
        self.assertEqual(payload["note"], "Coffee")
        self.assertNotIn("categoryId", payload)
        self.assertNotIn("counterParty", payload)

    def test_note_truncated_255(self) -> None:
        long_note = "N" * 300
        payload = build_record_payload(_row(note=long_note), account_id="acc-1")
        assert payload is not None
        self.assertEqual(len(payload["note"]), 255)

    def test_counter_party_when_set(self) -> None:
        long_cp = "C" * 300
        payload = build_record_payload(
            _row(counter_party=f"  {long_cp}  "),
            account_id="acc-1",
        )
        assert payload is not None
        self.assertEqual(payload["counterParty"], "C" * 255)

    def test_skip_zero_amount(self) -> None:
        self.assertIsNone(build_record_payload(_row(amount="0"), account_id="acc-1"))
        self.assertIsNone(build_record_payload(_row(amount="0.004"), account_id="acc-1"))

    def test_category_id_optional(self) -> None:
        with_cat = build_record_payload(
            _row(),
            account_id="acc-1",
            category_id="cat-uuid",
        )
        assert with_cat is not None
        self.assertEqual(with_cat["categoryId"], "cat-uuid")

        without = build_record_payload(_row(), account_id="acc-1", category_id=None)
        assert without is not None
        self.assertNotIn("categoryId", without)

    def test_default_currency_uah(self) -> None:
        payload = build_record_payload(_row(currency="  "), account_id="acc-1")
        assert payload is not None
        self.assertEqual(payload["amount"]["currencyCode"], "UAH")


class CategoryIdsByNameTests(unittest.TestCase):
    def test_casefold_first_wins(self) -> None:
        mapping = category_ids_by_name(
            [
                {"name": "Food", "id": "id-1"},
                {"name": "food", "id": "id-2"},
                {"name": "  ", "id": "skip"},
                {"name": "Travel", "id": ""},
                {"name": "Travel", "id": "id-3"},
            ]
        )
        self.assertEqual(mapping, {"food": "id-1", "travel": "id-3"})


class ImportRowsTests(unittest.TestCase):
    def _client(
        self,
        handler: httpx.MockTransport | httpx.Client,
        *,
        batch_size: int = 20,
    ) -> BudgetBakersRecordsClient:
        if isinstance(handler, httpx.MockTransport):
            http_client = httpx.Client(transport=handler)
        else:
            http_client = handler
        return BudgetBakersRecordsClient(
            base_url="https://example.test/wallet/v1/api",
            token="test-token",
            client=http_client,
            batch_size=batch_size,
        )

    def test_batches_21_rows_into_two_posts(self) -> None:
        posts: list[list[dict]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.method, "POST")
            self.assertTrue(str(request.url).endswith("/records"))
            self.assertEqual(
                request.headers.get("Authorization"),
                "Bearer test-token",
            )
            body = json.loads(request.content.decode())
            posts.append(body)
            return httpx.Response(200, json=[])

        rows = [_row(amount=str(i + 1), note=f"n{i}") for i in range(21)]
        with self._client(httpx.MockTransport(handler)) as client:
            result = client.import_rows(rows, account_id="acc-1")

        self.assertEqual(len(posts), 2)
        self.assertEqual(len(posts[0]), 20)
        self.assertEqual(len(posts[1]), 1)
        self.assertEqual(result.succeeded, 21)
        self.assertEqual(result.failed, 0)
        self.assertFalse(result.aborted)
        self.assertEqual(len(result.succeeded_indices), 21)

    def test_http_200_all_success(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=[])

        rows = [_row(amount="5"), _row(amount="0"), _row(amount="7")]
        with self._client(httpx.MockTransport(handler)) as client:
            result = client.import_rows(
                rows,
                account_id="acc-1",
                category_ids={"food": "cat-food"},
            )

        self.assertEqual(result.succeeded, 2)
        self.assertEqual(result.skipped_zero, 1)
        self.assertEqual(result.failed, 0)
        self.assertEqual(result.posted, 2)

    def test_http_207_partial(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                207,
                json=[
                    {"inputIndex": 0, "success": True, "id": "r1"},
                    {"inputIndex": 1, "success": False, "error": "duplicate"},
                ],
            )

        rows = [_row(note="ok"), _row(note="bad")]
        with self._client(httpx.MockTransport(handler)) as client:
            result = client.import_rows(rows, account_id="acc-1")

        self.assertEqual(result.succeeded, 1)
        self.assertEqual(result.failed, 1)
        self.assertEqual(result.succeeded_indices, [0])
        self.assertEqual(len(result.errors), 1)
        self.assertEqual(result.errors[0].note, "bad")
        self.assertIn("duplicate", result.errors[0].error)
        self.assertFalse(result.aborted)

    def test_abort_on_401(self) -> None:
        call_count = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            call_count["n"] += 1
            return httpx.Response(401, json={"message": "unauthorized"})

        # 21 non-zero rows → would be 2 batches; second must not be sent.
        rows = [_row(amount=str(i + 1), note=f"n{i}") for i in range(21)]
        with self._client(httpx.MockTransport(handler)) as client:
            result = client.import_rows(rows, account_id="acc-1")

        self.assertEqual(call_count["n"], 1)
        self.assertTrue(result.aborted)
        self.assertEqual(result.failed, 20)
        self.assertEqual(result.not_sent, 1)
        self.assertIsNotNone(result.fatal_error)
        assert result.fatal_error is not None
        self.assertEqual(result.fatal_error, "wallet.unauthorized")

    def test_resolves_category_from_cache(self) -> None:
        captured: list[dict] = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.extend(json.loads(request.content.decode()))
            return httpx.Response(200, json=[])

        with self._client(httpx.MockTransport(handler)) as client:
            client.import_rows(
                [_row(category="Food")],
                account_id="acc-1",
                category_cache=[{"name": "food", "id": "uuid-food"}],
            )

        self.assertEqual(captured[0]["categoryId"], "uuid-food")


if __name__ == "__main__":
    unittest.main()
