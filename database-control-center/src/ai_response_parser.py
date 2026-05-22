from __future__ import annotations

import json
from typing import Any


DEFAULT_ENVELOPE = {
    "type": "explanation",
    "message": "",
    "filter_plan": None,
    "write_proposal": None,
    "report_draft": None,
    "confidence": "low",
    "requires_user_confirmation": False,
}

ALLOWED_RESPONSE_TYPES = {
    "explanation",
    "filter_plan",
    "write_proposal",
    "report_draft",
    "warning",
    "unsupported",
}


def _trim_markdown_fence(text: str) -> str:
    candidate = text.strip()
    if candidate.startswith("```"):
        lines = candidate.splitlines()
        if len(lines) >= 3:
            candidate = "\n".join(lines[1:-1]).strip()
    return candidate


def _extract_json_candidate(text: str) -> str | None:
    candidate = _trim_markdown_fence(text)
    start = candidate.find("{")
    end = candidate.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    return candidate[start : end + 1]


def _normalize_envelope(payload: dict[str, Any], *, fallback_message: str) -> dict[str, Any]:
    envelope = dict(DEFAULT_ENVELOPE)
    envelope.update(payload)
    if envelope["type"] not in ALLOWED_RESPONSE_TYPES:
        envelope["type"] = "explanation"
    envelope["message"] = str(envelope.get("message") or fallback_message or "").strip()
    envelope["confidence"] = str(envelope.get("confidence") or "low").lower()
    if envelope["confidence"] not in {"low", "medium", "high"}:
        envelope["confidence"] = "low"
    envelope["requires_user_confirmation"] = bool(envelope.get("requires_user_confirmation", False))
    return envelope


def parse_ai_response(text: str) -> dict[str, Any]:
    candidate = _extract_json_candidate(text)
    if candidate is None:
        envelope = dict(DEFAULT_ENVELOPE)
        envelope["message"] = text.strip()
        return envelope

    try:
        payload = json.loads(candidate)
    except json.JSONDecodeError:
        envelope = dict(DEFAULT_ENVELOPE)
        envelope["message"] = text.strip()
        return envelope

    if not isinstance(payload, dict):
        envelope = dict(DEFAULT_ENVELOPE)
        envelope["message"] = text.strip()
        return envelope

    return _normalize_envelope(payload, fallback_message=text.strip())

