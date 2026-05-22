from __future__ import annotations

from typing import Any

from sqlalchemy import MetaData, Table, func, inspect, select
from sqlalchemy.engine import Engine
from sqlalchemy.sql.sqltypes import Boolean, Date, DateTime, Integer, LargeBinary, Numeric, String, Text


def reflect_table(engine: Engine, table_name: str) -> Table:
    metadata = MetaData()
    return Table(table_name, metadata, autoload_with=engine)


def get_table_names(engine: Engine, include_audit: bool = False) -> list[str]:
    tables = inspect(engine).get_table_names()
    if include_audit:
        return sorted(tables)
    return sorted(table for table in tables if table != "audit_log")


def get_primary_key_column(table: Table) -> str | None:
    for column in table.columns:
        if column.primary_key:
            return column.name
    return None


def _column_flags(column: Any) -> dict[str, bool]:
    return {
        "is_text": isinstance(column.type, (String, Text)),
        "is_numeric": isinstance(column.type, (Integer, Numeric)),
        "is_datetime": isinstance(column.type, (Date, DateTime)),
        "is_boolean": isinstance(column.type, Boolean),
        "is_binary": isinstance(column.type, LargeBinary),
    }


def get_table_metadata(engine: Engine, table_name: str) -> dict[str, Any]:
    table = reflect_table(engine, table_name)
    primary_key = get_primary_key_column(table)
    columns: list[dict[str, Any]] = []

    text_columns: list[str] = []
    numeric_columns: list[str] = []
    date_columns: list[str] = []
    editable_columns: list[str] = []

    for column in table.columns:
        flags = _column_flags(column)
        if flags["is_text"]:
            text_columns.append(column.name)
        if flags["is_numeric"]:
            numeric_columns.append(column.name)
        if flags["is_datetime"]:
            date_columns.append(column.name)
        if not column.primary_key and not flags["is_binary"]:
            editable_columns.append(column.name)
        columns.append(
            {
                "name": column.name,
                "type": str(column.type),
                "nullable": bool(column.nullable),
                "primary_key": bool(column.primary_key),
                "default": None if column.default is None else str(column.default.arg),
                **flags,
            }
        )

    return {
        "table_name": table_name,
        "primary_key": primary_key,
        "columns": columns,
        "column_names": [column["name"] for column in columns],
        "text_columns": text_columns,
        "numeric_columns": numeric_columns,
        "date_columns": date_columns,
        "editable_columns": editable_columns,
        "has_deleted_at": "deleted_at" in table.columns,
        "has_updated_at": "updated_at" in table.columns,
        "has_created_at": "created_at" in table.columns,
    }


def get_table_row_count(engine: Engine, table_name: str) -> int:
    table = reflect_table(engine, table_name)
    with engine.connect() as connection:
        return int(connection.execute(select(func.count()).select_from(table)).scalar_one())
