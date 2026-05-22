from __future__ import annotations

from typing import Any

import requests

from src.config import get_settings


def _base_url(base_url: str | None = None) -> str:
    return (base_url or get_settings().ollama_base_url).rstrip("/")


def _model_name(model: str | None = None) -> str:
    return (model or get_settings().ollama_model).strip() or "llama3.2"


def check_ollama_health(base_url: str | None = None) -> tuple[bool, str]:
    url = f"{_base_url(base_url)}/api/tags"
    try:
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        return True, "Ollama reachable"
    except requests.RequestException as exc:
        return False, f"Ollama unavailable: {exc}"


def list_models(base_url: str | None = None) -> list[str]:
    url = f"{_base_url(base_url)}/api/tags"
    response = requests.get(url, timeout=10)
    response.raise_for_status()
    payload = response.json()
    return [item.get("name", "") for item in payload.get("models", []) if item.get("name")]


def generate(prompt: str, model: str | None = None, base_url: str | None = None) -> str:
    url = f"{_base_url(base_url)}/api/generate"
    response = requests.post(
        url,
        json={
            "model": _model_name(model),
            "prompt": prompt,
            "stream": False,
        },
        timeout=120,
    )
    response.raise_for_status()
    return response.json().get("response", "")


def chat(messages: list[dict[str, Any]], model: str | None = None, base_url: str | None = None) -> str:
    url = f"{_base_url(base_url)}/api/chat"
    response = requests.post(
        url,
        json={
            "model": _model_name(model),
            "messages": messages,
            "stream": False,
        },
        timeout=120,
    )
    response.raise_for_status()
    payload = response.json()
    return payload.get("message", {}).get("content", "")
