from __future__ import annotations

import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from src.config import DATA_DIR
from src.db import mask_database_url


ACTIVITY_DB_PATH = DATA_DIR / "app_activity.db"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@contextmanager
def activity_connection(path: Path | None = None) -> Iterator[sqlite3.Connection]:
    database_path = path or ACTIVITY_DB_PATH
    database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database_path)
    try:
        ensure_activity_log_table(connection)
        yield connection
    finally:
        connection.close()


def ensure_activity_log_table(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS app_activity_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT NOT NULL,
            summary TEXT NOT NULL,
            payload_json TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    connection.commit()


def _sanitize_string(value: str) -> str:
    masked = mask_database_url(value)
    masked = re.sub(r"(?i)(password|pwd)\s*[:=]\s*[^;,\s]+", r"\1=********", masked)
    masked = re.sub(r"(?i)(username|user id|uid)\s*[:=]\s*[^;,\s]+", r"\1=********", masked)
    return masked


def sanitize_log_payload(value: Any) -> Any:
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            key_lower = str(key).lower()
            if key_lower in {"password", "pwd", "database_url", "connection_url", "connection_string", "username", "uid", "user id"}:
                sanitized[str(key)] = "********"
            else:
                sanitized[str(key)] = sanitize_log_payload(item)
        return sanitized
    if isinstance(value, list):
        return [sanitize_log_payload(item) for item in value]
    if isinstance(value, tuple):
        return [sanitize_log_payload(item) for item in value]
    if isinstance(value, str):
        return _sanitize_string(value)
    return value


def log_activity(event_type: str, summary: str, payload: Any | None = None, *, path: Path | None = None) -> None:
    safe_summary = _sanitize_string(summary)
    safe_payload = sanitize_log_payload(payload)
    payload_json = None if safe_payload is None else json.dumps(safe_payload, ensure_ascii=False, default=str)
    with activity_connection(path) as connection:
        connection.execute(
            "INSERT INTO app_activity_log (event_type, summary, payload_json, created_at) VALUES (?, ?, ?, ?)",
            (event_type, safe_summary, payload_json, utc_now_iso()),
        )
        connection.commit()


def fetch_activity_logs(limit: int = 200, *, path: Path | None = None) -> list[dict[str, Any]]:
    with activity_connection(path) as connection:
        rows = connection.execute(
            "SELECT id, event_type, summary, payload_json, created_at FROM app_activity_log ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    result: list[dict[str, Any]] = []
    for row in rows:
        payload = None
        if row[3]:
            try:
                payload = json.loads(row[3])
            except json.JSONDecodeError:
                payload = row[3]
        result.append(
            {
                "id": row[0],
                "event_type": row[1],
                "summary": row[2],
                "payload": payload,
                "created_at": row[4],
            }
        )
    return result

