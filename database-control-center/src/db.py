from __future__ import annotations

from contextlib import contextmanager
from functools import lru_cache
import re
from urllib.parse import parse_qsl, quote_plus, urlencode, urlsplit, urlunsplit

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.pool import NullPool

from src.config import get_settings, normalize_database_url


def mask_database_url(database_url: str) -> str:
    parsed = urlsplit(database_url)
    if parsed.password:
        username = parsed.username or ""
        hostname = parsed.hostname or ""
        port = f":{parsed.port}" if parsed.port else ""
        masked_netloc = f"{username}:********@{hostname}{port}"
        return urlunsplit((parsed.scheme, masked_netloc, parsed.path, parsed.query, parsed.fragment))

    query_items = parse_qsl(parsed.query, keep_blank_values=True)
    if not query_items:
        return database_url

    updated_items: list[tuple[str, str]] = []
    changed = False
    for key, value in query_items:
        if key.lower() == "odbc_connect":
            masked_value = re.sub(r"(PWD=)([^;]*)", r"\1********", value, flags=re.IGNORECASE)
            updated_items.append((key, masked_value))
            changed = changed or masked_value != value
        else:
            updated_items.append((key, value))

    if not changed:
        return database_url

    masked_query = urlencode(updated_items, doseq=True, quote_via=quote_plus)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, masked_query, parsed.fragment))


def get_database_type(database_url: str) -> str:
    lowered = database_url.lower()
    if lowered.startswith("sqlite"):
        return "SQLite"
    if lowered.startswith("postgresql"):
        return "PostgreSQL"
    if lowered.startswith("mysql") or lowered.startswith("mariadb"):
        return "MySQL / MariaDB"
    if lowered.startswith("mssql"):
        return "SQL Server"
    return "SQLAlchemy Compatible"


def _build_engine(database_url: str) -> Engine:
    engine_kwargs: dict[str, object] = {
        "future": True,
        "pool_pre_ping": True,
    }
    if database_url.startswith("sqlite"):
        engine_kwargs["connect_args"] = {"check_same_thread": False}
        engine_kwargs["poolclass"] = NullPool
    return create_engine(database_url, **engine_kwargs)


@lru_cache(maxsize=32)
def _get_cached_engine(database_url: str) -> Engine:
    return _build_engine(database_url)


def get_engine(database_url: str | None = None) -> Engine:
    settings = get_settings()
    resolved_url = normalize_database_url(database_url or settings.database_url)
    return _get_cached_engine(resolved_url)


@contextmanager
def get_connection(database_url: str | None = None) -> Connection:
    connection = get_engine(database_url).connect()
    try:
        yield connection
    finally:
        connection.close()


def test_connection(database_url: str | None = None) -> tuple[bool, str]:
    resolved_url = normalize_database_url(database_url or get_settings().database_url)
    try:
        engine = _build_engine(resolved_url)
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        engine.dispose()
        return True, f"Connection successful: {get_database_type(resolved_url)}"
    except (SQLAlchemyError, Exception) as exc:
        return False, f"Connection failed: {exc}"
