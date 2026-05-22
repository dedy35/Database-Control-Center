from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import MetaData, inspect

from src.audit_service import audit_log_exists, create_audit_log_table, fetch_audit_logs
from src.crud_service import insert_record, soft_delete_record, update_record
from src.db import get_engine
from src.demo_seed import define_demo_tables, seed_demo_database


class CrudAuditTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        db_path = Path(self.temp_dir.name) / "crud-audit.db"
        self.engine = get_engine(f"sqlite:///{db_path.as_posix()}")
        seed_demo_database(self.engine)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_insert_record_writes_audit_log(self) -> None:
        record_id = insert_record(
            self.engine,
            "customers",
            {
                "name": "Test Customer",
                "email": "test@example.com",
                "city": "Jakarta",
                "status": "active",
            },
            actor="tester",
        )
        logs = fetch_audit_logs(self.engine, table_name="customers", action="INSERT")
        self.assertTrue(any(str(record_id) == str(item["record_id"]) for item in logs))

    def test_update_and_soft_delete_write_audit_log(self) -> None:
        update_record(
            self.engine,
            "customers",
            record_id=1,
            data={"city": "Bandung"},
            actor="tester",
        )
        soft_delete_record(
            self.engine,
            "customers",
            record_id=1,
            actor="tester",
        )
        logs = fetch_audit_logs(self.engine, table_name="customers")
        actions = [item["action"] for item in logs]
        self.assertIn("UPDATE", actions)
        self.assertIn("SOFT_DELETE", actions)

    def test_insert_requires_existing_audit_log_table(self) -> None:
        isolated_dir = tempfile.TemporaryDirectory()
        try:
            db_path = Path(isolated_dir.name) / "no-audit.db"
            engine = get_engine(f"sqlite:///{db_path.as_posix()}")
            metadata = MetaData()
            tables = define_demo_tables(metadata)
            metadata.create_all(engine, tables=[tables["customers"], tables["orders"]])

            with self.assertRaises(RuntimeError):
                insert_record(
                    engine,
                    "customers",
                    {
                        "name": "No Audit",
                        "email": "no-audit@example.com",
                        "city": "Jakarta",
                        "status": "active",
                    },
                    actor="tester",
                )
        finally:
            isolated_dir.cleanup()

    def test_create_audit_log_table_is_explicit(self) -> None:
        isolated_dir = tempfile.TemporaryDirectory()
        try:
            db_path = Path(isolated_dir.name) / "manual-audit.db"
            engine = get_engine(f"sqlite:///{db_path.as_posix()}")
            metadata = MetaData()
            tables = define_demo_tables(metadata)
            metadata.create_all(engine, tables=[tables["customers"], tables["orders"]])
            self.assertNotIn("audit_log", inspect(engine).get_table_names())

            create_audit_log_table(engine)

            self.assertIn("audit_log", inspect(engine).get_table_names())
        finally:
            isolated_dir.cleanup()

    def test_audit_log_exists_returns_false_when_inspection_fails(self) -> None:
        with patch("src.audit_service.inspect", side_effect=RuntimeError("connect failed")):
            self.assertFalse(audit_log_exists(object()))


if __name__ == "__main__":
    unittest.main()
