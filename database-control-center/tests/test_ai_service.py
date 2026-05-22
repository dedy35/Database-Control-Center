from __future__ import annotations

import unittest

from src.ai_service import validate_query_plan


class AIServiceTests(unittest.TestCase):
    def test_validate_query_plan_accepts_safe_payload(self) -> None:
        plan = validate_query_plan(
            {
                "table": "customers",
                "keyword": "Makassar",
                "filters": [{"column": "status", "operator": "equals", "value": "active"}],
                "sort_by": "created_at",
                "sort_direction": "desc",
                "limit": 100,
            },
            allowed_tables=["customers"],
            allowed_columns=["id", "status", "created_at", "city", "name"],
        )
        self.assertEqual(plan["table"], "customers")
        self.assertEqual(plan["limit"], 100)

    def test_validate_query_plan_rejects_unknown_operator(self) -> None:
        with self.assertRaises(ValueError):
            validate_query_plan(
                {
                    "table": "customers",
                    "filters": [{"column": "status", "operator": "drop_table", "value": "x"}],
                },
                allowed_tables=["customers"],
                allowed_columns=["status"],
            )

    def test_validate_query_plan_rejects_unknown_table(self) -> None:
        with self.assertRaises(ValueError):
            validate_query_plan(
                {"table": "secrets", "filters": []},
                allowed_tables=["customers"],
                allowed_columns=["status"],
            )


if __name__ == "__main__":
    unittest.main()
