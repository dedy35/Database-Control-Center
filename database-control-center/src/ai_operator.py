from __future__ import annotations

import json
from typing import Any

from src.activity_log import log_activity
from src.ai_response_parser import parse_ai_response
from src.ollama_client import chat, check_ollama_health


def _truncate_value(value: Any, *, max_text: int = 240) -> Any:
    if isinstance(value, dict):
        return {str(key): _truncate_value(item, max_text=max_text) for key, item in list(value.items())[:30]}
    if isinstance(value, list):
        return [_truncate_value(item, max_text=max_text) for item in value[:20]]
    if isinstance(value, str):
        trimmed = value[:max_text]
        return trimmed + "..." if len(value) > max_text else trimmed
    return value


def prepare_ai_context(page_context: dict[str, Any]) -> dict[str, Any]:
    safe_context = _truncate_value(page_context)
    if isinstance(safe_context, dict):
        for blocked_key in ("database_url", "connection_url", "connection_string", "password", "username"):
            safe_context.pop(blocked_key, None)
    return safe_context


class AIOperator:
    def __init__(self, model_name: str) -> None:
        self.model_name = model_name

    def operate(self, user_message: str, page_context: dict[str, Any]) -> dict[str, Any]:
        safe_context = prepare_ai_context(page_context)
        log_activity(
            "AI_CHAT_MESSAGE",
            "AI operator received a new chat message.",
            {"message": _truncate_value(user_message, max_text=400), "page": safe_context.get("page")},
        )
        ok, message = check_ollama_health()
        if not ok:
            warning = {
                "type": "warning",
                "message": "Ollama is not running. Start it with: ollama serve",
                "filter_plan": None,
                "write_proposal": None,
                "report_draft": None,
                "confidence": "high",
                "requires_user_confirmation": False,
            }
            log_activity("AI_ERROR", "Ollama was unavailable for the AI operator.", {"details": message})
            return warning

        system_prompt = (
            "You are an AI operator for a desktop database investigation tool.\n"
            "Return JSON only.\n"
            "Never reveal or ask for database credentials.\n"
            "Never output SQL.\n"
            "Never claim you directly connected to the database.\n"
            "You may return one of these response types: explanation, filter_plan, write_proposal, report_draft, warning, unsupported.\n"
            "Any write_proposal must require human approval.\n"
            "Filter plans must only use safe filtering keys.\n"
        )
        user_prompt = (
            f"Current safe page context:\n{json.dumps(safe_context, ensure_ascii=False, default=str)}\n\n"
            f"User message:\n{user_message}\n\n"
            "Return JSON with keys: type, message, filter_plan, write_proposal, report_draft, confidence, requires_user_confirmation."
        )
        response_text = chat(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            model=self.model_name,
        )
        parsed = parse_ai_response(response_text)
        return parsed

