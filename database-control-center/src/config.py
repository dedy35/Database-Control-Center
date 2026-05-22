from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv


APP_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = APP_ROOT / "data"
ENV_PATH = APP_ROOT / ".env"
DEFAULT_SQLITE_URL = f"sqlite:///{(DATA_DIR / 'app.db').as_posix()}"

load_dotenv(ENV_PATH)


def normalize_database_url(database_url: str | None) -> str:
    value = (database_url or "").strip()
    return value or DEFAULT_SQLITE_URL


@dataclass(frozen=True)
class Settings:
    database_url: str
    app_actor: str
    ollama_base_url: str
    ollama_model: str
    db_profiles_json: str


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return Settings(
        database_url=normalize_database_url(os.getenv("DATABASE_URL")),
        app_actor=(os.getenv("APP_ACTOR") or "local_user").strip() or "local_user",
        ollama_base_url=(os.getenv("OLLAMA_BASE_URL") or "http://localhost:11434").rstrip("/"),
        ollama_model=(os.getenv("OLLAMA_MODEL") or "llama3.2").strip() or "llama3.2",
        db_profiles_json=os.getenv("DB_PROFILES_JSON", "").strip(),
    )
