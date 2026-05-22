from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import Table, select
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.sql.sqltypes import Boolean, Date, DateTime, Integer, Numeric

from src.audit_service import audit_log_exists, write_audit_entry
from src.schema_inspector import get_primary_key_column, get_table_metadata, reflect_table


SYSTEM_COLUMNS = {"created_at", "updated_at", "deleted_at"}


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _coerce_value(column: Any, value: Any) -> Any:
    if value in (None, ""):
        return None
    if isinstance(column.type, Boolean):
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in {"1", "true", "yes", "y"}
    if isinstance(column.type, Integer):
        return int(value)
    if isinstance(column.type, Numeric):
        return Decimal(str(value))
    if isinstance(column.type, Date):
        if isinstance(value, date) and not isinstance(value, datetime):
            return value
        return date.fromisoformat(str(value))
    if isinstance(column.type, DateTime):
        if isinstance(value, datetime):
            return value
        return datetime.fromisoformat(str(value))
    return value


def _record_to_dict(record: Any) -> dict[str, Any]:
    if record is None:
        return {}
    return dict(record._mapping)


def prepare_record_payload(
    engine: Engine,
    table_name: str,
    data: dict[str, Any],
    *,
    include_system_fields: bool = False,
    for_update: bool = False,
) -> dict[str, Any]:
    table = reflect_table(engine, table_name)
    payload: dict[str, Any] = {}

    for column in table.columns:
        if column.name not in data:
            continue
        if column.primary_key and not for_update and data.get(column.name) in (None, ""):
            continue
        if column.name in SYSTEM_COLUMNS and not include_system_fields:
            continue
        payload[column.name] = _coerce_value(column, data[column.name])

    return payload


def _fetch_record(connection: Connection, table: Table, primary_key: str, record_id: Any) -> dict[str, Any] | None:
    row = connection.execute(select(table).where(table.c[primary_key] == _coerce_value(table.c[primary_key], record_id))).fetchone()
    if row is None:
        return None
    return _record_to_dict(row)


def get_record_by_pk(engine: Engine, table_name: str, record_id: Any) -> dict[str, Any] | None:
    table = reflect_table(engine, table_name)
    primary_key = get_primary_key_column(table)
    if not primary_key:
        raise ValueError(f"Table '{table_name}' has no primary key.")
    with engine.connect() as connection:
        return _fetch_record(connection, table, primary_key, record_id)


def list_record_choices(engine: Engine, table_name: str, limit: int = 100) -> list[tuple[str, str]]:
    table = reflect_table(engine, table_name)
    metadata = get_table_metadata(engine, table_name)
    primary_key = metadata["primary_key"]
    if not primary_key:
        return []

    statement = select(table).limit(limit)
    if metadata["has_deleted_at"]:
        statement = statement.where(table.c.deleted_at.is_(None))
    statement = statement.order_by(table.c[primary_key].desc())

    with engine.connect() as connection:
        rows = connection.execute(statement).mappings().all()

    label_fields = [name for name in ("name", "email", "status") if name in metadata["column_names"]]
    options: list[tuple[str, str]] = []
    for row in rows:
        label = " | ".join(str(row[field]) for field in label_fields) if label_fields else str(row[primary_key])
        options.append((str(row[primary_key]), f"{row[primary_key]} - {label}"))
    return options


def insert_record(
    engine: Engine,
    table_name: str,
    data: dict[str, Any],
    *,
    actor: str,
    include_system_fields: bool = False,
) -> Any:
    table = reflect_table(engine, table_name)
    primary_key = get_primary_key_column(table)
    payload = prepare_record_payload(
        engine,
        table_name,
        data,
        include_system_fields=include_system_fields,
        for_update=False,
    )
    now = utc_now()
    if "created_at" in table.c and "created_at" not in payload:
        payload["created_at"] = now
    if "updated_at" in table.c and "updated_at" not in payload:
        payload["updated_at"] = now
    if "deleted_at" in table.c and "deleted_at" not in payload:
        payload["deleted_at"] = None

    with engine.begin() as connection:
        if not audit_log_exists(connection):
            raise RuntimeError(
                "The active database does not contain an audit_log table. "
                "Create audit_log table in this database before performing write operations."
            )
        result = connection.execute(table.insert().values(**payload))
        record_id = result.inserted_primary_key[0] if result.inserted_primary_key else payload.get(primary_key or "id", "unknown")
        after_data = _fetch_record(connection, table, primary_key, record_id) if primary_key else payload
        write_audit_entry(connection, table_name, record_id, "INSERT", None, after_data, actor)
    return record_id


def update_record(
    engine: Engine,
    table_name: str,
    *,
    record_id: Any,
    data: dict[str, Any],
    actor: str,
    include_system_fields: bool = False,
) -> int:
    table = reflect_table(engine, table_name)
    primary_key = get_primary_key_column(table)
    if not primary_key:
        raise ValueError(f"Table '{table_name}' has no primary key.")

    payload = prepare_record_payload(
        engine,
        table_name,
        data,
        include_system_fields=include_system_fields,
        for_update=True,
    )
    if primary_key in payload:
        payload.pop(primary_key)
    if "updated_at" in table.c:
        payload["updated_at"] = utc_now()

    with engine.begin() as connection:
        if not audit_log_exists(connection):
            raise RuntimeError(
                "The active database does not contain an audit_log table. "
                "Create audit_log table in this database before performing write operations."
            )
        before_data = _fetch_record(connection, table, primary_key, record_id)
        if before_data is None:
            raise ValueError(f"Record '{record_id}' not found in '{table_name}'.")
        result = connection.execute(
            table.update()
            .where(table.c[primary_key] == _coerce_value(table.c[primary_key], record_id))
            .values(**payload)
        )
        after_data = _fetch_record(connection, table, primary_key, record_id)
        write_audit_entry(connection, table_name, record_id, "UPDATE", before_data, after_data, actor)
    return int(result.rowcount or 0)


def soft_delete_record(engine: Engine, table_name: str, *, record_id: Any, actor: str) -> int:
    table = reflect_table(engine, table_name)
    primary_key = get_primary_key_column(table)
    if not primary_key:
        raise ValueError(f"Table '{table_name}' has no primary key.")
    if "deleted_at" not in table.c:
        raise ValueError(f"Table '{table_name}' does not support soft delete.")

    payload = {"deleted_at": utc_now()}
    if "updated_at" in table.c:
        payload["updated_at"] = utc_now()

    with engine.begin() as connection:
        if not audit_log_exists(connection):
            raise RuntimeError(
                "The active database does not contain an audit_log table. "
                "Create audit_log table in this database before performing write operations."
            )
        before_data = _fetch_record(connection, table, primary_key, record_id)
        if before_data is None:
            raise ValueError(f"Record '{record_id}' not found in '{table_name}'.")
        result = connection.execute(
            table.update()
            .where(table.c[primary_key] == _coerce_value(table.c[primary_key], record_id))
            .values(**payload)
        )
        after_data = _fetch_record(connection, table, primary_key, record_id)
        write_audit_entry(connection, table_name, record_id, "SOFT_DELETE", before_data, after_data, actor)
    return int(result.rowcount or 0)


def bulk_import_records(
    engine: Engine,
    table_name: str,
    rows: list[dict[str, Any]],
    *,
    actor: str,
    include_system_fields: bool = False,
) -> int:
    if not rows:
        return 0

    table = reflect_table(engine, table_name)
    payloads = []
    for row in rows:
        payload = prepare_record_payload(
            engine,
            table_name,
            row,
            include_system_fields=include_system_fields,
            for_update=False,
        )
        now = utc_now()
        if "created_at" in table.c and "created_at" not in payload:
            payload["created_at"] = now
        if "updated_at" in table.c and "updated_at" not in payload:
            payload["updated_at"] = now
        if "deleted_at" in table.c and "deleted_at" not in payload:
            payload["deleted_at"] = None
        payloads.append(payload)

    with engine.begin() as connection:
        if not audit_log_exists(connection):
            raise RuntimeError(
                "The active database does not contain an audit_log table. "
                "Create audit_log table in this database before performing write operations."
            )
        connection.execute(table.insert(), payloads)
        write_audit_entry(
            connection,
            table_name,
            "bulk",
            "BULK_IMPORT",
            None,
            {"row_count": len(payloads), "columns": list(payloads[0].keys())},
            actor,
        )
    return len(payloads)
