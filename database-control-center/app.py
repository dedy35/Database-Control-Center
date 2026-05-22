from __future__ import annotations

from datetime import date, datetime
from typing import Any

import pandas as pd
import streamlit as st
from sqlalchemy.exc import SQLAlchemyError

from src.ai_service import (
    detect_anomalies,
    draft_report,
    explain_data_sample,
    explain_schema,
    request_safe_query_plan,
    summarize_dataframe,
)
from src.audit_service import audit_log_exists, create_audit_log_table, fetch_audit_logs
from src.config import get_settings
from src.connection_manager import (
    build_manual_profile,
    connect_profile,
    current_database_status,
    get_active_database_name,
    get_active_database_url,
    get_active_engine,
    initialize_connection_state,
)
from src.crud_service import (
    bulk_import_records,
    get_record_by_pk,
    insert_record,
    list_record_choices,
    prepare_record_payload,
    soft_delete_record,
    update_record,
)
from src.db import get_database_type, mask_database_url, test_connection
from src.demo_seed import ensure_demo_seed_for_sqlite
from src.export_service import dataframe_to_csv_bytes, dataframe_to_excel_bytes, export_table_to_dataframe
from src.loading_ui import floating_spinner_css, loading_operation
from src.ollama_client import check_ollama_health, list_models
from src.query_builder import SAFE_LIMITS, build_select_statement, fetch_dataframe
from src.schema_inspector import get_table_metadata, get_table_names, get_table_row_count


st.set_page_config(page_title="Database Control Center", layout="wide")

PAGE_OPTIONS = [
    "Database Login / Connection Manager",
    "Dashboard",
    "Data Explorer",
    "Add Record",
    "Edit Record",
    "Import / Export",
    "AI Assistant",
    "Audit Log",
    "Settings / Health Check",
]

MANUAL_DB_TYPES = [
    "SQLite",
    "PostgreSQL",
    "SQL Server",
    "MySQL / MariaDB",
    "Other SQLAlchemy URL",
]


def toast_success(message: str) -> None:
    if hasattr(st, "toast"):
        st.toast(message)
    else:
        st.success(message)


def init_session_state() -> None:
    settings = get_settings()
    initialize_connection_state()
    st.session_state.setdefault("selected_ollama_model", settings.ollama_model)
    st.session_state.setdefault("last_results", pd.DataFrame())
    st.session_state.setdefault("last_results_table", None)
    st.session_state.setdefault("last_query_plan", None)
    st.session_state.setdefault("pending_add", None)
    st.session_state.setdefault("pending_update", None)
    st.session_state.setdefault("pending_delete", None)
    st.session_state.setdefault("ai_plan", None)
    st.session_state.setdefault("prepared_full_export", None)
    st.session_state.setdefault("prepared_filtered_export", None)


def render_page_styles() -> None:
    st.markdown(f"<style>{floating_spinner_css()}</style>", unsafe_allow_html=True)


def stringify_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def render_status_bar(engine: Any) -> None:
    status = current_database_status()
    ollama_ok, ollama_message = check_ollama_health()
    table_count = 0
    try:
        table_count = len(get_table_names(engine, include_audit=True))
    except SQLAlchemyError:
        table_count = 0

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Active DB", status["name"])
    col2.metric("DB Type", status["type"])
    col3.metric("Ollama", "Online" if ollama_ok else "Offline")
    col4.metric("Tables", str(table_count))
    st.caption(f"Active URL: {status['masked_url']}")
    if not st.session_state.get("active_engine"):
        st.warning("No active database is selected. Connect to a database from the Connection Manager page.")
    if not ollama_ok:
        st.warning(ollama_message)


def render_schema_expander(engine: Any, table_name: str) -> dict[str, Any]:
    with loading_operation("Loading schema..."):
        metadata = get_table_metadata(engine, table_name)
    with st.expander("Table Schema", expanded=False):
        st.dataframe(pd.DataFrame(metadata["columns"]), use_container_width=True)
    return metadata


def render_value_input(column_info: dict[str, Any], key_prefix: str, default_value: Any = None) -> Any:
    key = f"{key_prefix}_{column_info['name']}"
    label = f"{column_info['name']} ({column_info['type']})"
    if column_info["is_boolean"]:
        return st.checkbox(label, value=bool(default_value) if default_value is not None else False, key=key)
    if column_info["is_numeric"]:
        return st.text_input(label, value=stringify_value(default_value), key=key)
    if column_info["is_datetime"]:
        return st.text_input(
            label,
            value=stringify_value(default_value),
            help="Use ISO format, for example 2026-05-22T10:30:00+00:00",
            key=key,
        )
    return st.text_input(label, value=stringify_value(default_value), key=key)


def render_record_form(
    metadata: dict[str, Any],
    key_prefix: str,
    *,
    initial_values: dict[str, Any] | None = None,
    include_advanced: bool = False,
) -> dict[str, Any]:
    values: dict[str, Any] = {}
    system_columns = {"created_at", "updated_at", "deleted_at"}
    for column_info in metadata["columns"]:
        name = column_info["name"]
        if column_info["primary_key"]:
            continue
        if not include_advanced and name in system_columns:
            continue
        values[name] = render_value_input(column_info, key_prefix, (initial_values or {}).get(name))
    return values


def render_filters_ui(metadata: dict[str, Any], key_prefix: str) -> list[dict[str, Any]]:
    filters: list[dict[str, Any]] = []
    filter_count = st.selectbox("Number of filters", options=list(range(0, 6)), index=0, key=f"{key_prefix}_count")
    column_names = metadata["column_names"]
    if not column_names:
        return filters

    operators = [
        "equals",
        "contains",
        "starts_with",
        "ends_with",
        "greater_than",
        "less_than",
        "between",
        "is_null",
        "is_not_null",
    ]
    for index in range(filter_count):
        columns = st.columns(4)
        column_name = columns[0].selectbox(f"Column {index + 1}", column_names, key=f"{key_prefix}_col_{index}")
        operator = columns[1].selectbox(f"Operator {index + 1}", operators, key=f"{key_prefix}_op_{index}")
        value: Any = None
        second_value: Any = None
        if operator not in {"is_null", "is_not_null"}:
            value = columns[2].text_input(f"Value {index + 1}", key=f"{key_prefix}_val_{index}")
        if operator == "between":
            second_value = columns[3].text_input(f"Second value {index + 1}", key=f"{key_prefix}_val2_{index}")
        filters.append(
            {
                "column": column_name,
                "operator": operator,
                "value": value,
                "second_value": second_value,
            }
        )
    return filters


def show_audit_log_warning(engine: Any, key_prefix: str, *, allow_create: bool = False) -> bool:
    try:
        exists = audit_log_exists(engine)
    except Exception:
        exists = False
    if exists:
        return True

    st.warning(
        "This database does not currently contain an audit_log table. "
        "Write operations should stay blocked until audit logging is available."
    )
    if allow_create:
        confirmed = st.checkbox(
            "I confirm that creating the audit_log table in this database is approved.",
            key=f"{key_prefix}_audit_confirm",
        )
        if st.button("Create audit_log table in this database", key=f"{key_prefix}_audit_create"):
            if not confirmed:
                st.warning("Confirmation is required before creating audit_log.")
            else:
                try:
                    with loading_operation("Creating audit log table..."):
                        create_audit_log_table(engine)
                    toast_success("audit_log table created in the active database.")
                    return True
                except Exception as exc:
                    st.error(f"Could not create audit_log table: {exc}")
    return False


def run_query_and_store(
    engine: Any,
    table_name: str,
    *,
    keyword: str = "",
    filters: list[dict[str, Any]] | None = None,
    sort_by: str | None = None,
    sort_direction: str = "asc",
    limit: int = 100,
    include_soft_deleted: bool = False,
) -> pd.DataFrame:
    statement, _ = build_select_statement(
        engine,
        table_name,
        keyword=keyword,
        filters=filters or [],
        sort_by=sort_by,
        sort_direction=sort_direction,
        limit=limit,
        include_soft_deleted=include_soft_deleted,
    )
    frame = fetch_dataframe(engine, statement)
    st.session_state["last_results"] = frame
    st.session_state["last_results_table"] = table_name
    st.session_state["last_query_plan"] = {
        "table": table_name,
        "keyword": keyword,
        "filters": filters or [],
        "sort_by": sort_by,
        "sort_direction": sort_direction,
        "limit": limit,
        "include_soft_deleted": include_soft_deleted,
    }
    return frame


def page_connection_manager() -> None:
    st.subheader("Database Login / Connection Manager")
    status = current_database_status()
    active_url = status["url"]
    active_ok, active_message = test_connection(active_url)

    with st.expander("Current Active Database", expanded=True):
        col1, col2 = st.columns(2)
        col1.write(f"Name: `{status['name']}`")
        col1.write(f"Type: `{status['type']}`")
        col2.write(f"Masked URL: `{status['masked_url']}`")
        if active_ok:
            col2.success(active_message)
        else:
            col2.error(active_message)
        show_audit_log_warning(get_active_engine(), "conn_mgr_current", allow_create=True)

    with st.expander("Select Existing Database Profile", expanded=True):
        profiles = st.session_state.get("db_profiles", [])
        if not profiles:
            st.info("No profiles available in the current session.")
        else:
            profile_labels = [
                f"{profile['name']} [{get_database_type(profile['url'])}] - {profile.get('description') or 'No description'}"
                for profile in profiles
            ]
            selected_label = st.selectbox("Predefined profiles", profile_labels, key="connection_profile_dropdown")
            selected_profile = profiles[profile_labels.index(selected_label)]
            st.caption(f"Selected URL: {mask_database_url(selected_profile['url'])}")
            if st.button("Connect to Selected Database", key="connect_selected_profile"):
                try:
                    with loading_operation("Connecting to database..."):
                        success, message = connect_profile(selected_profile, state=st.session_state)
                        if success and selected_profile["url"].startswith("sqlite:///data/app.db"):
                            ensure_demo_seed_for_sqlite(get_active_engine())
                    if success:
                        toast_success(message)
                    else:
                        st.error(message)
                except Exception as exc:
                    st.error(f"Could not switch database: {exc}")

    with st.expander("Manual Database Login", expanded=True):
        with st.form("manual_database_login_form"):
            connection_name = st.text_input("Connection name", value="Manual Connection")
            database_type = st.selectbox("Database type", MANUAL_DB_TYPES, index=0)
            add_to_profiles = st.checkbox("Add this connection to current session profiles", value=False)

            form_data: dict[str, Any] = {}
            if database_type == "SQLite":
                form_data["sqlite_path"] = st.text_input("Database file path", value="data/app.db")
            elif database_type in {"PostgreSQL", "MySQL / MariaDB"}:
                default_port = "5432" if database_type == "PostgreSQL" else "3306"
                col1, col2 = st.columns(2)
                form_data["host"] = col1.text_input("Host", value="localhost")
                form_data["port"] = col2.text_input("Port", value=default_port)
                form_data["database_name"] = st.text_input("Database name")
                col3, col4 = st.columns(2)
                form_data["username"] = col3.text_input("Username")
                form_data["password"] = col4.text_input("Password", type="password")
                form_data["ssl_mode"] = st.text_input("SSL mode (optional)", placeholder="require")
            elif database_type == "SQL Server":
                col1, col2 = st.columns(2)
                form_data["server"] = col1.text_input("Server", value=r"SERVER\MSSQLSERVER2017,1435")
                form_data["database_name"] = col2.text_input("Database name")
                col3, col4 = st.columns(2)
                form_data["username"] = col3.text_input("Username")
                form_data["password"] = col4.text_input("Password", type="password")
                col5, col6 = st.columns(2)
                form_data["connect_timeout"] = col5.text_input("Connect timeout", value="30")
                form_data["application_name"] = col6.text_input("Application name", value="Database Control Center")
                col7, col8 = st.columns(2)
                form_data["driver"] = col7.text_input("ODBC driver", value="ODBC Driver 18 for SQL Server")
                form_data["encrypt"] = col8.selectbox("Encrypt", ["yes", "mandatory", "no"], index=1)
                form_data["trust_server_certificate"] = st.checkbox("Trust server certificate", value=True)
            else:
                form_data["full_url"] = st.text_input("Full SQLAlchemy database URL", type="password")

            test_clicked = st.form_submit_button("Test Connection")
            connect_clicked = st.form_submit_button("Connect")

        if test_clicked or connect_clicked:
            try:
                profile = build_manual_profile(connection_name, database_type, form_data)
                st.caption(f"Masked URL: {mask_database_url(profile['url'])}")
                if test_clicked:
                    with loading_operation("Connecting to database..."):
                        success, message = test_connection(profile["url"])
                    if success:
                        st.success(message)
                    else:
                        st.error(message)
                if connect_clicked:
                    with loading_operation("Connecting to database..."):
                        success, message = connect_profile(
                            profile,
                            state=st.session_state,
                            add_to_session_profiles=add_to_profiles,
                        )
                    if success:
                        if profile["url"].startswith("sqlite:///data/app.db"):
                            ensure_demo_seed_for_sqlite(get_active_engine())
                        toast_success(message)
                    else:
                        st.error(message)
            except Exception as exc:
                st.error(f"Manual connection failed: {exc}")

    with st.expander("Connection Notes", expanded=False):
        st.warning("Use read-only database users when connecting to production.")
        st.warning("Do not connect directly to sensitive production databases unless permissions, backup, and approval are clear.")
        st.warning("This app blocks raw SQL execution and AI direct writes by design.")


def page_dashboard(engine: Any) -> None:
    st.subheader("Dashboard")
    try:
        table_names = get_table_names(engine, include_audit=True)
        visible_tables = get_table_names(engine, include_audit=False)
    except Exception as exc:
        st.error(f"Could not inspect the active database: {exc}")
        return

    top_left, top_right = st.columns([2, 1])
    with top_left:
        st.write("Overview")
        st.dataframe(
            pd.DataFrame(
                [
                    {"table_name": table_name, "row_count": get_table_row_count(engine, table_name)}
                    for table_name in table_names
                ]
            ),
            use_container_width=True,
        )
    with top_right:
        active_url = get_active_database_url()
        st.info(f"Database type: {get_database_type(active_url)}")
        st.write(f"Visible data tables: {len(visible_tables)}")
        st.write(f"Audit table available: {'audit_log' in table_names}")

    st.write("Recent audit activity")
    if not audit_log_exists(engine):
        st.info("The active database does not contain audit_log yet.")
        return
    audit_rows = fetch_audit_logs(engine, limit=10)
    if audit_rows:
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "created_at": item["created_at"],
                        "table_name": item["table_name"],
                        "record_id": item["record_id"],
                        "action": item["action"],
                        "actor": item["actor"],
                    }
                    for item in audit_rows
                ]
            ),
            use_container_width=True,
        )
    else:
        st.info("No audit entries yet.")


def page_data_explorer(engine: Any) -> None:
    st.subheader("Data Explorer")
    table_names = get_table_names(engine, include_audit=False)
    if not table_names:
        st.warning("No data tables found.")
        return

    selected_table = st.selectbox("Select table", table_names, key="explorer_table")
    metadata = render_schema_expander(engine, selected_table)

    ai_plan = st.session_state.get("ai_plan")
    if ai_plan and ai_plan.get("table") == selected_table:
        with st.expander("AI Query Plan Ready", expanded=False):
            st.json(ai_plan)
            if st.button("Run AI Query Plan", key="run_ai_plan"):
                try:
                    with loading_operation("Searching records..."):
                        frame = run_query_and_store(
                            engine,
                            selected_table,
                            keyword=ai_plan.get("keyword") or "",
                            filters=ai_plan.get("filters") or [],
                            sort_by=ai_plan.get("sort_by"),
                            sort_direction=ai_plan.get("sort_direction", "asc"),
                            limit=int(ai_plan.get("limit", 100)),
                        )
                    toast_success(f"Loaded {len(frame)} rows using the approved AI query plan.")
                except Exception as exc:
                    st.error(f"Failed to run the AI query plan: {exc}")

    with st.form("data_explorer_form"):
        keyword = st.text_input("Keyword search")
        filters = render_filters_ui(metadata, "explorer_filters")
        col1, col2, col3, col4 = st.columns(4)
        sort_by = col1.selectbox("Sort by", [""] + metadata["column_names"])
        sort_direction = col2.selectbox("Sort direction", ["asc", "desc"], index=0)
        limit = col3.selectbox("Limit", sorted(SAFE_LIMITS), index=1)
        include_soft_deleted = col4.checkbox("Include soft-deleted rows", value=False)
        submitted = st.form_submit_button("Search / Load Records")

    if submitted or st.session_state.get("last_results_table") != selected_table:
        try:
            with loading_operation("Searching records..."):
                frame = run_query_and_store(
                    engine,
                    selected_table,
                    keyword=keyword,
                    filters=filters,
                    sort_by=sort_by or None,
                    sort_direction=sort_direction,
                    limit=int(limit),
                    include_soft_deleted=include_soft_deleted,
                )
            toast_success(f"Loaded {len(frame)} rows from {selected_table}.")
        except Exception as exc:
            st.error(f"Failed to load records: {exc}")

    last_results = st.session_state.get("last_results", pd.DataFrame())
    if isinstance(last_results, pd.DataFrame) and st.session_state.get("last_results_table") == selected_table:
        if last_results.empty:
            st.info("The current query returned no rows.")
        else:
            st.dataframe(last_results, use_container_width=True)
    else:
        st.info("Run a search to display records.")


def page_add_record(engine: Any, actor: str) -> None:
    st.subheader("Add Record")
    table_names = get_table_names(engine, include_audit=False)
    if not table_names:
        st.warning("No data tables found.")
        return

    show_audit_log_warning(engine, "add_record_notice", allow_create=False)
    selected_table = st.selectbox("Select table", table_names, key="add_table")
    metadata = render_schema_expander(engine, selected_table)
    include_advanced = st.checkbox("Show advanced fields", value=False, key="add_advanced")

    with st.form("add_record_form"):
        form_values = render_record_form(metadata, "add_form", include_advanced=include_advanced)
        preview_clicked = st.form_submit_button("Preview New Record")

    if preview_clicked:
        try:
            payload = prepare_record_payload(
                engine,
                selected_table,
                form_values,
                include_system_fields=include_advanced,
                for_update=False,
            )
            st.session_state["pending_add"] = {"table": selected_table, "payload": payload, "advanced": include_advanced}
        except Exception as exc:
            st.error(f"Could not prepare record preview: {exc}")

    pending = st.session_state.get("pending_add")
    if pending and pending.get("table") == selected_table:
        st.write("Preview")
        st.dataframe(pd.DataFrame([pending["payload"]]), use_container_width=True)
        confirmed = st.checkbox("I confirm this insert", key="add_confirm")
        if st.button("Execute Insert", type="primary", key="add_execute"):
            if not confirmed:
                st.warning("Confirmation is required before inserting a record.")
            else:
                try:
                    with loading_operation("Saving changes..."):
                        record_id = insert_record(
                            engine,
                            selected_table,
                            pending["payload"],
                            actor=actor,
                            include_system_fields=bool(pending.get("advanced")),
                        )
                    st.session_state["pending_add"] = None
                    toast_success(f"Inserted record {record_id} into {selected_table}.")
                except Exception as exc:
                    st.error(f"Insert failed: {exc}")


def page_edit_record(engine: Any, actor: str) -> None:
    st.subheader("Edit Record")
    table_names = get_table_names(engine, include_audit=False)
    if not table_names:
        st.warning("No data tables found.")
        return

    show_audit_log_warning(engine, "edit_record_notice", allow_create=False)
    selected_table = st.selectbox("Select table", table_names, key="edit_table")
    metadata = render_schema_expander(engine, selected_table)
    primary_key = metadata["primary_key"]
    if not primary_key:
        st.warning("This table has no detectable primary key, so editing is disabled.")
        return

    options = list_record_choices(engine, selected_table)
    option_labels = [""] + [label for _, label in options]
    chosen_label = st.selectbox("Choose a record", option_labels, key="edit_record_choice")
    selected_record_id = ""
    if chosen_label:
        selected_record_id = next((record_id for record_id, label in options if label == chosen_label), "")
    manual_record_id = st.text_input(f"Or enter {primary_key} manually", value=selected_record_id, key="edit_record_id")

    record = None
    if manual_record_id:
        try:
            with loading_operation("Loading record..."):
                record = get_record_by_pk(engine, selected_table, manual_record_id)
        except Exception as exc:
            st.error(f"Could not load the record: {exc}")
    if not record:
        st.info("Select or enter a record ID to edit.")
        return

    st.write("Current Record")
    st.dataframe(pd.DataFrame([record]), use_container_width=True)
    include_advanced = st.checkbox("Show advanced fields", value=False, key="edit_advanced")

    with st.form("edit_record_form"):
        edited_values = render_record_form(
            metadata,
            "edit_form",
            initial_values=record,
            include_advanced=include_advanced,
        )
        preview_clicked = st.form_submit_button("Preview Update")

    if preview_clicked:
        try:
            payload = prepare_record_payload(
                engine,
                selected_table,
                edited_values,
                include_system_fields=include_advanced,
                for_update=True,
            )
            if primary_key in payload:
                payload.pop(primary_key)
            st.session_state["pending_update"] = {
                "table": selected_table,
                "record_id": manual_record_id,
                "payload": payload,
                "advanced": include_advanced,
            }
        except Exception as exc:
            st.error(f"Could not prepare update preview: {exc}")

    pending_update = st.session_state.get("pending_update")
    if pending_update and pending_update.get("table") == selected_table and str(pending_update.get("record_id")) == str(manual_record_id):
        st.write("Before / After Preview")
        before_after = pd.DataFrame(
            [{"field": key, "before": record.get(key), "after": pending_update["payload"].get(key)} for key in pending_update["payload"]]
        )
        st.dataframe(before_after, use_container_width=True)
        confirmed = st.checkbox("I confirm this update", key="update_confirm")
        if st.button("Execute Update", type="primary", key="update_execute"):
            if not confirmed:
                st.warning("Confirmation is required before updating a record.")
            else:
                try:
                    with loading_operation("Saving changes..."):
                        updated_rows = update_record(
                            engine,
                            selected_table,
                            record_id=manual_record_id,
                            data=pending_update["payload"],
                            actor=actor,
                            include_system_fields=bool(pending_update.get("advanced")),
                        )
                    st.session_state["pending_update"] = None
                    toast_success(f"Updated {updated_rows} record(s) in {selected_table}.")
                except Exception as exc:
                    st.error(f"Update failed: {exc}")

    st.divider()
    st.write("Soft Delete")
    if metadata["has_deleted_at"]:
        delete_confirm = st.checkbox("I confirm this soft delete", key="delete_confirm")
        if st.button("Soft Delete Record", key="soft_delete_button"):
            if not delete_confirm:
                st.warning("Confirmation is required before soft deleting a record.")
            else:
                try:
                    with loading_operation("Saving changes..."):
                        affected = soft_delete_record(engine, selected_table, record_id=manual_record_id, actor=actor)
                    toast_success(f"Soft deleted {affected} record(s) in {selected_table}.")
                except Exception as exc:
                    st.error(f"Soft delete failed: {exc}")
    else:
        st.warning("This table does not have a deleted_at column, so hard delete is intentionally blocked.")


def page_import_export(engine: Any, actor: str) -> None:
    st.subheader("Import / Export")
    table_names = get_table_names(engine, include_audit=False)
    if not table_names:
        st.warning("No data tables found.")
        return

    show_audit_log_warning(engine, "import_export_notice", allow_create=False)
    selected_table = st.selectbox("Select table", table_names, key="import_export_table")
    metadata = render_schema_expander(engine, selected_table)

    export_col1, export_col2 = st.columns(2)
    if export_col1.button("Prepare Full Table Export", key="prepare_full_export"):
        try:
            with loading_operation("Exporting data..."):
                full_table = export_table_to_dataframe(engine, selected_table)
            st.session_state["prepared_full_export"] = {
                "table": selected_table,
                "csv": dataframe_to_csv_bytes(full_table),
                "excel": dataframe_to_excel_bytes(full_table),
            }
            toast_success(f"Prepared full-table export for {selected_table}.")
        except Exception as exc:
            st.error(f"Could not prepare full-table export: {exc}")

    prepared_full_export = st.session_state.get("prepared_full_export")
    if prepared_full_export and prepared_full_export.get("table") == selected_table:
        full_col1, full_col2 = st.columns(2)
        full_col1.download_button(
            "Download Full Table CSV",
            prepared_full_export["csv"],
            file_name=f"{selected_table}_full.csv",
            mime="text/csv",
        )
        full_col2.download_button(
            "Download Full Table Excel",
            prepared_full_export["excel"],
            file_name=f"{selected_table}_full.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    last_results = st.session_state.get("last_results", pd.DataFrame())
    if isinstance(last_results, pd.DataFrame) and not last_results.empty and st.session_state.get("last_results_table") == selected_table:
        if export_col2.button("Prepare Filtered Result Export", key="prepare_filtered_export"):
            try:
                with loading_operation("Exporting data..."):
                    st.session_state["prepared_filtered_export"] = {
                        "table": selected_table,
                        "csv": dataframe_to_csv_bytes(last_results),
                        "excel": dataframe_to_excel_bytes(last_results),
                    }
                toast_success(f"Prepared filtered export for {selected_table}.")
            except Exception as exc:
                st.error(f"Could not prepare filtered export: {exc}")
        prepared_filtered_export = st.session_state.get("prepared_filtered_export")
        if prepared_filtered_export and prepared_filtered_export.get("table") == selected_table:
            filtered_col1, filtered_col2 = st.columns(2)
            filtered_col1.download_button(
                "Download Filtered CSV",
                prepared_filtered_export["csv"],
                file_name=f"{selected_table}_filtered.csv",
                mime="text/csv",
            )
            filtered_col2.download_button(
                "Download Filtered Excel",
                prepared_filtered_export["excel"],
                file_name=f"{selected_table}_filtered.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )

    st.divider()
    st.write("Import CSV")
    uploaded_file = st.file_uploader("Upload CSV file", type=["csv"])
    if uploaded_file is None:
        return

    try:
        import_frame = pd.read_csv(uploaded_file)
        st.dataframe(import_frame.head(20), use_container_width=True)
        missing_columns = [column for column in import_frame.columns if column not in metadata["column_names"]]
        required_columns = [
            column_info["name"]
            for column_info in metadata["columns"]
            if not column_info["nullable"]
            and not column_info["primary_key"]
            and column_info["name"] not in {"created_at", "updated_at", "deleted_at"}
        ]
        missing_required = [column for column in required_columns if column not in import_frame.columns]
        if missing_columns:
            st.error(f"These CSV columns do not exist in the table: {', '.join(missing_columns)}")
            return
        if missing_required:
            st.error(f"These required table columns are missing from the CSV: {', '.join(missing_required)}")
            return

        confirm_import = st.checkbox("I confirm this bulk import", key="import_confirm")
        if st.button("Execute Bulk Import", type="primary", key="import_execute"):
            if not confirm_import:
                st.warning("Confirmation is required before importing records.")
            else:
                with loading_operation("Saving changes..."):
                    inserted_count = bulk_import_records(
                        engine,
                        selected_table,
                        import_frame.to_dict(orient="records"),
                        actor=actor,
                        include_system_fields=False,
                    )
                toast_success(f"Imported {inserted_count} rows into {selected_table}.")
    except Exception as exc:
        st.error(f"Import failed: {exc}")


def page_ai_assistant(engine: Any) -> None:
    st.subheader("AI Assistant")
    ollama_ok, ollama_message = check_ollama_health()
    if not ollama_ok:
        st.error(ollama_message)
        st.info("Install Ollama, run `ollama pull llama3.2`, run `ollama serve`, and then restart the Streamlit app.")
        return

    table_names = get_table_names(engine, include_audit=False)
    if not table_names:
        st.warning("No data tables found.")
        return

    selected_table = st.selectbox("Select table for AI context", table_names, key="ai_table")
    active_database_name = get_active_database_name()
    metadata = get_table_metadata(engine, selected_table)
    current_model = st.session_state["selected_ollama_model"]

    sample_frame = st.session_state.get("last_results", pd.DataFrame())
    if not isinstance(sample_frame, pd.DataFrame) or st.session_state.get("last_results_table") != selected_table:
        sample_frame = pd.DataFrame()
    if sample_frame.empty:
        try:
            with loading_operation("Loading schema..."):
                sample_frame = run_query_and_store(engine, selected_table, limit=50)
        except Exception as exc:
            st.error(f"Could not load sample rows for AI context: {exc}")
            return

    sample_rows = sample_frame.head(10).to_dict(orient="records")
    schema_summary = {
        "database_name": active_database_name,
        "table_name": metadata["table_name"],
        "columns": metadata["columns"],
        "primary_key": metadata["primary_key"],
    }

    schema_tab, summary_tab, plan_tab, anomaly_tab, report_tab = st.tabs(
        ["Schema", "Summary", "Safe Query Plan", "Anomalies", "Report"]
    )

    with schema_tab:
        if st.button("Explain Table Schema", key="ai_explain_schema"):
            try:
                with loading_operation("Asking local AI..."):
                    explanation = explain_schema(selected_table, schema_summary, model=current_model)
                st.write(explanation)
            except Exception as exc:
                st.error(f"AI schema explanation failed: {exc}")
        if st.button("Explain Current Data Sample", key="ai_explain_sample"):
            try:
                with loading_operation("Asking local AI..."):
                    explanation = explain_data_sample(
                        selected_table,
                        sample_rows,
                        model=current_model,
                        database_name=active_database_name,
                    )
                st.write(explanation)
            except Exception as exc:
                st.error(f"AI sample explanation failed: {exc}")

    with summary_tab:
        if st.button("Summarize Filtered Data", key="ai_summarize"):
            try:
                with loading_operation("Asking local AI..."):
                    summary = summarize_dataframe(
                        selected_table,
                        sample_frame,
                        model=current_model,
                        database_name=active_database_name,
                    )
                st.write(summary)
            except Exception as exc:
                st.error(f"AI summary failed: {exc}")

    with plan_tab:
        natural_language_request = st.text_area(
            "Describe the search or filter you want",
            placeholder="Example: Show active customers from Makassar sorted by newest created date",
        )
        if st.button("Generate Safe Query Plan", key="ai_generate_plan"):
            if not natural_language_request.strip():
                st.warning("Enter a request first.")
            else:
                try:
                    with loading_operation("Asking local AI..."):
                        plan = request_safe_query_plan(
                            natural_language_request,
                            database_name=active_database_name,
                            table_name=selected_table,
                            schema_summary=schema_summary,
                            allowed_tables=[selected_table],
                            allowed_columns=metadata["column_names"],
                            model=current_model,
                        )
                    st.session_state["ai_plan"] = plan
                    st.success("Approved JSON query plan generated. Open Data Explorer to run it.")
                    st.json(plan)
                except Exception as exc:
                    st.error(f"AI query plan failed validation: {exc}")

    with anomaly_tab:
        if st.button("Detect Possible Anomalies", key="ai_anomalies"):
            try:
                with loading_operation("Asking local AI..."):
                    result = detect_anomalies(
                        selected_table,
                        sample_frame,
                        model=current_model,
                        database_name=active_database_name,
                    )
                st.write(result)
            except Exception as exc:
                st.error(f"AI anomaly review failed: {exc}")

    with report_tab:
        if st.button("Draft Internal Report", key="ai_report"):
            try:
                with loading_operation("Asking local AI..."):
                    result = draft_report(
                        selected_table,
                        sample_frame,
                        model=current_model,
                        database_name=active_database_name,
                    )
                st.write(result)
            except Exception as exc:
                st.error(f"AI report drafting failed: {exc}")

    with st.expander("AI Safety Notes", expanded=False):
        st.write("- AI only receives the active database display name, table name, schema, and sample data.")
        st.write("- AI never receives database credentials.")
        st.write("- AI never executes SQL.")
        st.write("- AI-generated write suggestions still require the normal UI workflow.")


def page_audit_log(engine: Any) -> None:
    st.subheader("Audit Log")
    if not show_audit_log_warning(engine, "audit_page", allow_create=True):
        if not audit_log_exists(engine):
            return

    with st.form("audit_filter_form"):
        table_filter = st.text_input("Table name")
        action_filter = st.text_input("Action")
        actor_filter = st.text_input("Actor")
        col1, col2 = st.columns(2)
        start_date_text = col1.text_input("Start date (ISO)", placeholder="2026-05-01")
        end_date_text = col2.text_input("End date (ISO)", placeholder="2026-05-31")
        submitted = st.form_submit_button("Load Audit Log")

    if submitted or True:
        try:
            start_date = date.fromisoformat(start_date_text) if start_date_text.strip() else None
            end_date = date.fromisoformat(end_date_text) if end_date_text.strip() else None
            with loading_operation("Loading audit log..."):
                rows = fetch_audit_logs(
                    engine,
                    table_name=table_filter or None,
                    action=action_filter or None,
                    actor=actor_filter or None,
                    start_date=start_date,
                    end_date=end_date,
                    limit=500,
                )
            if not rows:
                st.info("No audit rows matched the current filters.")
                return
            frame = pd.DataFrame(
                [
                    {
                        "created_at": item["created_at"],
                        "table_name": item["table_name"],
                        "record_id": item["record_id"],
                        "action": item["action"],
                        "actor": item["actor"],
                    }
                    for item in rows
                ]
            )
            st.dataframe(frame, use_container_width=True)
            st.download_button(
                "Export Audit Log CSV",
                dataframe_to_csv_bytes(frame),
                file_name="audit_log.csv",
                mime="text/csv",
            )
            for item in rows[:50]:
                with st.expander(f"{item['created_at']} | {item['table_name']} | {item['action']} | {item['record_id']}"):
                    st.write("Before Data")
                    st.json(item["before_data_json"] or {})
                    st.write("After Data")
                    st.json(item["after_data_json"] or {})
        except Exception as exc:
            st.error(f"Could not load the audit log: {exc}")


def page_settings(engine: Any) -> None:
    st.subheader("Settings / Health Check")
    active_url = get_active_database_url()
    st.write(f"Masked active database URL: `{mask_database_url(active_url)}`")

    db_ok, db_message = test_connection(active_url)
    if db_ok:
        st.success(db_message)
    else:
        st.error(db_message)

    ollama_ok, ollama_message = check_ollama_health()
    if ollama_ok:
        st.success(ollama_message)
        try:
            models = list_models()
        except Exception as exc:
            models = []
            st.warning(f"Could not load model list: {exc}")
    else:
        models = []
        st.error(ollama_message)

    st.write("Available Ollama models")
    if models:
        st.write(models)
    else:
        st.info("No model list available.")

    new_model = st.text_input("Selected Ollama model", value=st.session_state["selected_ollama_model"])
    if st.button("Save Model Selection", key="save_model"):
        st.session_state["selected_ollama_model"] = new_model.strip() or "llama3.2"
        toast_success(f"Selected model set to {st.session_state['selected_ollama_model']}.")

    st.divider()
    if db_ok:
        show_audit_log_warning(engine, "settings_page", allow_create=True)
    else:
        st.info("Audit log availability is not checked because the active database connection is currently failing.")

    if not ollama_ok:
        st.info("Install Ollama")
        st.code("ollama pull llama3.2")
        st.code("ollama serve")
        st.write("Restart the Streamlit app after Ollama is running.")


def main() -> None:
    init_session_state()
    render_page_styles()
    settings = get_settings()
    engine = get_active_engine()

    try:
        if get_active_database_url().startswith("sqlite:///data/app.db"):
            ensure_demo_seed_for_sqlite(engine)
    except Exception as exc:
        st.warning(f"Demo seed check skipped: {exc}")

    st.title("Database Control Center")
    render_status_bar(engine)

    with st.sidebar:
        st.header("Navigation")
        page = st.radio("Go to", PAGE_OPTIONS)

    if page == "Database Login / Connection Manager":
        page_connection_manager()
    elif page == "Dashboard":
        page_dashboard(engine)
    elif page == "Data Explorer":
        page_data_explorer(engine)
    elif page == "Add Record":
        page_add_record(engine, settings.app_actor)
    elif page == "Edit Record":
        page_edit_record(engine, settings.app_actor)
    elif page == "Import / Export":
        page_import_export(engine, settings.app_actor)
    elif page == "AI Assistant":
        page_ai_assistant(engine)
    elif page == "Audit Log":
        page_audit_log(engine)
    elif page == "Settings / Health Check":
        page_settings(engine)


if __name__ == "__main__":
    main()
