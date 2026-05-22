from __future__ import annotations

from typing import Any

from src.ai_service import validate_query_plan


FORBIDDEN_SQL_KEYWORDS = {
    "drop",
    "alter",
    "truncate",
    "grant",
    "revoke",
    "execute",
    "delete from",
    "insert into",
    "update set",
    "create table",
    "hard delete",
}
ALLOWED_WRITE_ACTIONS = {"insert", "update", "soft_delete", "import"}
ALLOWED_RISK_LEVELS = {"low", "medium", "high"}
BLOCKED_COLUMNS = {"created_at", "updated_at", "deleted_at", "password"}


def _contains_sql_payload(value: Any) -> bool:
    if isinstance(value, dict):
        return any(_contains_sql_payload(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_sql_payload(item) for item in value)
    if isinstance(value, str):
        lowered = value.lower()
        if ";" in value:
            return True
        return any(keyword in lowered for keyword in FORBIDDEN_SQL_KEYWORDS)
    return False


def validate_filter_plan(
    payload: dict[str, Any],
    *,
    allowed_tables: list[str],
    allowed_columns: list[str],
) -> dict[str, Any]:
    validated = validate_query_plan(payload, allowed_tables=allowed_tables, allowed_columns=allowed_columns)
    if _contains_sql_payload(validated):
        raise ValueError("Filter plan contains blocked SQL-like content.")
    return validated


def validate_write_proposal(
    proposal: dict[str, Any],
    *,
    allowed_tables: list[str],
    allowed_columns_by_table: dict[str, list[str]],
    allow_system_columns: bool = False,
) -> dict[str, Any]:
    if not isinstance(proposal, dict):
        raise ValueError("Write proposal must be a JSON object.")

    action = str(proposal.get("action") or "").lower()
    table_name = str(proposal.get("table") or "")
    changes = proposal.get("changes")
    risk_level = str(proposal.get("risk_level") or "medium").lower()
    primary_key_column = str(proposal.get("primary_key_column") or "").strip() or None
    primary_key_value = proposal.get("primary_key_value")

    if action not in ALLOWED_WRITE_ACTIONS:
        raise ValueError("AI proposed an unsupported write action.")
    if table_name not in allowed_tables:
        raise ValueError("AI proposed a write action for an unknown table.")
    if risk_level not in ALLOWED_RISK_LEVELS:
        raise ValueError("Write proposal is missing a valid risk level.")
    if _contains_sql_payload(proposal):
        raise ValueError("AI proposed blocked SQL-like content. No database changes were made.")

    allowed_columns = set(allowed_columns_by_table.get(table_name, []))
    if action != "import":
        if not isinstance(changes, dict) or not changes:
            raise ValueError("Write proposal must contain non-empty changes.")
        unknown_columns = sorted(column for column in changes if column not in allowed_columns)
        if unknown_columns:
            raise ValueError(f"Unknown columns in write proposal: {', '.join(unknown_columns)}")
        if not allow_system_columns:
            blocked = sorted(column for column in changes if column in BLOCKED_COLUMNS)
            if blocked:
                raise ValueError(f"Write proposal tries to change blocked columns: {', '.join(blocked)}")

    if action in {"update", "soft_delete"}:
        if not primary_key_column or primary_key_column not in allowed_columns:
            raise ValueError("Write proposal must target a valid primary key column.")
        if primary_key_value in (None, ""):
            raise ValueError("Write proposal must target a specific primary key value.")

    result = {
        "action": action,
        "table": table_name,
        "primary_key_column": primary_key_column,
        "primary_key_value": primary_key_value,
        "changes": changes if isinstance(changes, dict) else {},
        "reason": str(proposal.get("reason") or "").strip(),
        "risk_level": risk_level,
        "requires_user_confirmation": True,
    }
    return result

