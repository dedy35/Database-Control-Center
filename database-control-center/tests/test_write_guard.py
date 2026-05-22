from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from sqlalchemy import MetaData, Table, func, select

from src.db import get_engine
from src.demo_seed import seed_demo_database
from src.write_guard import WriteActionPlan, create_confirmation_token, execute_approved_write


class WriteGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        db_path = Path(self.temp_dir.name) / "guard.db"
        self.url = f"sqlite:///{db_path.as_posix()}"
        self.engine = get_engine(self.url)
        seed_demo_database(self.engine)

    def _customer_count(self) -> int:
        customers = Table("customers", MetaData(), autoload_with=self.engine)
        with self.engine.connect() as connection:
            return int(connection.execute(select(func.count()).select_from(customers)).scalar_one())

    def test_write_without_confirmation_token_is_blocked(self) -> None:
        plan = WriteActionPlan(
            action="insert",
            table="customers",
            database_name="Test DB",
            database_type="SQLite",
            actor="tester",
            reason="Unit test insert",
            risk_level="medium",
            payload={"name": "Test User", "email": "test@example.com", "city": "Tokyo", "status": "active"},
            after_data={"name": "Test User"},
        )
        with self.assertRaises(PermissionError):
            execute_approved_write(plan, None, self.engine)

    def test_valid_token_allows_single_write(self) -> None:
        before_count = self._customer_count()
        plan = WriteActionPlan(
            action="insert",
            table="customers",
            database_name="Test DB",
            database_type="SQLite",
            actor="tester",
            reason="Unit test insert",
            risk_level="medium",
            payload={"name": "Test User", "email": "test@example.com", "city": "Tokyo", "status": "active"},
            after_data={"name": "Test User"},
        )
        token = create_confirmation_token(plan)
        record_id = execute_approved_write(plan, token, self.engine)
        after_count = self._customer_count()
        self.assertIsNotNone(record_id)
        self.assertEqual(after_count, before_count + 1)

    def test_token_is_single_use(self) -> None:
        plan = WriteActionPlan(
            action="insert",
            table="customers",
            database_name="Test DB",
            database_type="SQLite",
            actor="tester",
            reason="Unit test insert",
            risk_level="medium",
            payload={"name": "Test User", "email": "test@example.com", "city": "Tokyo", "status": "active"},
            after_data={"name": "Test User"},
        )
        token = create_confirmation_token(plan)
        execute_approved_write(plan, token, self.engine)
        with self.assertRaises(PermissionError):
            execute_approved_write(plan, token, self.engine)

    def test_cancelled_write_does_not_execute(self) -> None:
        before_count = self._customer_count()
        plan = WriteActionPlan(
            action="insert",
            table="customers",
            database_name="Test DB",
            database_type="SQLite",
            actor="tester",
            reason="Unit test insert",
            risk_level="medium",
            payload={"name": "Test User", "email": "test@example.com", "city": "Tokyo", "status": "active"},
            after_data={"name": "Test User"},
        )
        with self.assertRaises(PermissionError):
            execute_approved_write(plan, "cancelled-token", self.engine)
        self.assertEqual(self._customer_count(), before_count)


if __name__ == "__main__":
    unittest.main()
