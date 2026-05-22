from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.config import DEFAULT_SQLITE_URL
from src.connection_manager import (
    build_manual_database_url,
    default_db_profile,
    load_db_profiles,
    set_active_database_profile,
)


class ConnectionManagerTests(unittest.TestCase):
    def test_load_db_profiles_falls_back_to_default_profile(self) -> None:
        profiles = load_db_profiles("")
        self.assertEqual(len(profiles), 1)
        self.assertEqual(profiles[0]["name"], "Local Demo SQLite")
        self.assertEqual(profiles[0]["url"], DEFAULT_SQLITE_URL)

    def test_load_db_profiles_parses_env_json(self) -> None:
        raw = """
        [
          {"name": "Demo", "type": "sqlite", "url": "sqlite:///data/app.db", "description": "demo"},
          {"name": "Postgres", "type": "postgresql", "url": "postgresql+psycopg2://u:p@localhost:5432/db", "description": "pg"}
        ]
        """
        profiles = load_db_profiles(raw)
        self.assertEqual(len(profiles), 2)
        self.assertEqual(profiles[1]["type"], "postgresql")

    def test_load_db_profiles_parses_quoted_json_string(self) -> None:
        raw = "\"[{\\\"name\\\":\\\"Demo\\\",\\\"type\\\":\\\"sqlite\\\",\\\"url\\\":\\\"sqlite:///data/app.db\\\",\\\"description\\\":\\\"demo\\\"}]\""
        profiles = load_db_profiles(raw)
        self.assertEqual(len(profiles), 1)
        self.assertEqual(profiles[0]["name"], "Demo")

    def test_build_manual_database_url_for_sqlite(self) -> None:
        url = build_manual_database_url(
            "SQLite",
            {
                "sqlite_path": "data/app.db",
            },
        )
        self.assertEqual(url, "sqlite:///data/app.db")

    def test_build_manual_database_url_for_postgresql(self) -> None:
        url = build_manual_database_url(
            "PostgreSQL",
            {
                "host": "localhost",
                "port": "5432",
                "database_name": "mydb",
                "username": "alice",
                "password": "secret",
                "ssl_mode": "require",
            },
        )
        self.assertEqual(
            url,
            "postgresql+psycopg2://alice:secret@localhost:5432/mydb?sslmode=require",
        )

    def test_build_manual_database_url_for_sql_server(self) -> None:
        url = build_manual_database_url(
            "SQL Server",
            {
                "server": r"SERVER\MSSQLSERVER2017,1435",
                "database_name": "order_20231025",
                "username": "sa",
                "password": "",
                "encrypt": "yes",
                "trust_server_certificate": True,
                "connect_timeout": "30",
                "application_name": "vscode-mssql",
                "driver": "ODBC Driver 18 for SQL Server",
            },
        )
        self.assertIn("mssql+pyodbc:///?odbc_connect=", url)
        self.assertIn("SERVER%3DSERVER%5CMSSQLSERVER2017%2C1435", url)
        self.assertIn("DATABASE%3Dorder_20231025", url)
        self.assertIn("UID%3Dsa", url)

    def test_set_active_database_profile_updates_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "active.db"
            state: dict[str, object] = {}
            profile = {
                "name": "Temp SQLite",
                "type": "sqlite",
                "url": f"sqlite:///{db_path.as_posix()}",
                "description": "temporary",
            }
            set_active_database_profile(state, profile)
            self.assertEqual(state["active_database_name"], "Temp SQLite")
            self.assertEqual(state["active_database_url"], profile["url"])
            self.assertIsNotNone(state["active_engine"])


if __name__ == "__main__":
    unittest.main()
