from __future__ import annotations

import unittest

from src.ai_plan_validator import validate_filter_plan, validate_write_proposal


class AIPlanValidatorTests(unittest.TestCase):
    def test_accepts_valid_filter_plan(self) -> None:
        plan = validate_filter_plan(
            {
                "table": "customers",
                "keyword": "Makassar",
                "filters": [{"column": "status", "operator": "equals", "value": "active"}],
                "sort_by": "created_at",
                "sort_direction": "desc",
                "limit": 100,
            },
            allowed_tables=["customers"],
            allowed_columns=["id", "status", "created_at"],
        )
        self.assertEqual(plan["table"], "customers")

    def test_rejects_unknown_table(self) -> None:
        with self.assertRaises(ValueError):
            validate_filter_plan(
                {
                    "table": "orders",
                    "keyword": "",
                    "filters": [],
                    "sort_by": "id",
                    "sort_direction": "asc",
                    "limit": 100,
                },
                allowed_tables=["customers"],
                allowed_columns=["id"],
            )

    def test_rejects_unknown_column(self) -> None:
        with self.assertRaises(ValueError):
            validate_write_proposal(
                {
                    "action": "update",
                    "table": "customers",
                    "primary_key_column": "id",
                    "primary_key_value": "1",
                    "changes": {"unknown_field": "x"},
                    "reason": "test",
                    "risk_level": "medium",
                },
                allowed_tables=["customers"],
                allowed_columns_by_table={"customers": ["id", "status"]},
            )

    def test_rejects_destructive_sql_payload(self) -> None:
        with self.assertRaises(ValueError):
            validate_write_proposal(
                {
                    "action": "update",
                    "table": "customers",
                    "primary_key_column": "id",
                    "primary_key_value": "1",
                    "changes": {"status": "drop table customers"},
                    "reason": "test",
                    "risk_level": "medium",
                },
                allowed_tables=["customers"],
                allowed_columns_by_table={"customers": ["id", "status"]},
            )

    def test_rejects_semicolon_sql_injection(self) -> None:
        with self.assertRaises(ValueError):
            validate_filter_plan(
                {
                    "table": "customers",
                    "keyword": "Makassar; DROP TABLE customers",
                    "filters": [],
                    "sort_by": "id",
                    "sort_direction": "asc",
                    "limit": 100,
                },
                allowed_tables=["customers"],
                allowed_columns=["id", "status"],
            )


if __name__ == "__main__":
    unittest.main()

