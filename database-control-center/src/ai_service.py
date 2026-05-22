from __future__ import annotations

import json
from typing import Any

import pandas as pd

from src.ollama_client import chat, generate
from src.query_builder import ALLOWED_OPERATORS, SAFE_LIMITS


ALLOWED_PLAN_KEYS = {"table", "keyword", "filters", "sort_by", "sort_direction", "limit"}


def _trim_markdown_fence(text: str) -> str:
    candidate = text.strip()
    if candidate.startswith("```"):
        lines = candidate.splitlines()
        if len(lines) >= 3:
            candidate = "\n".join(lines[1:-1]).strip()
    return candidate


def extract_json_object(text: str) -> dict[str, Any]:
    candidate = _trim_markdown_fence(text)
    start = candidate.find("{")
    end = candidate.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("AI response does not contain a JSON object.")
    return json.loads(candidate[start : end + 1])


def validate_query_plan(
    payload: dict[str, Any],
    *,
    allowed_tables: list[str],
    allowed_columns: list[str],
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("Query plan must be a JSON object.")

    extra_keys = set(payload) - ALLOWED_PLAN_KEYS
    if extra_keys:
        raise ValueError(f"Unsupported keys in query plan: {', '.join(sorted(extra_keys))}")

    table_name = payload.get("table")
    if not isinstance(table_name, str) or table_name not in allowed_tables:
        raise ValueError("Query plan references an unknown table.")

    keyword = payload.get("keyword")
    if keyword is not None and not isinstance(keyword, str):
        raise ValueError("Keyword must be a string.")

    filters = payload.get("filters", [])
    if not isinstance(filters, list):
        raise ValueError("Filters must be a list.")

    validated_filters: list[dict[str, Any]] = []
    for item in filters:
        if not isinstance(item, dict):
            raise ValueError("Each filter must be an object.")
        column = item.get("column")
        operator = item.get("operator")
        if column not in allowed_columns:
            raise ValueError(f"Unknown filter column: {column}")
        if operator not in ALLOWED_OPERATORS:
            raise ValueError(f"Unsupported filter operator: {operator}")

        cleaned: dict[str, Any] = {"column": column, "operator": operator}
        if operator not in {"is_null", "is_not_null"}:
            if "value" not in item:
                raise ValueError(f"Filter '{column}' requires a value.")
            cleaned["value"] = item.get("value")
        if operator == "between":
            if "second_value" in item:
                cleaned["second_value"] = item["second_value"]
            elif isinstance(item.get("value"), list) and len(item["value"]) == 2:
                cleaned["value"] = item["value"]
            else:
                raise ValueError("Between filters require two values.")
        validated_filters.append(cleaned)

    sort_by = payload.get("sort_by")
    if sort_by is not None and sort_by not in allowed_columns:
        raise ValueError("Unknown sort column.")

    sort_direction = str(payload.get("sort_direction", "asc")).lower()
    if sort_direction not in {"asc", "desc"}:
        raise ValueError("Sort direction must be 'asc' or 'desc'.")

    limit = int(payload.get("limit", 100))
    if limit not in SAFE_LIMITS:
        raise ValueError(f"Limit must be one of: {sorted(SAFE_LIMITS)}")

    return {
        "table": table_name,
        "keyword": keyword,
        "filters": validated_filters,
        "sort_by": sort_by,
        "sort_direction": sort_direction,
        "limit": limit,
    }


def explain_schema(table_name: str, schema_summary: dict[str, Any], model: str | None = None) -> str:
    prompt = (
        "Explain this database table in simple language for a non-SQL user.\n\n"
        f"Database display name: {schema_summary.get('database_name', 'Active Database')}\n"
        f"Table: {table_name}\n"
        f"Schema summary: {json.dumps(schema_summary, ensure_ascii=False, default=str)}\n"
    )
    return generate(prompt, model=model)


def explain_data_sample(
    table_name: str,
    sample_rows: list[dict[str, Any]],
    model: str | None = None,
    database_name: str | None = None,
) -> str:
    prompt = (
        "Explain what this data sample appears to contain in simple language.\n\n"
        f"Database display name: {database_name or 'Active Database'}\n"
        f"Table: {table_name}\n"
        f"Sample rows: {json.dumps(sample_rows, ensure_ascii=False, default=str)}\n"
    )
    return generate(prompt, model=model)


def summarize_dataframe(
    table_name: str,
    frame: pd.DataFrame,
    model: str | None = None,
    database_name: str | None = None,
) -> str:
    sample_rows = frame.head(20).to_dict(orient="records")
    prompt = (
        "Summarize the important patterns in this filtered dataset for an internal business user.\n\n"
        f"Database display name: {database_name or 'Active Database'}\n"
        f"Table: {table_name}\n"
        f"Row count: {len(frame)}\n"
        f"Sample rows: {json.dumps(sample_rows, ensure_ascii=False, default=str)}\n"
    )
    return generate(prompt, model=model)


def detect_anomalies(
    table_name: str,
    frame: pd.DataFrame,
    model: str | None = None,
    database_name: str | None = None,
) -> str:
    sample_rows = frame.head(25).to_dict(orient="records")
    prompt = (
        "Review this dataset sample and point out possible anomalies, inconsistencies, or questions to investigate. "
        "Do not claim certainty when the sample is limited.\n\n"
        f"Database display name: {database_name or 'Active Database'}\n"
        f"Table: {table_name}\n"
        f"Row count: {len(frame)}\n"
        f"Sample rows: {json.dumps(sample_rows, ensure_ascii=False, default=str)}\n"
    )
    return generate(prompt, model=model)


def draft_report(
    table_name: str,
    frame: pd.DataFrame,
    model: str | None = None,
    database_name: str | None = None,
) -> str:
    sample_rows = frame.head(25).to_dict(orient="records")
    prompt = (
        "Draft a concise internal report based on this dataset. Use plain language and highlight the main findings.\n\n"
        f"Database display name: {database_name or 'Active Database'}\n"
        f"Table: {table_name}\n"
        f"Row count: {len(frame)}\n"
        f"Sample rows: {json.dumps(sample_rows, ensure_ascii=False, default=str)}\n"
    )
    return generate(prompt, model=model)


def request_safe_query_plan(
    user_request: str,
    *,
    database_name: str,
    table_name: str,
    schema_summary: dict[str, Any],
    allowed_tables: list[str],
    allowed_columns: list[str],
    model: str | None = None,
) -> dict[str, Any]:
    messages = [
        {
            "role": "system",
            "content": (
                "You are a database analysis assistant. Return JSON only. "
                "Do not output SQL. Do not ask for credentials. "
                "You may only create safe search and filter plans. "
                "Do not claim that you connected to the database directly."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Active database display name: {database_name}\n"
                f"Selected table: {table_name}\n"
                f"Available schema: {json.dumps(schema_summary, ensure_ascii=False, default=str)}\n"
                f"Allowed limit values: {sorted(SAFE_LIMITS)}\n"
                "Return JSON with keys: table, keyword, filters, sort_by, sort_direction, limit.\n"
                f"User request: {user_request}"
            ),
        },
    ]
    response_text = chat(messages, model=model)
    payload = extract_json_object(response_text)
    return validate_query_plan(payload, allowed_tables=allowed_tables, allowed_columns=allowed_columns)
