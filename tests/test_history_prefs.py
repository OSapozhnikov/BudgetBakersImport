"""Unit tests for import history and prefs stores."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.services.import_history import ImportHistoryStore
from app.services.prefs_store import PrefsStore


class ImportHistoryStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.store = ImportHistoryStore(self._tmp.name, cap=3)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_append_newest_first_and_cap(self) -> None:
        for i in range(5):
            self.store.append(
                filename=f"f{i}.xlsx",
                account_name="Cash",
                account_id="acc-1",
                requested=i + 1,
                succeeded=i,
                failed=0,
                skipped_zero=0,
                job_id=f"job-{i}",
            )
        entries = self.store.list()
        self.assertEqual(len(entries), 3)
        self.assertEqual(entries[0].filename, "f4.xlsx")
        self.assertEqual(entries[-1].filename, "f2.xlsx")
        path = Path(self._tmp.name) / "import_history.json"
        self.assertTrue(path.exists())


class PrefsStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.store = PrefsStore(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_last_account_round_trip(self) -> None:
        self.assertIsNone(self.store.get_last_account_name())
        self.store.set_last_account_name("  My Cash  ")
        self.assertEqual(self.store.get_last_account_name(), "My Cash")
        path = Path(self._tmp.name) / "prefs.json"
        self.assertTrue(path.exists())
        self.assertIn("My Cash", path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
