from __future__ import annotations

import secrets
from dataclasses import asdict, dataclass, field
from typing import Any

from sqlalchemy.engine import Engine

from src.activity_log import log_activity
from src.audit_service import create_audit_log_table
from src.crud_service import bulk_import_records, insert_record, soft_delete_record, update_record


@dataclass
class WriteActionPlan:
    action: str
    table: str
    database_name: str
    database_type: str
    actor: str
    reason: str
    risk_level: str
    source: str = "manual_ui"
    primary_key_column: str | None = None
    primary_key_value: Any = None
    before_data: Any = None
    after_data: Any = None
    payload: dict[str, Any] = field(default_factory=dict)
    rows: list[dict[str, Any]] = field(default_factory=list)
    include_system_fields: bool = False
    write_summary: str = ""


_APPROVED_TOKENS: dict[str, dict[str, Any]] = {}


def validate_write_action_plan(plan: WriteActionPlan) -> WriteActionPlan:
    if plan.action not in {"insert", "update", "soft_delete", "import", "create_audit_log"}:
        raise ValueError("This action was blocked because it is not an allowed write operation.")
    if not plan.table and plan.action != "create_audit_log":
        raise ValueError("Write action is missing a target table.")
    if plan.action in {"insert", "update"} and not plan.payload:
        raise ValueError("Write action is missing change data.")
    if plan.action == "import" and not plan.rows:
        raise ValueError("Import action is missing rows.")
    if not plan.reason:
        raise ValueError("Write action is missing an explanation.")
    return plan


def plan_to_preview_data(plan: WriteActionPlan) -> dict[str, Any]:
    return {
        "action": plan.action,
        "database_name": plan.database_name,
        "database_type": plan.database_type,
        "table": plan.table,
        "primary_key_column": plan.primary_key_column,
        "primary_key_value": plan.primary_key_value,
        "before_data": plan.before_data,
        "after_data": plan.after_data,
        "risk_level": plan.risk_level,
        "reason": plan.reason,
        "source": plan.source,
        "write_summary": plan.write_summary,
    }


def create_confirmation_token(plan: WriteActionPlan) -> str:
    token = secrets.token_urlsafe(24)
    _APPROVED_TOKENS[token] = {
        "action": plan.action,
        "table": plan.table,
        "primary_key_value": str(plan.primary_key_value),
        "used": False,
    }
    return token


def reject_if_not_confirmed(plan: WriteActionPlan, confirmation_token: str | None) -> None:
    if not confirmation_token or confirmation_token not in _APPROVED_TOKENS:
        log_activity("WRITE_BLOCKED_READ_ONLY", "Write action was blocked because no approval token was present.", {"plan": asdict(plan)})
        raise PermissionError("This action was blocked because the app is currently in read-only mode.")
    token_state = _APPROVED_TOKENS[confirmation_token]
    if token_state.get("used"):
        raise PermissionError("This confirmation token has already been used.")
    if token_state.get("action") != plan.action or token_state.get("table") != plan.table:
        raise PermissionError("Confirmation token does not match the requested database change.")


def require_user_confirmation(plan: WriteActionPlan, preview_data: dict[str, Any], approved: bool) -> str:
    validate_write_action_plan(plan)
    log_write_attempt(plan, preview_data)
    if not approved:
        log_write_rejected(plan, "User cancelled the confirmation dialog.")
        raise PermissionError("Database change cancelled by user.")
    return create_confirmation_token(plan)


def execute_approved_write(plan: WriteActionPlan, confirmation_token: str | None, engine: Engine) -> Any:
    validate_write_action_plan(plan)
    reject_if_not_confirmed(plan, confirmation_token)
    token_state = _APPROVED_TOKENS[confirmation_token or ""]
    token_state["used"] = True

    if plan.action == "insert":
        result = insert_record(
            engine,
            plan.table,
            plan.payload,
            actor=plan.actor,
            include_system_fields=plan.include_system_fields,
        )
    elif plan.action == "update":
        result = update_record(
            engine,
            plan.table,
            record_id=plan.primary_key_value,
            data=plan.payload,
            actor=plan.actor,
            include_system_fields=plan.include_system_fields,
        )
    elif plan.action == "soft_delete":
        result = soft_delete_record(engine, plan.table, record_id=plan.primary_key_value, actor=plan.actor)
    elif plan.action == "import":
        result = bulk_import_records(
            engine,
            plan.table,
            plan.rows,
            actor=plan.actor,
            include_system_fields=plan.include_system_fields,
        )
    elif plan.action == "create_audit_log":
        create_audit_log_table(engine)
        result = "audit_log_created"
    else:
        raise ValueError("Unsupported write action.")

    log_write_success(plan, result)
    return result


def log_write_attempt(plan: WriteActionPlan, preview_data: dict[str, Any] | None = None) -> None:
    log_activity(
        "WRITE_APPROVAL_REQUESTED",
        f"{plan.source} requested {plan.action} on {plan.table or 'audit_log'}",
        {
            "plan": asdict(plan),
            "preview": preview_data or plan_to_preview_data(plan),
        },
    )


def log_write_success(plan: WriteActionPlan, result: Any) -> None:
    log_activity(
        "WRITE_EXECUTED",
        f"{plan.action} executed for {plan.table or 'audit_log'}",
        {
            "plan": asdict(plan),
            "result": result,
        },
    )


def log_write_rejected(plan: WriteActionPlan, reason: str) -> None:
    log_activity(
        "WRITE_CANCELLED",
        f"{plan.action} was rejected for {plan.table or 'audit_log'}",
        {
            "plan": asdict(plan),
            "reason": reason,
        },
    )
