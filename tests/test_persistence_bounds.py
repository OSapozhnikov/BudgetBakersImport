"""Persistence integrity and upload bound tests."""

from __future__ import annotations

import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

from app.errors import AppError
from app.persistence.fingerprints import FingerprintStore
from app.persistence.json_store import JsonFileStore
from app.services.excel_parser import parse_excel


class JsonStoreIntegrityTests(unittest.TestCase):
    def test_corrupt_json_raises_and_does_not_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "import_fingerprints.json"
            path.write_text("{not-json", encoding="utf-8")
            store = FingerprintStore(tmp)
            with self.assertRaises(AppError) as ctx:
                store.load()
            self.assertEqual(ctx.exception.code, "err.data_corrupt")
            self.assertEqual(path.read_text(encoding="utf-8"), "{not-json")

            with self.assertRaises(AppError):
                store.add_many(["abc"])
            self.assertEqual(path.read_text(encoding="utf-8"), "{not-json")

    def test_atomic_write_keeps_bak(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = JsonFileStore(Path(tmp) / "prefs.json")
            store.dump({"a": 1})
            store.dump({"a": 2})
            bak = Path(tmp) / "prefs.json.bak"
            self.assertTrue(bak.exists())
            self.assertIn('"a": 1', bak.read_text(encoding="utf-8"))


class ExcelBoundsTests(unittest.TestCase):
    def test_zip_bomb_rejected_before_openpyxl(self) -> None:
        buf = BytesIO()
        with ZipFile(buf, "w") as zf:
            zf.writestr("xl/workbook.xml", "x" * 100)
        content = buf.getvalue()
        with self.assertRaises(AppError) as ctx:
            parse_excel(content, max_uncompressed_bytes=10)
        self.assertEqual(ctx.exception.code, "err.excel_too_large")


if __name__ == "__main__":
    unittest.main()
