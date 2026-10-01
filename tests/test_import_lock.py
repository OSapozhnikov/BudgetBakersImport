"""Import locking and WEB_CONCURRENCY guard."""

from __future__ import annotations

import tempfile
import threading
import time
import unittest
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

from app.errors import AppError
from app.jobs import JobStore
from app.main import create_app
from app.persistence.category_cache import CategoryCacheStore
from app.persistence.fingerprints import FingerprintStore
from app.persistence.import_history import ImportHistoryStore
from app.services.csv_export import ConversionResult, ExportRow
from app.services.records import RecordImportResult
from app.settings import Settings
from app.use_cases.import_records import import_selected_rows


def _row(*, note: str = "Coffee", amount: str = "-10.00") -> ExportRow:
    return ExportRow(
        date=date(2026, 6, 15),
        account="Cash",
        category="Food",
        amount=Decimal(amount),
        note=note,
        currency="UAH",
        bank_category="Food",
        original_amount=Decimal(amount),
        original_currency="UAH",
        mapped=True,
        fx_converted=False,
    )


class WebConcurrencyGuardTests(unittest.TestCase):
    def test_create_app_rejects_extra_workers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            settings = Settings(data_dir=tmp, web_concurrency=2)
            with self.assertRaises(RuntimeError):
                create_app(settings)


class ImportLockTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.settings = Settings(
            data_dir=self._tmp.name,
            budgetbakers_api_token="tok",
            budgetbakers_api_base="https://example.test/wallet/v1/api",
        )
        self.fingerprints = FingerprintStore(self._tmp.name)
        self.history = ImportHistoryStore(self._tmp.name)
        self.category_cache = CategoryCacheStore(self._tmp.name)
        self.jobs = JobStore()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_parallel_import_posts_each_row_once(self) -> None:
        result = ConversionResult(
            rows=[
                _row(note="first", amount="-1.00"),
                _row(note="second", amount="-2.00"),
            ]
        )
        job_id = self.jobs.put(result, "Cash", "stmt.xlsx", account_id="acc-1")
        job = self.jobs.get(job_id)
        assert job is not None

        entered = threading.Event()
        release = threading.Event()
        posted: list[list[str]] = []
        lock = threading.Lock()
        errors: list[BaseException] = []

        def slow_import(rows, **kwargs):  # noqa: ANN001
            entered.set()
            if not release.wait(timeout=5):
                raise TimeoutError("import release timed out")
            notes = [r.note for r in rows]
            with lock:
                posted.append(notes)
            return RecordImportResult(
                succeeded=len(notes),
                failed=0,
                succeeded_indices=list(range(len(notes))),
            )

        def worker() -> None:
            try:
                with patch(
                    "app.use_cases.import_records.BudgetBakersRecordsClient"
                ) as client_cls:
                    client = MagicMock()
                    client.__enter__.return_value = client
                    client.__exit__.return_value = None
                    client.import_rows.side_effect = slow_import
                    client_cls.return_value = client
                    import_selected_rows(
                        job=job,
                        job_id=job_id,
                        indices=[0, 1],
                        settings=self.settings,
                        fingerprint_store=self.fingerprints,
                        history_store=self.history,
                        category_cache=self.category_cache,
                    )
            except AppError as exc:
                errors.append(exc)
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        self.assertTrue(entered.wait(timeout=5))
        # Second thread should have failed while the first holds in_flight.
        time.sleep(0.1)
        release.set()
        for thread in threads:
            thread.join(timeout=10)

        self.assertEqual(job.imported_indices, {0, 1})
        self.assertEqual(job.in_flight, set())
        self.assertEqual(len(posted), 1)
        self.assertEqual(sorted(posted[0]), ["first", "second"])
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], AppError)
        self.assertEqual(errors[0].code, "err.already_imported")


if __name__ == "__main__":
    unittest.main()
