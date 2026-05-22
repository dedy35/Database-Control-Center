from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

import pandas as pd
from sqlalchemy import Select, String, func, or_, select
from sqlalchemy.engine import Engine
from sqlalchemy.sql.sqltypes import Boolean, Date, DateTime, Integer, Numeric

from src.schema_inspector import get_table_metadata, reflect_table


ALLOWED_OPERATORS = {
    "equals",
    "contains",
    "starts_with",
    "ends_with",
    "greater_than",
    "less_than",
    "between",
    "is_null",
    "is_not_null",
}

SAFE_LIMITS = {50, 100, 500, 1000}


def _coerce_filter_value(column: Any, value: Any) -> Any:
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


def _build_filter_condition(column: Any, operator: str, raw_value: Any, second_value: Any = None) -> Any:
    operator = operator.lower()
    if operator not in ALLOWED_OPERATORS:
        raise ValueError(f"Unsupported operator: {operator}")

    if operator == "is_null":
        return column.is_(None)
    if operator == "is_not_null":
        return column.is_not(None)

    if operator == "between" and isinstance(raw_value, (list, tuple)) and len(raw_value) == 2:
        lower_value = _coerce_filter_value(column, raw_value[0])
        upper_value = _coerce_filter_value(column, raw_value[1])
        return column.between(lower_value, upper_value)

    value = _coerce_filter_value(column, raw_value)
    second = _coerce_filter_value(column, second_value)

    if operator == "equals":
        return column == value
    if operator == "contains":
        return func.lower(column.cast(String)).like(f"%{str(raw_value).lower()}%")
    if operator == "starts_with":
        return func.lower(column.cast(String)).like(f"{str(raw_value).lower()}%")
    if operator == "ends_with":
        return func.lower(column.cast(String)).like(f"%{str(raw_value).lower()}")
    if operator == "greater_than":
        return column > value
    if operator == "less_than":
        return column < value
    if operator == "between":
        return column.between(value, second)
    raise ValueError(f"Unsupported operator: {operator}")


def build_select_statement(
    engine: Engine,
    table_name: str,
    keyword: str | None = None,
    filters: list[dict[str, Any]] | None = None,
    sort_by: str | None = None,
    sort_direction: str = "asc",
    limit: int = 100,
    include_soft_deleted: bool = False,
) -> tuple[Select[Any], dict[str, Any]]:
    table = reflect_table(engine, table_name)
    metadata = get_table_metadata(engine, table_name)
    limit_value = limit if limit in SAFE_LIMITS else 100
    statement = select(table)

    if metadata["has_deleted_at"] and not include_soft_deleted:
        statement = statement.where(table.c.deleted_at.is_(None))

    normalized_keyword = (keyword or "").strip()
    if normalized_keyword and metadata["text_columns"]:
        pattern = f"%{normalized_keyword.lower()}%"
        conditions = [func.lower(table.c[column_name].cast(String)).like(pattern) for column_name in metadata["text_columns"]]
        statement = statement.where(or_(*conditions))

    for filter_item in filters or []:
        column_name = filter_item.get("column")
        if not column_name or column_name not in table.c:
            continue
        condition = _build_filter_condition(
            table.c[column_name],
            str(filter_item.get("operator", "equals")),
            filter_item.get("value"),
            filter_item.get("second_value"),
        )
        statement = statement.where(condition)

    if sort_by and sort_by in table.c:
        sort_column = table.c[sort_by]
        statement = statement.order_by(sort_column.desc() if str(sort_direction).lower() == "desc" else sort_column.asc())
    else:
        primary_key = metadata["primary_key"]
        if primary_key and primary_key in table.c:
            statement = statement.order_by(table.c[primary_key].desc())

    statement = statement.limit(limit_value)
    return statement, metadata


def fetch_dataframe(engine: Engine, statement: Select[Any]) -> pd.DataFrame:
    with engine.connect() as connection:
        return pd.read_sql(statement, connection)
