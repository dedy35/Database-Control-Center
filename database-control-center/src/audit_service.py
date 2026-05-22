from __future__ import annotations

import json
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import Column, DateTime, Integer, MetaData, String, Table, Text, inspect, select
from sqlalchemy.engine import Connection, Engine


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def define_audit_table(metadata: MetaData) -> Table:
    return Table(
        "audit_log",
        metadata,
        Column("id", Integer, primary_key=True, autoincrement=True),
        Column("table_name", String(255), nullable=False),
        Column("record_id", String(255), nullable=False),
        Column("action", String(100), nullable=False),
        Column("before_data", Text, nullable=True),
        Column("after_data", Text, nullable=True),
        Column("actor", String(255), nullable=False),
        Column("created_at", DateTime(timezone=True), nullable=False),
    )


def create_audit_log_table(bind: Engine | Connection) -> Table:
    metadata = MetaData()
    audit_table = define_audit_table(metadata)
    metadata.create_all(bind)
    return audit_table


def audit_log_exists(bind: Engine | Connection) -> bool:
    try:
        return bool(inspect(bind).has_table("audit_log"))
    except Exception:
        return False


def get_audit_log_table(bind: Engine | Connection) -> Table:
    if not audit_log_exists(bind):
        raise RuntimeError(
            "The active database does not contain an audit_log table. "
            "Create audit_log table in this database before performing write operations."
        )
    metadata = MetaData()
    return Table("audit_log", metadata, autoload_with=bind)


def _serialize_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _serialize_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_serialize_value(item) for item in value]
    if isinstance(value, tuple):
        return [_serialize_value(item) for item in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


def _json_text(data: Any) -> str | None:
    if data is None:
        return None
    return json.dumps(_serialize_value(data), ensure_ascii=False, default=str)


def _safe_json_loads(value: str | None) -> Any:
    if not value:
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def write_audit_entry(
    connection: Connection,
    table_name: str,
    record_id: Any,
    action: str,
    before_data: Any,
    after_data: Any,
    actor: str,
) -> None:
    audit_table = get_audit_log_table(connection)
    connection.execute(
        audit_table.insert().values(
            table_name=table_name,
            record_id=str(record_id),
            action=action,
            before_data=_json_text(before_data),
            after_data=_json_text(after_data),
            actor=actor,
            created_at=utc_now(),
        )
    )


def fetch_audit_logs(
    engine: Engine,
    table_name: str | None = None,
    action: str | None = None,
    actor: str | None = None,
    start_date: date | datetime | None = None,
    end_date: date | datetime | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    if not audit_log_exists(engine):
        return []
    audit_table = get_audit_log_table(engine)
    statement = select(audit_table).order_by(audit_table.c.created_at.desc()).limit(limit)

    if table_name:
        statement = statement.where(audit_table.c.table_name == table_name)
    if action:
        statement = statement.where(audit_table.c.action == action)
    if actor:
        statement = statement.where(audit_table.c.actor == actor)
    if start_date:
        statement = statement.where(audit_table.c.created_at >= start_date)
    if end_date:
        statement = statement.where(audit_table.c.created_at <= end_date)

    with engine.connect() as connection:
        rows = connection.execute(statement).mappings().all()

    result: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item["before_data_json"] = _safe_json_loads(item.get("before_data"))
        item["after_data_json"] = _safe_json_loads(item.get("after_data"))
        result.append(item)
    return result
