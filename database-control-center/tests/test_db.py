from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.db import get_database_type, get_engine, mask_database_url, test_connection


class DatabaseHelpersTests(unittest.TestCase):
    def test_get_engine_caches_per_url(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "cache-test.db"
            url = f"sqlite:///{db_path.as_posix()}"
            first = get_engine(url)
            second = get_engine(url)
            self.assertIs(first, second)

    def test_mask_database_url_hides_password(self) -> None:
        url = "postgresql+psycopg2://alice:secret@localhost:5432/appdb"
        self.assertEqual(
            mask_database_url(url),
            "postgresql+psycopg2://alice:********@localhost:5432/appdb",
        )

    def test_mask_database_url_hides_odbc_password(self) -> None:
        url = (
            "mssql+pyodbc:///?odbc_connect="
            "DRIVER%3D%7BODBC+Driver+18+for+SQL+Server%7D%3B"
            "SERVER%3DSERVER%5CMSSQLSERVER2017%2C1435%3B"
            "DATABASE%3Dorder_20231025%3B"
            "UID%3Dsa%3B"
            "PWD%3DTcomm7447%3B"
            "Encrypt%3DMandatory%3B"
            "TrustServerCertificate%3Dyes%3B"
        )
        masked = mask_database_url(url)
        self.assertNotIn("Tcomm7447", masked)
        self.assertIn("PWD%3D%2A%2A%2A%2A%2A%2A%2A%2A", masked)

    def test_get_database_type_reports_sqlite(self) -> None:
        self.assertEqual(get_database_type("sqlite:///data/app.db"), "SQLite")

    def test_get_database_type_reports_sql_server(self) -> None:
        self.assertEqual(get_database_type("mssql+pyodbc:///?odbc_connect=test"), "SQL Server")

    def test_test_connection_succeeds_for_sqlite(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "ok.db"
            success, message = test_connection(f"sqlite:///{db_path.as_posix()}")
            self.assertTrue(success)
            self.assertIn("successful", message.lower())


if __name__ == "__main__":
    unittest.main()
