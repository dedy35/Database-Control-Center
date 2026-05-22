from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.db import get_engine
from src.demo_seed import seed_demo_database
from src.query_builder import build_select_statement, fetch_dataframe


class QueryBuilderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        db_path = Path(self.temp_dir.name) / "query-builder.db"
        self.engine = get_engine(f"sqlite:///{db_path.as_posix()}")
        seed_demo_database(self.engine)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_keyword_search_matches_text_columns(self) -> None:
        statement, _ = build_select_statement(
            self.engine,
            "customers",
            keyword="Makassar",
            limit=50,
        )
        frame = fetch_dataframe(self.engine, statement)
        self.assertFalse(frame.empty)
        self.assertTrue((frame["city"] == "Makassar").any())

    def test_deleted_rows_are_hidden_by_default(self) -> None:
        statement, _ = build_select_statement(
            self.engine,
            "customers",
            filters=[{"column": "deleted_at", "operator": "is_not_null"}],
            limit=50,
        )
        frame = fetch_dataframe(self.engine, statement)
        self.assertTrue(frame.empty)

    def test_explicit_include_deleted_shows_soft_deleted_rows(self) -> None:
        statement, _ = build_select_statement(
            self.engine,
            "customers",
            filters=[{"column": "deleted_at", "operator": "is_not_null"}],
            include_soft_deleted=True,
            limit=50,
        )
        frame = fetch_dataframe(self.engine, statement)
        self.assertFalse(frame.empty)


if __name__ == "__main__":
    unittest.main()
