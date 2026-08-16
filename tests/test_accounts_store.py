"""Unit tests for AccountsStore (primary flag, merge, JSON round-trip)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app.services.accounts_store import AccountsStore, StoredAccount


class AccountsStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.data_dir = Path(self._tmp.name)
        self.store = AccountsStore(self.data_dir)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_set_primary_exclusive(self) -> None:
        self.store.add_manual("Cash")
        self.store.add_manual("Card")
        self.store.set_primary("Cash")
        accounts = self.store.list()
        by_name = {a.name: a for a in accounts}
        self.assertTrue(by_name["Cash"].primary)
        self.assertFalse(by_name["Card"].primary)

        self.store.set_primary("Card")
        accounts = self.store.list()
        by_name = {a.name: a for a in accounts}
        self.assertFalse(by_name["Cash"].primary)
        self.assertTrue(by_name["Card"].primary)
        self.assertEqual(sum(1 for a in accounts if a.primary), 1)

    def test_set_primary_toggle_off(self) -> None:
        self.store.add_manual("Cash")
        self.store.set_primary("Cash")
        self.assertTrue(self.store.list()[0].primary)
        self.store.set_primary("Cash")
        self.assertFalse(self.store.list()[0].primary)

    def test_set_primary_unknown_name_noop(self) -> None:
        self.store.add_manual("Cash")
        self.store.set_primary("Cash")
        before = self.store.list()
        after = self.store.set_primary("Missing")
        self.assertEqual(after, before)
        self.assertTrue(after[0].primary)

    def test_set_primary_empty_name_noop(self) -> None:
        self.store.add_manual("Cash")
        self.store.set_primary("Cash")
        after = self.store.set_primary("  ")
        self.assertTrue(after[0].primary)

    def test_merge_from_api_preserves_primary(self) -> None:
        self.store.add_manual("Cash")
        self.store.set_primary("Cash")
        merged = self.store.merge_from_api(
            [("Cash", "uuid-cash"), ("API Card", "uuid-card")]
        )
        by_name = {a.name: a for a in merged}
        self.assertTrue(by_name["Cash"].primary)
        self.assertEqual(by_name["Cash"].id, "uuid-cash")
        self.assertEqual(by_name["Cash"].source, "api")
        self.assertFalse(by_name["API Card"].primary)

    def test_add_manual_preserves_existing_primary(self) -> None:
        self.store.add_manual("Cash")
        self.store.set_primary("Cash")
        self.store.add_manual("Wallet")
        accounts = self.store.list()
        by_name = {a.name: a for a in accounts}
        self.assertTrue(by_name["Cash"].primary)
        self.assertFalse(by_name["Wallet"].primary)
        self.assertEqual(by_name["Wallet"].source, "manual")

    def test_add_manual_duplicate_casefold_noop(self) -> None:
        self.store.add_manual("Cash")
        self.store.set_primary("Cash")
        again = self.store.add_manual("cash")
        self.assertEqual(len(again), 1)
        self.assertTrue(again[0].primary)

    def test_json_roundtrip_with_primary(self) -> None:
        self.store.add_manual("Cash")
        self.store.merge_from_api([("API Card", "id-1")])
        self.store.set_primary("API Card")

        reloaded = AccountsStore(self.data_dir).list()
        by_name = {a.name: a for a in reloaded}
        self.assertTrue(by_name["API Card"].primary)
        self.assertEqual(by_name["API Card"].id, "id-1")
        self.assertFalse(by_name["Cash"].primary)

        raw = json.loads(self.store.path.read_text(encoding="utf-8"))
        primary_items = [item for item in raw if item.get("primary")]
        self.assertEqual(len(primary_items), 1)
        self.assertEqual(primary_items[0]["name"], "API Card")
        non_primary = next(item for item in raw if item["name"] == "Cash")
        self.assertNotIn("primary", non_primary)

    def test_json_roundtrip_without_primary(self) -> None:
        self.store.add_manual("Cash")
        self.store.add_manual("Card")
        reloaded = AccountsStore(self.data_dir).list()
        self.assertTrue(all(not a.primary for a in reloaded))
        raw = json.loads(self.store.path.read_text(encoding="utf-8"))
        self.assertTrue(all("primary" not in item for item in raw))

    def test_reads_legacy_string_entries(self) -> None:
        self.store.path.write_text(
            json.dumps(["Legacy Cash", {"name": "Modern", "id": "x", "source": "api"}]),
            encoding="utf-8",
        )
        accounts = self.store.list()
        by_name = {a.name: a for a in accounts}
        self.assertEqual(by_name["Legacy Cash"], StoredAccount("Legacy Cash", None, "manual", False))
        self.assertEqual(by_name["Modern"].id, "x")
        self.assertEqual(by_name["Modern"].source, "api")

    def test_merge_keeps_manual_not_in_api(self) -> None:
        self.store.add_manual("Only Manual")
        self.store.merge_from_api([("From API", "api-1")])
        names = self.store.names()
        self.assertIn("Only Manual", names)
        self.assertIn("From API", names)


if __name__ == "__main__":
    unittest.main()
