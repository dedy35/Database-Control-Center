from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.activity_log import fetch_activity_logs, log_activity


class ActivityLogTests(unittest.TestCase):
    def test_log_masks_secrets(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "activity.db"
            log_activity(
                "AI_CHAT_MESSAGE",
                "Testing log safety",
                {
                    "database_url": "postgresql+psycopg2://alice:secret@localhost:5432/appdb",
                    "password": "secret",
                    "message": "UID=sa;PWD=Tcomm7447;",
                },
                path=db_path,
            )
            rows = fetch_activity_logs(path=db_path)
            self.assertEqual(len(rows), 1)
            payload = rows[0]["payload"]
            self.assertEqual(payload["database_url"], "********")
            self.assertEqual(payload["password"], "********")
            self.assertNotIn("Tcomm7447", str(payload["message"]))


if __name__ == "__main__":
    unittest.main()

