from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, MutableMapping
from urllib.parse import quote_plus

from sqlalchemy.engine import Engine

from src.config import DEFAULT_SQLITE_URL, get_settings, normalize_database_url
from src.db import get_database_type, get_engine, mask_database_url, test_connection


DEFAULT_PROFILE_NAME = "Local Demo SQLite"
SESSION_PREFIXES_TO_CLEAR = (
    "explorer_",
    "add_",
    "edit_",
    "import_export_",
    "ai_",
    "update_",
    "delete_",
    "import_",
    "audit_",
    "prepared_",
)
SESSION_KEYS_TO_CLEAR = {
    "last_results",
    "last_results_table",
    "last_query_plan",
    "pending_add",
    "pending_update",
    "pending_delete",
    "ai_plan",
}

_GLOBAL_STATE: dict[str, Any] = {}


def default_db_profile() -> dict[str, str]:
    return {
        "name": DEFAULT_PROFILE_NAME,
        "type": "sqlite",
        "url": DEFAULT_SQLITE_URL,
        "description": "Default local demo database",
    }


def _state(target: MutableMapping[str, Any] | None = None) -> MutableMapping[str, Any]:
    return target if target is not None else _GLOBAL_STATE


def normalize_profile(profile: dict[str, Any]) -> dict[str, str]:
    normalized = {
        "name": str(profile.get("name") or "Unnamed Connection").strip() or "Unnamed Connection",
        "type": str(profile.get("type") or get_database_type(str(profile.get("url", "")))).strip().lower(),
        "url": str(profile.get("url") or "").strip(),
        "description": str(profile.get("description") or "").strip(),
    }
    if not normalized["url"]:
        raise ValueError("Database profile is missing a URL.")
    if not normalized["type"] or normalized["type"] == "sqlalchemy compatible":
        normalized["type"] = get_database_type(normalized["url"]).lower()
    return normalized


def load_db_profiles(raw_json: str | None = None) -> list[dict[str, str]]:
    settings = get_settings()
    raw_value = raw_json if raw_json is not None else settings.db_profiles_json
    if not raw_value:
        return [default_db_profile()]

    try:
        payload = json.loads(raw_value)
        if isinstance(payload, str):
            payload = json.loads(payload)
        if not isinstance(payload, list) or not payload:
            return [default_db_profile()]
        profiles = [normalize_profile(item) for item in payload if isinstance(item, dict)]
        return profiles or [default_db_profile()]
    except (ValueError, TypeError, json.JSONDecodeError):
        return [default_db_profile()]


def build_manual_database_url(database_type: str, form_data: dict[str, Any]) -> str:
    selected_type = database_type.strip().lower()
    if selected_type == "sqlite":
        sqlite_path = str(form_data.get("sqlite_path") or "data/app.db").strip()
        if sqlite_path.startswith("sqlite:///"):
            return sqlite_path
        normalized_path = sqlite_path.replace("\\", "/")
        return f"sqlite:///{normalized_path}"

    if selected_type == "postgresql":
        host = str(form_data.get("host") or "localhost").strip()
        port = str(form_data.get("port") or "5432").strip()
        database_name = str(form_data.get("database_name") or "").strip()
        username = quote_plus(str(form_data.get("username") or "").strip())
        password = quote_plus(str(form_data.get("password") or ""))
        ssl_mode = str(form_data.get("ssl_mode") or "").strip()
        url = f"postgresql+psycopg2://{username}:{password}@{host}:{port}/{database_name}"
        if ssl_mode:
            url += f"?sslmode={quote_plus(ssl_mode)}"
        return url

    if selected_type in {"mysql / mariadb", "mysql", "mariadb"}:
        host = str(form_data.get("host") or "localhost").strip()
        port = str(form_data.get("port") or "3306").strip()
        database_name = str(form_data.get("database_name") or "").strip()
        username = quote_plus(str(form_data.get("username") or "").strip())
        password = quote_plus(str(form_data.get("password") or ""))
        ssl_mode = str(form_data.get("ssl_mode") or "").strip()
        url = f"mysql+pymysql://{username}:{password}@{host}:{port}/{database_name}"
        if ssl_mode:
            url += f"?ssl_mode={quote_plus(ssl_mode)}"
        return url

    if selected_type in {"sql server", "mssql", "microsoft sql server"}:
        server = str(form_data.get("server") or "localhost").strip()
        database_name = str(form_data.get("database_name") or "").strip()
        username = str(form_data.get("username") or "").strip()
        password = str(form_data.get("password") or "")
        encrypt = str(form_data.get("encrypt") or "yes").strip() or "yes"
        trust_server_certificate = "yes" if bool(form_data.get("trust_server_certificate", True)) else "no"
        connect_timeout = str(form_data.get("connect_timeout") or "30").strip() or "30"
        application_name = (
            str(form_data.get("application_name") or "Database Control Center").strip() or "Database Control Center"
        )
        driver = str(form_data.get("driver") or "ODBC Driver 18 for SQL Server").strip() or "ODBC Driver 18 for SQL Server"
        odbc_parts = [
            f"DRIVER={{{driver}}}",
            f"SERVER={server}",
            f"DATABASE={database_name}",
            f"UID={username}",
            f"PWD={password}",
            f"Encrypt={encrypt}",
            f"TrustServerCertificate={trust_server_certificate}",
            f"Connection Timeout={connect_timeout}",
            f"APP={application_name}",
            "ApplicationIntent=ReadWrite",
        ]
        odbc_connect = ";".join(odbc_parts) + ";"
        return f"mssql+pyodbc:///?odbc_connect={quote_plus(odbc_connect)}"

    full_url = str(form_data.get("full_url") or "").strip()
    if not full_url:
        raise ValueError("A full SQLAlchemy database URL is required.")
    return full_url


def build_manual_profile(connection_name: str, database_type: str, form_data: dict[str, Any]) -> dict[str, str]:
    url = build_manual_database_url(database_type, form_data)
    normalized_type = database_type.strip().lower()
    if normalized_type == "sqlite":
        profile_type = "sqlite"
    elif normalized_type == "postgresql":
        profile_type = "postgresql"
    elif normalized_type in {"mysql / mariadb", "mysql", "mariadb"}:
        profile_type = "mysql"
    elif normalized_type in {"sql server", "mssql", "microsoft sql server"}:
        profile_type = "mssql"
    else:
        profile_type = get_database_type(url).lower()
    return normalize_profile(
        {
            "name": connection_name.strip() or "Manual Connection",
            "type": profile_type,
            "url": url,
            "description": "Manual session connection",
        }
    )


def clear_database_context(state: MutableMapping[str, Any] | None = None) -> None:
    target = _state(state)
    for key in list(target.keys()):
        if key in SESSION_KEYS_TO_CLEAR or any(key.startswith(prefix) for prefix in SESSION_PREFIXES_TO_CLEAR):
            target.pop(key, None)


def set_active_database_profile(
    state: MutableMapping[str, Any] | None,
    profile: dict[str, Any],
    *,
    clear_existing_context: bool = True,
) -> None:
    target = _state(state)
    normalized = normalize_profile(profile)
    if clear_existing_context:
        clear_database_context(target)
    target["active_db_profile"] = normalized
    target["active_database_url"] = normalized["url"]
    target["active_database_name"] = normalized["name"]
    target["active_engine"] = get_engine(normalized["url"])


def add_profile_to_session(state: MutableMapping[str, Any] | None, profile: dict[str, Any]) -> None:
    target = _state(state)
    normalized = normalize_profile(profile)
    profiles = list(target.get("db_profiles", []))
    if not any(item.get("name") == normalized["name"] and item.get("url") == normalized["url"] for item in profiles):
        profiles.append(normalized)
    target["db_profiles"] = profiles


def initialize_connection_state(state: MutableMapping[str, Any] | None = None) -> None:
    target = _state(state)
    profiles = target.get("db_profiles")
    if not isinstance(profiles, list) or not profiles:
        profiles = load_db_profiles()
        target["db_profiles"] = profiles

    target.setdefault("selected_ollama_model", get_settings().ollama_model)

    if not target.get("active_database_url"):
        configured_url = normalize_database_url(get_settings().database_url)
        preferred = next((profile for profile in profiles if profile.get("url") == configured_url), None)
        if preferred is None:
            preferred = next((profile for profile in profiles if profile.get("name") == DEFAULT_PROFILE_NAME), profiles[0])
        set_active_database_profile(target, preferred, clear_existing_context=False)


def get_active_engine(state: MutableMapping[str, Any] | None = None) -> Engine:
    initialize_connection_state(state)
    target = _state(state)
    engine = target.get("active_engine")
    if engine is None:
        profile = target.get("active_db_profile") or default_db_profile()
        set_active_database_profile(target, profile, clear_existing_context=False)
        engine = target["active_engine"]
    return engine


def get_active_database_url(state: MutableMapping[str, Any] | None = None) -> str:
    initialize_connection_state(state)
    return str(_state(state).get("active_database_url") or DEFAULT_SQLITE_URL)


def get_active_database_name(state: MutableMapping[str, Any] | None = None) -> str:
    initialize_connection_state(state)
    return str(_state(state).get("active_database_name") or DEFAULT_PROFILE_NAME)


def get_db_profiles(state: MutableMapping[str, Any] | None = None) -> list[dict[str, str]]:
    initialize_connection_state(state)
    profiles = _state(state).get("db_profiles", [])
    return [normalize_profile(profile) for profile in profiles if isinstance(profile, dict)]


def connect_profile(
    profile: dict[str, Any],
    *,
    state: MutableMapping[str, Any] | None = None,
    add_to_session_profiles: bool = False,
) -> tuple[bool, str]:
    normalized = normalize_profile(profile)
    success, message = test_connection(normalized["url"])
    if not success:
        return False, message

    target = _state(state)
    if add_to_session_profiles:
        add_profile_to_session(target, normalized)
    set_active_database_profile(target, normalized)
    return True, f"Connected to {normalized['name']}. Active database switched successfully."


def current_database_status(state: MutableMapping[str, Any] | None = None) -> dict[str, str]:
    initialize_connection_state(state)
    target = _state(state)
    database_url = get_active_database_url(target)
    return {
        "name": get_active_database_name(target),
        "type": get_database_type(database_url),
        "url": database_url,
        "masked_url": mask_database_url(database_url),
    }


def sqlite_profile_for_path(path_value: str) -> dict[str, str]:
    normalized_path = Path(path_value).as_posix() if ":" not in path_value else path_value.replace("\\", "/")
    return normalize_profile(
        {
            "name": DEFAULT_PROFILE_NAME,
            "type": "sqlite",
            "url": f"sqlite:///{normalized_path}",
            "description": "Default local demo database",
        }
    )


@dataclass
class ConnectionManager:
    state: MutableMapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        initialize_connection_state(self.state)

    def initialize(self) -> None:
        initialize_connection_state(self.state)

    def clear_database_context(self) -> None:
        clear_database_context(self.state)

    def set_active_database_profile(self, profile: dict[str, Any], *, clear_existing_context: bool = True) -> None:
        set_active_database_profile(self.state, profile, clear_existing_context=clear_existing_context)

    def add_profile(self, profile: dict[str, Any]) -> None:
        add_profile_to_session(self.state, profile)

    def connect_profile(self, profile: dict[str, Any], *, add_to_session_profiles: bool = False) -> tuple[bool, str]:
        return connect_profile(profile, state=self.state, add_to_session_profiles=add_to_session_profiles)

    def get_active_engine(self) -> Engine:
        return get_active_engine(self.state)

    def get_active_database_url(self) -> str:
        return get_active_database_url(self.state)

    def get_active_database_name(self) -> str:
        return get_active_database_name(self.state)

    def current_database_status(self) -> dict[str, str]:
        return current_database_status(self.state)

    def get_profiles(self) -> list[dict[str, str]]:
        return get_db_profiles(self.state)

