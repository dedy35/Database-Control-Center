from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd
from PySide6.QtCore import QAbstractTableModel, QDate, QModelIndex, Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QTableView,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
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
from src.connection_manager import ConnectionManager, build_manual_profile
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
from src.loading_ui import loading_operation
from src.ollama_client import check_ollama_health, list_models
from src.query_builder import SAFE_LIMITS, build_select_statement, fetch_dataframe
from src.schema_inspector import get_table_metadata, get_table_names, get_table_row_count


PAGE_TITLES = [
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

FILTER_OPERATORS = [
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


def stringify_value(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


class PandasTableModel(QAbstractTableModel):
    def __init__(self, frame: pd.DataFrame | None = None) -> None:
        super().__init__()
        self._frame = frame if frame is not None else pd.DataFrame()

    def set_frame(self, frame: pd.DataFrame) -> None:
        self.beginResetModel()
        self._frame = frame.copy()
        self.endResetModel()

    def dataframe(self) -> pd.DataFrame:
        return self._frame.copy()

    def rowCount(self, parent: QModelIndex | None = None) -> int:
        if parent and parent.isValid():
            return 0
        return len(self._frame.index)

    def columnCount(self, parent: QModelIndex | None = None) -> int:
        if parent and parent.isValid():
            return 0
        return len(self._frame.columns)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> Any:
        if not index.isValid() or role not in {Qt.DisplayRole, Qt.ToolTipRole}:
            return None
        value = self._frame.iat[index.row(), index.column()]
        if pd.isna(value):
            return ""
        return str(value)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole) -> Any:
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal and 0 <= section < len(self._frame.columns):
            return str(self._frame.columns[section])
        if orientation == Qt.Vertical:
            return str(section + 1)
        return None


class DataFrameView(QTableView):
    def __init__(self) -> None:
        super().__init__()
        self._model = PandasTableModel()
        self.setModel(self._model)
        self.setSortingEnabled(False)
        self.setAlternatingRowColors(True)
        self.setSelectionBehavior(QTableView.SelectRows)
        self.setSelectionMode(QTableView.SingleSelection)
        self.horizontalHeader().setStretchLastSection(True)
        self.verticalHeader().setVisible(False)

    def set_frame(self, frame: pd.DataFrame) -> None:
        self._model.set_frame(frame)

    def dataframe(self) -> pd.DataFrame:
        return self._model.dataframe()


class FilterRowWidget(QWidget):
    def __init__(self, columns: list[str], remove_callback) -> None:
        super().__init__()
        self.column_combo = QComboBox()
        self.column_combo.addItems(columns)
        self.operator_combo = QComboBox()
        self.operator_combo.addItems(FILTER_OPERATORS)
        self.value_edit = QLineEdit()
        self.value_edit.setPlaceholderText("Value")
        self.second_value_edit = QLineEdit()
        self.second_value_edit.setPlaceholderText("Second value")
        self.remove_button = QToolButton()
        self.remove_button.setText("Remove")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.column_combo, 2)
        layout.addWidget(self.operator_combo, 2)
        layout.addWidget(self.value_edit, 2)
        layout.addWidget(self.second_value_edit, 2)
        layout.addWidget(self.remove_button, 1)

        self.operator_combo.currentTextChanged.connect(self._sync_visibility)
        self.remove_button.clicked.connect(lambda: remove_callback(self))
        self._sync_visibility(self.operator_combo.currentText())

    def _sync_visibility(self, operator: str) -> None:
        needs_value = operator not in {"is_null", "is_not_null"}
        needs_second = operator == "between"
        self.value_edit.setVisible(needs_value)
        self.second_value_edit.setVisible(needs_second)

    def to_filter(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "column": self.column_combo.currentText(),
            "operator": self.operator_combo.currentText(),
        }
        if payload["operator"] not in {"is_null", "is_not_null"}:
            payload["value"] = self.value_edit.text().strip()
        if payload["operator"] == "between":
            payload["second_value"] = self.second_value_edit.text().strip()
        return payload

    def apply_filter(self, payload: dict[str, Any]) -> None:
        column = str(payload.get("column") or "")
        operator = str(payload.get("operator") or "equals")
        if column:
            index = self.column_combo.findText(column)
            if index >= 0:
                self.column_combo.setCurrentIndex(index)
        index = self.operator_combo.findText(operator)
        if index >= 0:
            self.operator_combo.setCurrentIndex(index)
        self.value_edit.setText(str(payload.get("value") or ""))
        self.second_value_edit.setText(str(payload.get("second_value") or ""))


class DynamicFormWidget(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.form_layout = QFormLayout(self)
        self.form_layout.setContentsMargins(0, 0, 0, 0)
        self._widgets: dict[str, QWidget] = {}
        self._columns: list[dict[str, Any]] = []

    def set_metadata(
        self,
        metadata: dict[str, Any] | None,
        *,
        initial_values: dict[str, Any] | None = None,
        include_advanced: bool = False,
        include_primary_key: bool = False,
    ) -> None:
        self.clear()
        self._columns = []
        if not metadata:
            return

        system_columns = {"created_at", "updated_at", "deleted_at"}
        for column in metadata.get("columns", []):
            column_name = column["name"]
            if not include_primary_key and column.get("primary_key"):
                continue
            if not include_advanced and column_name in system_columns:
                continue

            if column.get("is_boolean"):
                widget: QWidget = QCheckBox()
                if initial_values and column_name in initial_values:
                    widget.setChecked(bool(initial_values[column_name]))
            else:
                widget = QLineEdit()
                widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
                if initial_values and column_name in initial_values:
                    widget.setText(stringify_value(initial_values[column_name]))
                if column.get("is_datetime"):
                    widget.setToolTip("Use ISO format, for example 2026-05-22T10:30:00+00:00")

            self.form_layout.addRow(f"{column_name} ({column['type']})", widget)
            self._widgets[column_name] = widget
            self._columns.append(column)

    def clear(self) -> None:
        while self.form_layout.count():
            item = self.form_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._widgets = {}
        self._columns = []

    def values(self) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        for column in self._columns:
            widget = self._widgets[column["name"]]
            if isinstance(widget, QCheckBox):
                payload[column["name"]] = widget.isChecked()
            elif isinstance(widget, QLineEdit):
                payload[column["name"]] = widget.text().strip()
        return payload


class BasePage(QWidget):
    def __init__(self, window: "MainWindow") -> None:
        super().__init__()
        self.window = window

    def on_database_changed(self) -> None:
        return None

    def on_activated(self) -> None:
        return None


class ConnectionManagerPage(BasePage):
    def __init__(self, window: "MainWindow") -> None:
        super().__init__(window)
        self.profile_lookup: list[dict[str, str]] = []

        layout = QVBoxLayout(self)

        current_group = QGroupBox("Current active database")
        current_layout = QFormLayout(current_group)
        self.current_name = QLabel("-")
        self.current_type = QLabel("-")
        self.current_url = QLabel("-")
        self.current_status = QLabel("-")
        self.current_url.setWordWrap(True)
        current_layout.addRow("Name", self.current_name)
        current_layout.addRow("Type", self.current_type)
        current_layout.addRow("Masked URL", self.current_url)
        current_layout.addRow("Connection Status", self.current_status)
        layout.addWidget(current_group)

        profile_group = QGroupBox("Select existing database profile")
        profile_layout = QHBoxLayout(profile_group)
        self.profile_combo = QComboBox()
        self.connect_profile_button = QPushButton("Connect to Selected Database")
        profile_layout.addWidget(self.profile_combo, 3)
        profile_layout.addWidget(self.connect_profile_button, 1)
        layout.addWidget(profile_group)

        manual_group = QGroupBox("Manual database login")
        manual_layout = QVBoxLayout(manual_group)
        form = QFormLayout()
        self.connection_name = QLineEdit("Manual Connection")
        self.database_type_combo = QComboBox()
        self.database_type_combo.addItems(MANUAL_DB_TYPES)
        self.sqlite_path_edit = QLineEdit("data/app.db")
        self.host_edit = QLineEdit("localhost")
        self.port_edit = QLineEdit("5432")
        self.server_edit = QLineEdit(r"SERVER\MSSQLSERVER2017,1435")
        self.database_name_edit = QLineEdit()
        self.username_edit = QLineEdit()
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.Password)
        self.ssl_mode_edit = QLineEdit()
        self.encrypt_combo = QComboBox()
        self.encrypt_combo.addItems(["Mandatory", "Yes", "No"])
        self.trust_cert_checkbox = QCheckBox()
        self.trust_cert_checkbox.setChecked(True)
        self.timeout_spin = QSpinBox()
        self.timeout_spin.setRange(1, 600)
        self.timeout_spin.setValue(30)
        self.driver_edit = QLineEdit("ODBC Driver 18 for SQL Server")
        self.application_name_edit = QLineEdit("Database Control Center")
        self.full_url_edit = QLineEdit()
        self.add_session_checkbox = QCheckBox("Add this connection to current session profiles")

        self.manual_rows: dict[str, tuple[str, QWidget]] = {
            "connection_name": ("Connection name", self.connection_name),
            "database_type": ("Database type", self.database_type_combo),
            "sqlite_path": ("SQLite database file path", self.sqlite_path_edit),
            "host": ("Host", self.host_edit),
            "port": ("Port", self.port_edit),
            "server": ("Server", self.server_edit),
            "database_name": ("Database name", self.database_name_edit),
            "username": ("Username", self.username_edit),
            "password": ("Password", self.password_edit),
            "ssl_mode": ("SSL mode (optional)", self.ssl_mode_edit),
            "encrypt": ("Encrypt", self.encrypt_combo),
            "trust_cert": ("Trust server certificate", self.trust_cert_checkbox),
            "timeout": ("Connect timeout", self.timeout_spin),
            "driver": ("ODBC driver", self.driver_edit),
            "application_name": ("Application name", self.application_name_edit),
            "full_url": ("Full SQLAlchemy URL", self.full_url_edit),
        }
        for label, widget in self.manual_rows.values():
            form.addRow(label, widget)
        manual_layout.addLayout(form)
        manual_layout.addWidget(self.add_session_checkbox)

        actions = QHBoxLayout()
        self.test_manual_button = QPushButton("Test Connection")
        self.connect_manual_button = QPushButton("Connect")
        actions.addWidget(self.test_manual_button)
        actions.addWidget(self.connect_manual_button)
        actions.addStretch(1)
        manual_layout.addLayout(actions)
        layout.addWidget(manual_group)

        notes = QGroupBox("Connection notes")
        notes_layout = QVBoxLayout(notes)
        notes_label = QLabel(
            "Use read-only database users when connecting to production.\n"
            "Do not connect directly to sensitive production databases unless permissions, backup, and approval are clear.\n"
            "This application blocks raw SQL execution and AI direct writes by design."
        )
        notes_label.setWordWrap(True)
        notes_layout.addWidget(notes_label)
        layout.addWidget(notes)
        layout.addStretch(1)

        self.connect_profile_button.clicked.connect(self._connect_selected_profile)
        self.test_manual_button.clicked.connect(self._test_manual_connection)
        self.connect_manual_button.clicked.connect(self._connect_manual_profile)
        self.database_type_combo.currentTextChanged.connect(self._sync_manual_type_visibility)

        self.refresh_profiles()
        self.refresh_status()
        self._sync_manual_type_visibility(self.database_type_combo.currentText())

    def on_database_changed(self) -> None:
        self.refresh_profiles()
        self.refresh_status()

    def on_activated(self) -> None:
        self.refresh_profiles()
        self.refresh_status()

    def refresh_profiles(self) -> None:
        self.profile_lookup = self.window.manager.get_profiles()
        self.profile_combo.clear()
        for profile in self.profile_lookup:
            self.profile_combo.addItem(profile["name"])

    def refresh_status(self) -> None:
        status = self.window.manager.current_database_status()
        success, message = test_connection(status["url"])
        self.current_name.setText(status["name"])
        self.current_type.setText(status["type"])
        self.current_url.setText(status["masked_url"])
        self.current_status.setText("Connected" if success else message)

    def _sync_manual_type_visibility(self, selected: str) -> None:
        selected = selected.lower()
        visibility = {
            "sqlite_path": selected == "sqlite",
            "host": selected in {"postgresql", "mysql / mariadb"},
            "port": selected in {"postgresql", "mysql / mariadb"},
            "server": selected == "sql server",
            "database_name": selected in {"postgresql", "mysql / mariadb", "sql server"},
            "username": selected in {"postgresql", "mysql / mariadb", "sql server"},
            "password": selected in {"postgresql", "mysql / mariadb", "sql server"},
            "ssl_mode": selected in {"postgresql", "mysql / mariadb"},
            "encrypt": selected == "sql server",
            "trust_cert": selected == "sql server",
            "timeout": selected == "sql server",
            "driver": selected == "sql server",
            "application_name": selected == "sql server",
            "full_url": selected == "other sqlalchemy url",
        }
        for key, (_, widget) in self.manual_rows.items():
            if key in {"connection_name", "database_type"}:
                widget.parentWidget()
                continue
            row_label = self.manual_rows[key][0]
            should_show = visibility.get(key, False)
            widget.setVisible(should_show)
            label_widget = self._label_for_row(row_label)
            if label_widget is not None:
                label_widget.setVisible(should_show)

    def _label_for_row(self, text: str) -> QLabel | None:
        for index in range(self.layout().count()):
            item = self.layout().itemAt(index)
            widget = item.widget()
            if isinstance(widget, QGroupBox) and widget.title() == "Manual database login":
                form_layout = widget.layout().itemAt(0).layout()
                if isinstance(form_layout, QFormLayout):
                    for row in range(form_layout.rowCount()):
                        label_item = form_layout.itemAt(row, QFormLayout.LabelRole)
                        field_item = form_layout.itemAt(row, QFormLayout.FieldRole)
                        if label_item and field_item and label_item.widget() and label_item.widget().text() == text:
                            return label_item.widget()  # type: ignore[return-value]
        return None

    def _manual_form_data(self) -> dict[str, Any]:
        selected = self.database_type_combo.currentText().lower()
        if selected == "sqlite":
            return {"sqlite_path": self.sqlite_path_edit.text().strip()}
        if selected in {"postgresql", "mysql / mariadb"}:
            return {
                "host": self.host_edit.text().strip(),
                "port": self.port_edit.text().strip(),
                "database_name": self.database_name_edit.text().strip(),
                "username": self.username_edit.text().strip(),
                "password": self.password_edit.text(),
                "ssl_mode": self.ssl_mode_edit.text().strip(),
            }
        if selected == "sql server":
            return {
                "server": self.server_edit.text().strip(),
                "database_name": self.database_name_edit.text().strip(),
                "username": self.username_edit.text().strip(),
                "password": self.password_edit.text(),
                "encrypt": self.encrypt_combo.currentText(),
                "trust_server_certificate": self.trust_cert_checkbox.isChecked(),
                "connect_timeout": self.timeout_spin.value(),
                "application_name": self.application_name_edit.text().strip(),
                "driver": self.driver_edit.text().strip(),
            }
        return {"full_url": self.full_url_edit.text().strip()}

    def _selected_manual_profile(self) -> dict[str, str]:
        return build_manual_profile(
            self.connection_name.text().strip() or "Manual Connection",
            self.database_type_combo.currentText(),
            self._manual_form_data(),
        )

    def _test_manual_connection(self) -> None:
        try:
            profile = self._selected_manual_profile()
        except Exception as exc:
            self.window.show_error("Manual connection", exc)
            return
        with loading_operation("Testing database connection...", self.window):
            success, message = test_connection(profile["url"])
        if success:
            self.window.show_info("Manual connection", f"{message}\n\nMasked URL:\n{mask_database_url(profile['url'])}")
        else:
            self.window.show_warning("Manual connection", message)

    def _connect_manual_profile(self) -> None:
        try:
            profile = self._selected_manual_profile()
        except Exception as exc:
            self.window.show_error("Manual connection", exc)
            return
        self.window.connect_to_profile(profile, add_to_session_profiles=self.add_session_checkbox.isChecked())

    def _connect_selected_profile(self) -> None:
        index = self.profile_combo.currentIndex()
        if index < 0 or index >= len(self.profile_lookup):
            self.window.show_warning("Database connection", "No profile is selected.")
            return
        self.window.connect_to_profile(self.profile_lookup[index], add_to_session_profiles=False)


class DashboardPage(BasePage):
    def __init__(self, window: "MainWindow") -> None:
        super().__init__(window)
        layout = QVBoxLayout(self)
        self.summary_label = QLabel()
        self.summary_label.setWordWrap(True)
        layout.addWidget(self.summary_label)

        self.row_counts = DataFrameView()
        row_group = QGroupBox("Row count per table")
        row_layout = QVBoxLayout(row_group)
        row_layout.addWidget(self.row_counts)
        layout.addWidget(row_group, 2)

        self.audit_table = DataFrameView()
        audit_group = QGroupBox("Recent audit actions")
        audit_layout = QVBoxLayout(audit_group)
        audit_layout.addWidget(self.audit_table)
        layout.addWidget(audit_group, 2)

    def on_database_changed(self) -> None:
        self.refresh_dashboard()

    def on_activated(self) -> None:
        self.refresh_dashboard()

    def refresh_dashboard(self) -> None:
        status = self.window.manager.current_database_status()
        success, message = test_connection(status["url"])
        ollama_ok, ollama_message = check_ollama_health()
        self.summary_label.setText(
            f"Active DB: {status['name']}\n"
            f"Database type: {status['type']}\n"
            f"Connection: {'Connected' if success else message}\n"
            f"Ollama: {'Online' if ollama_ok else ollama_message}"
        )
        if not success:
            self.row_counts.set_frame(pd.DataFrame())
            self.audit_table.set_frame(pd.DataFrame())
            return

        engine = self.window.active_engine()
        rows: list[dict[str, Any]] = []
        try:
            with loading_operation("Loading dashboard data...", self.window):
                for table_name in get_table_names(engine, include_audit=True):
                    rows.append({"table_name": table_name, "row_count": get_table_row_count(engine, table_name)})
                audits = fetch_audit_logs(engine, limit=25)
        except Exception as exc:
            self.window.show_error("Dashboard", exc)
            return

        self.row_counts.set_frame(pd.DataFrame(rows))
        audit_frame = pd.DataFrame(audits)
        if not audit_frame.empty:
            for column in ("before_data_json", "after_data_json"):
                if column in audit_frame.columns:
                    audit_frame[column] = audit_frame[column].apply(lambda value: json.dumps(value, ensure_ascii=False, default=str))
        self.audit_table.set_frame(audit_frame)


class DataExplorerPage(BasePage):
    def __init__(self, window: "MainWindow") -> None:
        super().__init__(window)
        self.metadata: dict[str, Any] | None = None
        self.filter_rows: list[FilterRowWidget] = []

        layout = QVBoxLayout(self)
        controls = QGridLayout()
        self.table_combo = QComboBox()
        self.keyword_edit = QLineEdit()
        self.keyword_edit.setPlaceholderText("Keyword search across text columns")
        self.limit_combo = QComboBox()
        self.limit_combo.addItems([str(value) for value in sorted(SAFE_LIMITS)])
        self.limit_combo.setCurrentText("100")
        self.sort_combo = QComboBox()
        self.direction_combo = QComboBox()
        self.direction_combo.addItems(["asc", "desc"])
        self.include_deleted_checkbox = QCheckBox("Include soft-deleted rows")
        self.search_button = QPushButton("Search")
        self.export_csv_button = QPushButton("Export CSV")
        self.export_excel_button = QPushButton("Export Excel")
        self.clear_filters_button = QPushButton("Reset Filters")

        controls.addWidget(QLabel("Table"), 0, 0)
        controls.addWidget(self.table_combo, 0, 1)
        controls.addWidget(QLabel("Keyword"), 0, 2)
        controls.addWidget(self.keyword_edit, 0, 3)
        controls.addWidget(QLabel("Limit"), 1, 0)
        controls.addWidget(self.limit_combo, 1, 1)
        controls.addWidget(QLabel("Sort by"), 1, 2)
        controls.addWidget(self.sort_combo, 1, 3)
        controls.addWidget(QLabel("Direction"), 2, 0)
        controls.addWidget(self.direction_combo, 2, 1)
        controls.addWidget(self.include_deleted_checkbox, 2, 2, 1, 2)
        controls.addWidget(self.search_button, 3, 0)
        controls.addWidget(self.export_csv_button, 3, 1)
        controls.addWidget(self.export_excel_button, 3, 2)
        controls.addWidget(self.clear_filters_button, 3, 3)
        layout.addLayout(controls)

        filter_group = QGroupBox("Filters")
        filter_layout = QVBoxLayout(filter_group)
        self.filter_container = QVBoxLayout()
        filter_actions = QHBoxLayout()
        self.add_filter_button = QPushButton("Add Filter")
        filter_actions.addWidget(self.add_filter_button)
        filter_actions.addStretch(1)
        filter_layout.addLayout(self.filter_container)
        filter_layout.addLayout(filter_actions)
        layout.addWidget(filter_group)

        splitter = QSplitter(Qt.Vertical)
        self.schema_view = DataFrameView()
        self.results_view = DataFrameView()

        schema_group = QGroupBox("Schema")
        schema_layout = QVBoxLayout(schema_group)
        schema_layout.addWidget(self.schema_view)

        result_group = QGroupBox("Results")
        result_layout = QVBoxLayout(result_group)
        result_layout.addWidget(self.results_view)

        splitter.addWidget(schema_group)
        splitter.addWidget(result_group)
        splitter.setSizes([220, 520])
        layout.addWidget(splitter, 1)

        self.add_filter_button.clicked.connect(self.add_filter_row)
        self.clear_filters_button.clicked.connect(self.reset_filters)
        self.search_button.clicked.connect(self.search)
        self.export_csv_button.clicked.connect(self.export_csv)
        self.export_excel_button.clicked.connect(self.export_excel)
        self.table_combo.currentTextChanged.connect(self._table_changed)

    def on_database_changed(self) -> None:
        self.refresh_tables()
        self.results_view.set_frame(pd.DataFrame())
        self.schema_view.set_frame(pd.DataFrame())

    def on_activated(self) -> None:
        self.refresh_tables()

    def refresh_tables(self) -> None:
        self.table_combo.blockSignals(True)
        current = self.table_combo.currentText()
        self.table_combo.clear()
        for table_name in self.window.get_available_tables():
            self.table_combo.addItem(table_name)
        index = self.table_combo.findText(current)
        if index >= 0:
            self.table_combo.setCurrentIndex(index)
        self.table_combo.blockSignals(False)
        if self.table_combo.count() > 0:
            self._table_changed(self.table_combo.currentText())

    def _table_changed(self, table_name: str) -> None:
        if not table_name:
            self.metadata = None
            self.sort_combo.clear()
            self.schema_view.set_frame(pd.DataFrame())
            return
        try:
            with loading_operation("Loading schema...", self.window):
                self.metadata = get_table_metadata(self.window.active_engine(), table_name)
        except Exception as exc:
            self.window.show_error("Schema", exc)
            self.metadata = None
            return

        self.sort_combo.clear()
        self.sort_combo.addItems(self.metadata["column_names"])
        schema_frame = pd.DataFrame(self.metadata["columns"])
        self.schema_view.set_frame(schema_frame)
        self.reset_filters()

    def add_filter_row(self) -> None:
        if not self.metadata:
            self.window.show_warning("Filters", "Select a table first.")
            return
        row = FilterRowWidget(self.metadata["column_names"], self.remove_filter_row)
        self.filter_rows.append(row)
        self.filter_container.addWidget(row)

    def remove_filter_row(self, row: FilterRowWidget) -> None:
        self.filter_rows = [item for item in self.filter_rows if item is not row]
        row.setParent(None)
        row.deleteLater()

    def reset_filters(self) -> None:
        for row in list(self.filter_rows):
            self.remove_filter_row(row)

    def current_filters(self) -> list[dict[str, Any]]:
        return [row.to_filter() for row in self.filter_rows]

    def search(self) -> None:
        table_name = self.table_combo.currentText()
        if not table_name:
            self.window.show_warning("Data Explorer", "Select a table first.")
            return
        try:
            with loading_operation("Searching records...", self.window):
                statement, _ = build_select_statement(
                    self.window.active_engine(),
                    table_name,
                    keyword=self.keyword_edit.text().strip(),
                    filters=self.current_filters(),
                    sort_by=self.sort_combo.currentText() or None,
                    sort_direction=self.direction_combo.currentText(),
                    limit=int(self.limit_combo.currentText() or "100"),
                    include_soft_deleted=self.include_deleted_checkbox.isChecked(),
                )
                frame = fetch_dataframe(self.window.active_engine(), statement)
        except Exception as exc:
            self.window.show_error("Data Explorer", exc)
            return

        self.results_view.set_frame(frame)
        self.window.last_results = frame
        self.window.last_results_table = table_name
        self.window.status_message(f"Loaded {len(frame)} rows from {table_name}.")

    def export_csv(self) -> None:
        frame = self.results_view.dataframe()
        if frame.empty:
            self.window.show_warning("Export", "There are no search results to export.")
            return
        self.window.save_bytes("CSV Files (*.csv)", dataframe_to_csv_bytes(frame), default_name="filtered_results.csv")

    def export_excel(self) -> None:
        frame = self.results_view.dataframe()
        if frame.empty:
            self.window.show_warning("Export", "There are no search results to export.")
            return
        self.window.save_bytes("Excel Files (*.xlsx)", dataframe_to_excel_bytes(frame), default_name="filtered_results.xlsx")

    def apply_query_plan(self, plan: dict[str, Any]) -> None:
        table_name = str(plan.get("table") or "")
        if not table_name:
            return
        index = self.table_combo.findText(table_name)
        if index >= 0:
            self.table_combo.setCurrentIndex(index)
        self.keyword_edit.setText(str(plan.get("keyword") or ""))
        sort_by = str(plan.get("sort_by") or "")
        if sort_by:
            sort_index = self.sort_combo.findText(sort_by)
            if sort_index >= 0:
                self.sort_combo.setCurrentIndex(sort_index)
        direction_index = self.direction_combo.findText(str(plan.get("sort_direction") or "asc"))
        if direction_index >= 0:
            self.direction_combo.setCurrentIndex(direction_index)
        self.limit_combo.setCurrentText(str(plan.get("limit") or "100"))
        self.reset_filters()
        for filter_payload in plan.get("filters", []):
            self.add_filter_row()
            self.filter_rows[-1].apply_filter(filter_payload)
        self.search()


class AddRecordPage(BasePage):
    def __init__(self, window: "MainWindow") -> None:
        super().__init__(window)
        self.metadata: dict[str, Any] | None = None
        self.pending_payload: dict[str, Any] | None = None

        layout = QVBoxLayout(self)
        header = QHBoxLayout()
        self.table_combo = QComboBox()
        self.advanced_checkbox = QCheckBox("Include advanced/system fields")
        header.addWidget(QLabel("Table"))
        header.addWidget(self.table_combo, 2)
        header.addWidget(self.advanced_checkbox, 1)
        layout.addLayout(header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        form_container = QWidget()
        form_layout = QVBoxLayout(form_container)
        self.form_widget = DynamicFormWidget()
        form_layout.addWidget(self.form_widget)
        form_layout.addStretch(1)
        scroll.setWidget(form_container)
        layout.addWidget(scroll, 1)

        self.preview_text = QPlainTextEdit()
        self.preview_text.setReadOnly(True)
        self.confirm_checkbox = QCheckBox("I confirm this insert should be executed.")
        buttons = QHBoxLayout()
        self.preview_button = QPushButton("Preview Insert")
        self.execute_button = QPushButton("Execute Insert")
        buttons.addWidget(self.preview_button)
        buttons.addWidget(self.execute_button)
        buttons.addStretch(1)
        layout.addWidget(QLabel("Preview"))
        layout.addWidget(self.preview_text, 1)
        layout.addWidget(self.confirm_checkbox)
        layout.addLayout(buttons)

        self.table_combo.currentTextChanged.connect(self._table_changed)
        self.advanced_checkbox.stateChanged.connect(lambda _: self._refresh_form())
        self.preview_button.clicked.connect(self.preview_insert)
        self.execute_button.clicked.connect(self.execute_insert)

    def on_database_changed(self) -> None:
        self.refresh_tables()

    def on_activated(self) -> None:
        self.refresh_tables()

    def refresh_tables(self) -> None:
        current = self.table_combo.currentText()
        self.table_combo.blockSignals(True)
        self.table_combo.clear()
        self.table_combo.addItems(self.window.get_available_tables())
        index = self.table_combo.findText(current)
        if index >= 0:
            self.table_combo.setCurrentIndex(index)
        self.table_combo.blockSignals(False)
        if self.table_combo.count() > 0:
            self._table_changed(self.table_combo.currentText())

    def _table_changed(self, table_name: str) -> None:
        self.pending_payload = None
        self.preview_text.clear()
        if not table_name:
            self.metadata = None
            self.form_widget.clear()
            return
        try:
            self.metadata = get_table_metadata(self.window.active_engine(), table_name)
            self._refresh_form()
        except Exception as exc:
            self.window.show_error("Add Record", exc)

    def _refresh_form(self) -> None:
        self.form_widget.set_metadata(self.metadata, include_advanced=self.advanced_checkbox.isChecked())

    def preview_insert(self) -> None:
        if not self.metadata:
            self.window.show_warning("Add Record", "Select a table first.")
            return
        try:
            payload = prepare_record_payload(
                self.window.active_engine(),
                self.table_combo.currentText(),
                self.form_widget.values(),
                include_system_fields=self.advanced_checkbox.isChecked(),
            )
        except Exception as exc:
            self.window.show_error("Add Record", exc)
            return
        self.pending_payload = payload
        self.preview_text.setPlainText(json.dumps(payload, ensure_ascii=False, indent=2, default=str))

    def execute_insert(self) -> None:
        if not self.confirm_checkbox.isChecked():
            self.window.show_warning("Add Record", "Preview the record and confirm before executing the insert.")
            return
        if not self.pending_payload:
            self.window.show_warning("Add Record", "Generate a preview before executing the insert.")
            return
        try:
            with loading_operation("Saving changes...", self.window):
                record_id = insert_record(
                    self.window.active_engine(),
                    self.table_combo.currentText(),
                    self.form_widget.values(),
                    actor=self.window.actor,
                    include_system_fields=self.advanced_checkbox.isChecked(),
                )
        except Exception as exc:
            self.window.show_error("Add Record", exc)
            return
        self.window.status_message(f"Record {record_id} inserted successfully.")
        self.pending_payload = None
        self.preview_text.clear()
        self.confirm_checkbox.setChecked(False)
        self._refresh_form()


class EditRecordPage(BasePage):
    def __init__(self, window: "MainWindow") -> None:
        super().__init__(window)
        self.metadata: dict[str, Any] | None = None
        self.current_record: dict[str, Any] | None = None
        self.pending_update: dict[str, Any] | None = None

        layout = QVBoxLayout(self)
        selector = QGridLayout()
        self.table_combo = QComboBox()
        self.record_combo = QComboBox()
        self.refresh_records_button = QPushButton("Refresh Records")
        self.advanced_checkbox = QCheckBox("Include advanced/system fields")
        selector.addWidget(QLabel("Table"), 0, 0)
        selector.addWidget(self.table_combo, 0, 1)
        selector.addWidget(QLabel("Record"), 1, 0)
        selector.addWidget(self.record_combo, 1, 1)
        selector.addWidget(self.refresh_records_button, 1, 2)
        selector.addWidget(self.advanced_checkbox, 2, 0, 1, 3)
        layout.addLayout(selector)

        splitter = QSplitter(Qt.Vertical)
        top = QWidget()
        top_layout = QVBoxLayout(top)
        self.current_record_text = QPlainTextEdit()
        self.current_record_text.setReadOnly(True)
        top_layout.addWidget(QLabel("Current record"))
        top_layout.addWidget(self.current_record_text)

        bottom = QWidget()
        bottom_layout = QVBoxLayout(bottom)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        form_container = QWidget()
        form_container_layout = QVBoxLayout(form_container)
        self.form_widget = DynamicFormWidget()
        form_container_layout.addWidget(self.form_widget)
        form_container_layout.addStretch(1)
        scroll.setWidget(form_container)
        bottom_layout.addWidget(scroll)
        self.preview_text = QPlainTextEdit()
        self.preview_text.setReadOnly(True)
        bottom_layout.addWidget(QLabel("Before / after preview"))
        bottom_layout.addWidget(self.preview_text)
        splitter.addWidget(top)
        splitter.addWidget(bottom)
        splitter.setSizes([220, 480])
        layout.addWidget(splitter, 1)

        self.update_confirm_checkbox = QCheckBox("I confirm this update should be executed.")
        update_actions = QHBoxLayout()
        self.preview_update_button = QPushButton("Preview Update")
        self.execute_update_button = QPushButton("Execute Update")
        update_actions.addWidget(self.preview_update_button)
        update_actions.addWidget(self.execute_update_button)
        update_actions.addStretch(1)
        layout.addWidget(self.update_confirm_checkbox)
        layout.addLayout(update_actions)

        self.delete_confirm_checkbox = QCheckBox("I confirm this soft delete should be executed.")
        self.soft_delete_button = QPushButton("Soft Delete Record")
        layout.addWidget(self.delete_confirm_checkbox)
        layout.addWidget(self.soft_delete_button)

        self.table_combo.currentTextChanged.connect(self._table_changed)
        self.record_combo.currentIndexChanged.connect(lambda _: self._load_selected_record())
        self.refresh_records_button.clicked.connect(self._refresh_records)
        self.advanced_checkbox.stateChanged.connect(lambda _: self._reload_form())
        self.preview_update_button.clicked.connect(self.preview_update)
        self.execute_update_button.clicked.connect(self.execute_update)
        self.soft_delete_button.clicked.connect(self.execute_soft_delete)

    def on_database_changed(self) -> None:
        self.refresh_tables()

    def on_activated(self) -> None:
        self.refresh_tables()

    def refresh_tables(self) -> None:
        current = self.table_combo.currentText()
        self.table_combo.blockSignals(True)
        self.table_combo.clear()
        self.table_combo.addItems(self.window.get_available_tables())
        index = self.table_combo.findText(current)
        if index >= 0:
            self.table_combo.setCurrentIndex(index)
        self.table_combo.blockSignals(False)
        if self.table_combo.count() > 0:
            self._table_changed(self.table_combo.currentText())

    def _table_changed(self, table_name: str) -> None:
        if not table_name:
            return
        try:
            self.metadata = get_table_metadata(self.window.active_engine(), table_name)
            self._refresh_records()
        except Exception as exc:
            self.window.show_error("Edit Record", exc)

    def _refresh_records(self) -> None:
        table_name = self.table_combo.currentText()
        if not table_name:
            return
        try:
            choices = list_record_choices(self.window.active_engine(), table_name, limit=200)
        except Exception as exc:
            self.window.show_error("Edit Record", exc)
            return
        self.record_combo.blockSignals(True)
        self.record_combo.clear()
        for record_id, label in choices:
            self.record_combo.addItem(label, record_id)
        self.record_combo.blockSignals(False)
        self._load_selected_record()

    def _load_selected_record(self) -> None:
        record_id = self.record_combo.currentData()
        table_name = self.table_combo.currentText()
        if not record_id or not table_name:
            self.current_record = None
            self.current_record_text.clear()
            self.form_widget.clear()
            return
        try:
            self.current_record = get_record_by_pk(self.window.active_engine(), table_name, record_id)
        except Exception as exc:
            self.window.show_error("Edit Record", exc)
            return
        self.current_record_text.setPlainText(json.dumps(self.current_record or {}, ensure_ascii=False, indent=2, default=str))
        self._reload_form()

    def _reload_form(self) -> None:
        self.pending_update = None
        self.preview_text.clear()
        self.form_widget.set_metadata(
            self.metadata,
            initial_values=self.current_record or {},
            include_advanced=self.advanced_checkbox.isChecked(),
            include_primary_key=False,
        )

    def preview_update(self) -> None:
        if not self.current_record:
            self.window.show_warning("Edit Record", "Select a record first.")
            return
        after_payload = self.form_widget.values()
        self.pending_update = after_payload
        preview = {"before": self.current_record, "after": after_payload}
        self.preview_text.setPlainText(json.dumps(preview, ensure_ascii=False, indent=2, default=str))

    def execute_update(self) -> None:
        if not self.update_confirm_checkbox.isChecked():
            self.window.show_warning("Edit Record", "Preview the change and confirm before updating.")
            return
        if self.pending_update is None:
            self.window.show_warning("Edit Record", "Generate a preview before executing the update.")
            return
        record_id = self.record_combo.currentData()
        try:
            with loading_operation("Saving changes...", self.window):
                rowcount = update_record(
                    self.window.active_engine(),
                    self.table_combo.currentText(),
                    record_id=record_id,
                    data=self.form_widget.values(),
                    actor=self.window.actor,
                    include_system_fields=self.advanced_checkbox.isChecked(),
                )
        except Exception as exc:
            self.window.show_error("Edit Record", exc)
            return
        self.window.status_message(f"Updated {rowcount} record(s).")
        self.update_confirm_checkbox.setChecked(False)
        self._refresh_records()

    def execute_soft_delete(self) -> None:
        if not self.delete_confirm_checkbox.isChecked():
            self.window.show_warning("Edit Record", "Confirm the soft delete before executing it.")
            return
        record_id = self.record_combo.currentData()
        try:
            with loading_operation("Saving changes...", self.window):
                rowcount = soft_delete_record(
                    self.window.active_engine(),
                    self.table_combo.currentText(),
                    record_id=record_id,
                    actor=self.window.actor,
                )
        except Exception as exc:
            self.window.show_error("Edit Record", exc)
            return
        self.window.status_message(f"Soft-deleted {rowcount} record(s).")
        self.delete_confirm_checkbox.setChecked(False)
        self._refresh_records()


class ImportExportPage(BasePage):
    def __init__(self, window: "MainWindow") -> None:
        super().__init__(window)
        self.import_frame = pd.DataFrame()
        self.import_path: str | None = None

        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        self.table_combo = QComboBox()
        top.addWidget(QLabel("Table"))
        top.addWidget(self.table_combo, 1)
        layout.addLayout(top)

        export_group = QGroupBox("Export")
        export_layout = QHBoxLayout(export_group)
        self.export_table_csv_button = QPushButton("Export table to CSV")
        self.export_table_excel_button = QPushButton("Export table to Excel")
        self.export_filtered_csv_button = QPushButton("Export filtered result to CSV")
        self.export_filtered_excel_button = QPushButton("Export filtered result to Excel")
        export_layout.addWidget(self.export_table_csv_button)
        export_layout.addWidget(self.export_table_excel_button)
        export_layout.addWidget(self.export_filtered_csv_button)
        export_layout.addWidget(self.export_filtered_excel_button)
        layout.addWidget(export_group)

        import_group = QGroupBox("Import CSV")
        import_layout = QVBoxLayout(import_group)
        import_actions = QHBoxLayout()
        self.choose_csv_button = QPushButton("Choose CSV file")
        self.selected_csv_label = QLabel("No file selected")
        import_actions.addWidget(self.choose_csv_button)
        import_actions.addWidget(self.selected_csv_label, 1)
        import_layout.addLayout(import_actions)
        self.import_preview = DataFrameView()
        import_layout.addWidget(self.import_preview, 1)
        self.import_validation_label = QLabel()
        self.import_confirm_checkbox = QCheckBox("I confirm this bulk import should be executed.")
        self.import_button = QPushButton("Execute Import")
        import_layout.addWidget(self.import_validation_label)
        import_layout.addWidget(self.import_confirm_checkbox)
        import_layout.addWidget(self.import_button)
        layout.addWidget(import_group, 1)

        self.table_combo.currentTextChanged.connect(lambda _: self._validate_import())
        self.export_table_csv_button.clicked.connect(self.export_table_csv)
        self.export_table_excel_button.clicked.connect(self.export_table_excel)
        self.export_filtered_csv_button.clicked.connect(self.export_filtered_csv)
        self.export_filtered_excel_button.clicked.connect(self.export_filtered_excel)
        self.choose_csv_button.clicked.connect(self.choose_csv)
        self.import_button.clicked.connect(self.execute_import)

    def on_database_changed(self) -> None:
        self.refresh_tables()

    def on_activated(self) -> None:
        self.refresh_tables()

    def refresh_tables(self) -> None:
        current = self.table_combo.currentText()
        self.table_combo.clear()
        self.table_combo.addItems(self.window.get_available_tables())
        index = self.table_combo.findText(current)
        if index >= 0:
            self.table_combo.setCurrentIndex(index)

    def export_table_csv(self) -> None:
        table_name = self.table_combo.currentText()
        if not table_name:
            return
        try:
            with loading_operation("Exporting data...", self.window):
                frame = export_table_to_dataframe(self.window.active_engine(), table_name)
        except Exception as exc:
            self.window.show_error("Export", exc)
            return
        self.window.save_bytes("CSV Files (*.csv)", dataframe_to_csv_bytes(frame), default_name=f"{table_name}.csv")

    def export_table_excel(self) -> None:
        table_name = self.table_combo.currentText()
        if not table_name:
            return
        try:
            with loading_operation("Exporting data...", self.window):
                frame = export_table_to_dataframe(self.window.active_engine(), table_name)
        except Exception as exc:
            self.window.show_error("Export", exc)
            return
        self.window.save_bytes("Excel Files (*.xlsx)", dataframe_to_excel_bytes(frame), default_name=f"{table_name}.xlsx")

    def export_filtered_csv(self) -> None:
        if self.window.last_results.empty:
            self.window.show_warning("Export", "There are no filtered search results to export.")
            return
        name = self.window.last_results_table or "filtered_results"
        self.window.save_bytes("CSV Files (*.csv)", dataframe_to_csv_bytes(self.window.last_results), default_name=f"{name}.csv")

    def export_filtered_excel(self) -> None:
        if self.window.last_results.empty:
            self.window.show_warning("Export", "There are no filtered search results to export.")
            return
        name = self.window.last_results_table or "filtered_results"
        self.window.save_bytes(
            "Excel Files (*.xlsx)",
            dataframe_to_excel_bytes(self.window.last_results),
            default_name=f"{name}.xlsx",
        )

    def choose_csv(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(self, "Choose CSV file", "", "CSV Files (*.csv)")
        if not file_path:
            return
        try:
            frame = pd.read_csv(file_path)
        except Exception as exc:
            self.window.show_error("Import", exc)
            return
        self.import_frame = frame
        self.import_path = file_path
        self.selected_csv_label.setText(Path(file_path).name)
        self.import_preview.set_frame(frame.head(100))
        self._validate_import()

    def _validate_import(self) -> None:
        table_name = self.table_combo.currentText()
        if not table_name or self.import_frame.empty:
            self.import_validation_label.setText("")
            return
        try:
            metadata = get_table_metadata(self.window.active_engine(), table_name)
        except Exception as exc:
            self.window.show_error("Import", exc)
            return
        allowed_columns = set(metadata["column_names"])
        incoming_columns = set(self.import_frame.columns)
        unknown_columns = sorted(incoming_columns - allowed_columns)
        missing_columns = sorted(column for column in metadata["column_names"] if column not in incoming_columns and column not in {"id"})
        if unknown_columns:
            self.import_validation_label.setText(f"Unknown CSV columns: {', '.join(unknown_columns)}")
            return
        if missing_columns:
            self.import_validation_label.setText(
                f"Missing columns are allowed if nullable or auto-managed: {', '.join(missing_columns)}"
            )
            return
        self.import_validation_label.setText("CSV columns match the selected table.")

    def execute_import(self) -> None:
        if self.import_frame.empty:
            self.window.show_warning("Import", "Choose a CSV file first.")
            return
        if not self.import_confirm_checkbox.isChecked():
            self.window.show_warning("Import", "Preview the CSV and confirm before importing.")
            return
        table_name = self.table_combo.currentText()
        try:
            rows = self.import_frame.to_dict(orient="records")
            with loading_operation("Importing data...", self.window):
                imported = bulk_import_records(self.window.active_engine(), table_name, rows, actor=self.window.actor)
        except Exception as exc:
            self.window.show_error("Import", exc)
            return
        self.window.status_message(f"Imported {imported} row(s) into {table_name}.")
        self.import_confirm_checkbox.setChecked(False)


class AIAssistantPage(BasePage):
    def __init__(self, window: "MainWindow") -> None:
        super().__init__(window)
        self.last_plan: dict[str, Any] | None = None

        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        self.table_combo = QComboBox()
        top.addWidget(QLabel("Table"))
        top.addWidget(self.table_combo, 1)
        layout.addLayout(top)

        self.request_edit = QPlainTextEdit()
        self.request_edit.setPlaceholderText("Describe the data question or filtering request here.")
        self.output_edit = QPlainTextEdit()
        self.output_edit.setReadOnly(True)

        action_row = QHBoxLayout()
        self.explain_schema_button = QPushButton("Explain Schema")
        self.explain_sample_button = QPushButton("Explain Sample")
        self.generate_plan_button = QPushButton("Generate Safe Query Plan")
        self.summarize_button = QPushButton("Summarize Filtered Data")
        self.anomalies_button = QPushButton("Detect Anomalies")
        self.report_button = QPushButton("Draft Report")
        self.apply_plan_button = QPushButton("Apply Plan in Data Explorer")
        self.apply_plan_button.setEnabled(False)
        for button in (
            self.explain_schema_button,
            self.explain_sample_button,
            self.generate_plan_button,
            self.summarize_button,
            self.anomalies_button,
            self.report_button,
            self.apply_plan_button,
        ):
            action_row.addWidget(button)
        layout.addWidget(QLabel("Prompt"))
        layout.addWidget(self.request_edit, 1)
        layout.addLayout(action_row)
        layout.addWidget(QLabel("Response"))
        layout.addWidget(self.output_edit, 2)

        self.explain_schema_button.clicked.connect(self._explain_schema)
        self.explain_sample_button.clicked.connect(self._explain_sample)
        self.generate_plan_button.clicked.connect(self._generate_plan)
        self.summarize_button.clicked.connect(self._summarize)
        self.anomalies_button.clicked.connect(self._anomalies)
        self.report_button.clicked.connect(self._draft_report)
        self.apply_plan_button.clicked.connect(self._apply_plan)

    def on_database_changed(self) -> None:
        self.refresh_tables()
        self.last_plan = None
        self.apply_plan_button.setEnabled(False)
        self.output_edit.clear()

    def on_activated(self) -> None:
        self.refresh_tables()

    def refresh_tables(self) -> None:
        current = self.table_combo.currentText()
        self.table_combo.clear()
        self.table_combo.addItems(self.window.get_available_tables())
        index = self.table_combo.findText(current)
        if index >= 0:
            self.table_combo.setCurrentIndex(index)

    def _metadata(self) -> tuple[str, dict[str, Any]]:
        table_name = self.table_combo.currentText()
        if not table_name:
            raise ValueError("Select a table first.")
        metadata = get_table_metadata(self.window.active_engine(), table_name)
        schema_summary = {
            "database_name": self.window.manager.get_active_database_name(),
            "table_name": table_name,
            "primary_key": metadata["primary_key"],
            "columns": metadata["columns"],
        }
        return table_name, schema_summary

    def _sample_frame(self, table_name: str) -> pd.DataFrame:
        if self.window.last_results_table == table_name and not self.window.last_results.empty:
            return self.window.last_results.copy()
        statement, _ = build_select_statement(self.window.active_engine(), table_name, limit=50)
        return fetch_dataframe(self.window.active_engine(), statement)

    def _set_output(self, text: str) -> None:
        self.output_edit.setPlainText(text)

    def _explain_schema(self) -> None:
        try:
            table_name, schema_summary = self._metadata()
            with loading_operation("Asking local AI...", self.window):
                response = explain_schema(table_name, schema_summary, model=self.window.selected_ollama_model)
        except Exception as exc:
            self.window.show_error("AI Assistant", exc)
            return
        self._set_output(response)

    def _explain_sample(self) -> None:
        try:
            table_name, _ = self._metadata()
            frame = self._sample_frame(table_name)
            with loading_operation("Asking local AI...", self.window):
                response = explain_data_sample(
                    table_name,
                    frame.head(20).to_dict(orient="records"),
                    model=self.window.selected_ollama_model,
                    database_name=self.window.manager.get_active_database_name(),
                )
        except Exception as exc:
            self.window.show_error("AI Assistant", exc)
            return
        self._set_output(response)

    def _generate_plan(self) -> None:
        user_request = self.request_edit.toPlainText().strip()
        if not user_request:
            self.window.show_warning("AI Assistant", "Describe the filter request first.")
            return
        try:
            table_name, schema_summary = self._metadata()
            metadata = get_table_metadata(self.window.active_engine(), table_name)
            with loading_operation("Asking local AI...", self.window):
                plan = request_safe_query_plan(
                    user_request,
                    database_name=self.window.manager.get_active_database_name(),
                    table_name=table_name,
                    schema_summary=schema_summary,
                    allowed_tables=self.window.get_available_tables(),
                    allowed_columns=metadata["column_names"],
                    model=self.window.selected_ollama_model,
                )
        except Exception as exc:
            self.window.show_error("AI Assistant", exc)
            return
        self.last_plan = plan
        self.apply_plan_button.setEnabled(True)
        self._set_output(json.dumps(plan, ensure_ascii=False, indent=2))

    def _summarize(self) -> None:
        table_name = self.window.last_results_table
        frame = self.window.last_results
        if not table_name or frame.empty:
            self.window.show_warning("AI Assistant", "Run a filtered search in Data Explorer first.")
            return
        try:
            with loading_operation("Asking local AI...", self.window):
                response = summarize_dataframe(
                    table_name,
                    frame,
                    model=self.window.selected_ollama_model,
                    database_name=self.window.manager.get_active_database_name(),
                )
        except Exception as exc:
            self.window.show_error("AI Assistant", exc)
            return
        self._set_output(response)

    def _anomalies(self) -> None:
        table_name = self.window.last_results_table
        frame = self.window.last_results
        if not table_name or frame.empty:
            self.window.show_warning("AI Assistant", "Run a filtered search in Data Explorer first.")
            return
        try:
            with loading_operation("Asking local AI...", self.window):
                response = detect_anomalies(
                    table_name,
                    frame,
                    model=self.window.selected_ollama_model,
                    database_name=self.window.manager.get_active_database_name(),
                )
        except Exception as exc:
            self.window.show_error("AI Assistant", exc)
            return
        self._set_output(response)

    def _draft_report(self) -> None:
        table_name = self.window.last_results_table
        frame = self.window.last_results
        if not table_name or frame.empty:
            self.window.show_warning("AI Assistant", "Run a filtered search in Data Explorer first.")
            return
        try:
            with loading_operation("Asking local AI...", self.window):
                response = draft_report(
                    table_name,
                    frame,
                    model=self.window.selected_ollama_model,
                    database_name=self.window.manager.get_active_database_name(),
                )
        except Exception as exc:
            self.window.show_error("AI Assistant", exc)
            return
        self._set_output(response)

    def _apply_plan(self) -> None:
        if not self.last_plan:
            return
        self.window.data_explorer_page.apply_query_plan(self.last_plan)
        self.window.navigate_to("Data Explorer")


class AuditLogPage(BasePage):
    def __init__(self, window: "MainWindow") -> None:
        super().__init__(window)
        layout = QVBoxLayout(self)

        filters = QGridLayout()
        self.table_combo = QComboBox()
        self.action_combo = QComboBox()
        self.action_combo.addItems(["", "INSERT", "UPDATE", "SOFT_DELETE", "BULK_IMPORT"])
        self.actor_edit = QLineEdit()
        self.start_date = QDateEdit()
        self.end_date = QDateEdit()
        for widget in (self.start_date, self.end_date):
            widget.setCalendarPopup(True)
            widget.setDisplayFormat("yyyy-MM-dd")
        self.start_date.setDate(QDate.currentDate().addMonths(-1))
        self.end_date.setDate(QDate.currentDate())
        self.refresh_button = QPushButton("Refresh Audit Log")
        self.export_button = QPushButton("Export Audit Log")
        self.create_button = QPushButton("Create audit_log table in this database")
        filters.addWidget(QLabel("Table"), 0, 0)
        filters.addWidget(self.table_combo, 0, 1)
        filters.addWidget(QLabel("Action"), 0, 2)
        filters.addWidget(self.action_combo, 0, 3)
        filters.addWidget(QLabel("Actor"), 1, 0)
        filters.addWidget(self.actor_edit, 1, 1)
        filters.addWidget(QLabel("Start date"), 1, 2)
        filters.addWidget(self.start_date, 1, 3)
        filters.addWidget(QLabel("End date"), 2, 0)
        filters.addWidget(self.end_date, 2, 1)
        filters.addWidget(self.refresh_button, 2, 2)
        filters.addWidget(self.export_button, 2, 3)
        layout.addLayout(filters)
        layout.addWidget(self.create_button)

        splitter = QSplitter(Qt.Vertical)
        self.table_view = DataFrameView()
        detail_widget = QWidget()
        detail_layout = QHBoxLayout(detail_widget)
        self.before_text = QPlainTextEdit()
        self.before_text.setReadOnly(True)
        self.after_text = QPlainTextEdit()
        self.after_text.setReadOnly(True)
        detail_layout.addWidget(self.before_text)
        detail_layout.addWidget(self.after_text)
        splitter.addWidget(self.table_view)
        splitter.addWidget(detail_widget)
        splitter.setSizes([400, 220])
        layout.addWidget(splitter, 1)

        self.refresh_button.clicked.connect(self.refresh_audit_logs)
        self.export_button.clicked.connect(self.export_audit_logs)
        self.create_button.clicked.connect(self.create_audit_table)
        self.table_view.selectionModel().selectionChanged.connect(lambda *_: self._update_details())

    def on_database_changed(self) -> None:
        self.refresh_tables()
        self.refresh_audit_logs()

    def on_activated(self) -> None:
        self.refresh_tables()
        self.refresh_audit_logs()

    def refresh_tables(self) -> None:
        current = self.table_combo.currentText()
        self.table_combo.clear()
        self.table_combo.addItem("")
        self.table_combo.addItems(self.window.get_available_tables(include_audit=True))
        index = self.table_combo.findText(current)
        if index >= 0:
            self.table_combo.setCurrentIndex(index)

    def refresh_audit_logs(self) -> None:
        engine = self.window.active_engine()
        exists = audit_log_exists(engine)
        self.create_button.setVisible(not exists)
        if not exists:
            self.table_view.set_frame(pd.DataFrame())
            self.before_text.clear()
            self.after_text.clear()
            return
        try:
            with loading_operation("Loading audit log...", self.window):
                rows = fetch_audit_logs(
                    engine,
                    table_name=self.table_combo.currentText() or None,
                    action=self.action_combo.currentText() or None,
                    actor=self.actor_edit.text().strip() or None,
                    start_date=self.start_date.date().toPython(),
                    end_date=self.end_date.date().toPython(),
                    limit=500,
                )
        except Exception as exc:
            self.window.show_error("Audit Log", exc)
            return
        frame = pd.DataFrame(rows)
        if not frame.empty:
            frame["before_data_json"] = frame["before_data_json"].apply(lambda value: json.dumps(value, ensure_ascii=False, default=str))
            frame["after_data_json"] = frame["after_data_json"].apply(lambda value: json.dumps(value, ensure_ascii=False, default=str))
        self.table_view.set_frame(frame)
        self._update_details()

    def _update_details(self) -> None:
        frame = self.table_view.dataframe()
        if frame.empty:
            self.before_text.clear()
            self.after_text.clear()
            return
        index = self.table_view.currentIndex()
        row = index.row() if index.isValid() else 0
        row = max(0, min(row, len(frame) - 1))
        before = frame.iloc[row].get("before_data_json", "")
        after = frame.iloc[row].get("after_data_json", "")
        self.before_text.setPlainText(stringify_value(before))
        self.after_text.setPlainText(stringify_value(after))

    def export_audit_logs(self) -> None:
        frame = self.table_view.dataframe()
        if frame.empty:
            self.window.show_warning("Audit Log", "There are no audit log rows to export.")
            return
        self.window.save_bytes("CSV Files (*.csv)", dataframe_to_csv_bytes(frame), default_name="audit_log.csv")

    def create_audit_table(self) -> None:
        if not self.window.confirm_action("Create Audit Table", "Create audit_log table in the active database?"):
            return
        try:
            with loading_operation("Creating audit log table...", self.window):
                create_audit_log_table(self.window.active_engine())
        except Exception as exc:
            self.window.show_error("Audit Log", exc)
            return
        self.window.status_message("audit_log table created in the active database.")
        self.refresh_audit_logs()


class SettingsPage(BasePage):
    def __init__(self, window: "MainWindow") -> None:
        super().__init__(window)
        layout = QVBoxLayout(self)

        self.masked_url_label = QLabel()
        self.masked_url_label.setWordWrap(True)
        self.connection_label = QLabel()
        self.audit_label = QLabel()
        self.ollama_label = QLabel()
        self.models_combo = QComboBox()
        self.reload_models_button = QPushButton("Reload Ollama models")
        self.apply_model_button = QPushButton("Use selected model")
        self.test_connection_button = QPushButton("Test active database connection")
        self.create_audit_button = QPushButton("Create audit_log table in this database")

        layout.addWidget(QLabel("Masked active database URL"))
        layout.addWidget(self.masked_url_label)
        layout.addWidget(self.connection_label)
        layout.addWidget(self.audit_label)
        layout.addWidget(self.ollama_label)
        layout.addWidget(self.models_combo)
        controls = QHBoxLayout()
        controls.addWidget(self.reload_models_button)
        controls.addWidget(self.apply_model_button)
        controls.addWidget(self.test_connection_button)
        controls.addWidget(self.create_audit_button)
        layout.addLayout(controls)

        instructions = QLabel(
            "If Ollama is not running:\n"
            "1. Install Ollama\n"
            "2. Run: ollama pull llama3.2\n"
            "3. Run: ollama serve\n"
            "4. Restart the application"
        )
        instructions.setWordWrap(True)
        layout.addWidget(instructions)
        layout.addStretch(1)

        self.reload_models_button.clicked.connect(self.reload_models)
        self.apply_model_button.clicked.connect(self.apply_model)
        self.test_connection_button.clicked.connect(self.test_connection)
        self.create_audit_button.clicked.connect(self.create_audit_table)

    def on_database_changed(self) -> None:
        self.refresh_settings()

    def on_activated(self) -> None:
        self.refresh_settings()

    def refresh_settings(self) -> None:
        status = self.window.manager.current_database_status()
        self.masked_url_label.setText(status["masked_url"])
        self.test_connection()
        self.reload_models()
        exists = audit_log_exists(self.window.active_engine())
        self.audit_label.setText("audit_log table is available." if exists else "audit_log table is missing.")
        self.create_audit_button.setVisible(not exists)

    def test_connection(self) -> None:
        status = self.window.manager.current_database_status()
        success, message = test_connection(status["url"])
        self.connection_label.setText(message)
        if success:
            self.audit_label.setText("audit_log table status can be checked for this database.")
        else:
            self.audit_label.setText("Audit log availability is not checked because the active database connection is currently failing.")

    def reload_models(self) -> None:
        ok, message = check_ollama_health()
        self.ollama_label.setText(message)
        self.models_combo.clear()
        if not ok:
            self.models_combo.addItem(self.window.selected_ollama_model)
            return
        try:
            models = list_models()
        except Exception as exc:
            self.ollama_label.setText(f"Ollama unavailable: {exc}")
            self.models_combo.addItem(self.window.selected_ollama_model)
            return
        if not models:
            models = [self.window.selected_ollama_model]
        self.models_combo.addItems(models)
        index = self.models_combo.findText(self.window.selected_ollama_model)
        if index >= 0:
            self.models_combo.setCurrentIndex(index)

    def apply_model(self) -> None:
        model_name = self.models_combo.currentText().strip()
        if not model_name:
            self.window.show_warning("Settings", "Select an Ollama model first.")
            return
        self.window.selected_ollama_model = model_name
        self.window.manager.state["selected_ollama_model"] = model_name
        self.window.status_message(f"Ollama model switched to {model_name}.")

    def create_audit_table(self) -> None:
        if not self.window.confirm_action("Create Audit Table", "Create audit_log table in the active database?"):
            return
        try:
            with loading_operation("Creating audit log table...", self.window):
                create_audit_log_table(self.window.active_engine())
        except Exception as exc:
            self.window.show_error("Settings", exc)
            return
        self.window.status_message("audit_log table created in the active database.")
        self.refresh_settings()


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        settings = get_settings()
        self.actor = settings.app_actor
        self.manager = ConnectionManager()
        self.selected_ollama_model = str(self.manager.state.get("selected_ollama_model") or settings.ollama_model)
        self.last_results = pd.DataFrame()
        self.last_results_table: str | None = None

        self.setWindowTitle("Database Control Center")
        self.resize(1600, 980)

        self._create_actions()
        self._build_ui()
        self._ensure_demo_database_if_needed()
        self.refresh_status_bar()
        self._notify_all_pages_database_changed()
        self.navigate_to("Database Login / Connection Manager")

    def _create_actions(self) -> None:
        exit_action = QAction("Exit", self)
        exit_action.triggered.connect(self.close)
        file_menu = self.menuBar().addMenu("File")
        file_menu.addAction(exit_action)

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        layout = QHBoxLayout(central)

        self.navigation = QListWidget()
        self.navigation.addItems(PAGE_TITLES)
        self.navigation.setFixedWidth(260)
        layout.addWidget(self.navigation)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        layout.addWidget(right, 1)

        status_frame = QFrame()
        status_frame.setFrameShape(QFrame.StyledPanel)
        status_layout = QHBoxLayout(status_frame)
        self.active_db_label = QLabel("Active DB: -")
        self.db_type_label = QLabel("DB Type: -")
        self.ollama_status_label = QLabel("Ollama: -")
        self.connection_status_label = QLabel("Connection: -")
        status_layout.addWidget(self.active_db_label)
        status_layout.addWidget(self.db_type_label)
        status_layout.addWidget(self.ollama_status_label)
        status_layout.addWidget(self.connection_status_label, 1)
        right_layout.addWidget(status_frame)

        self.pages = QStackedWidget()
        right_layout.addWidget(self.pages, 1)

        self.connection_page = ConnectionManagerPage(self)
        self.dashboard_page = DashboardPage(self)
        self.data_explorer_page = DataExplorerPage(self)
        self.add_record_page = AddRecordPage(self)
        self.edit_record_page = EditRecordPage(self)
        self.import_export_page = ImportExportPage(self)
        self.ai_page = AIAssistantPage(self)
        self.audit_page = AuditLogPage(self)
        self.settings_page = SettingsPage(self)

        self.page_widgets: list[tuple[str, BasePage]] = [
            (PAGE_TITLES[0], self.connection_page),
            (PAGE_TITLES[1], self.dashboard_page),
            (PAGE_TITLES[2], self.data_explorer_page),
            (PAGE_TITLES[3], self.add_record_page),
            (PAGE_TITLES[4], self.edit_record_page),
            (PAGE_TITLES[5], self.import_export_page),
            (PAGE_TITLES[6], self.ai_page),
            (PAGE_TITLES[7], self.audit_page),
            (PAGE_TITLES[8], self.settings_page),
        ]
        for _, page in self.page_widgets:
            self.pages.addWidget(page)

        self.navigation.currentRowChanged.connect(self._change_page)
        self.statusBar().showMessage("Ready")

    def active_engine(self):
        return self.manager.get_active_engine()

    def navigate_to(self, title: str) -> None:
        for index, (page_title, _) in enumerate(self.page_widgets):
            if page_title == title:
                self.navigation.setCurrentRow(index)
                break

    def _change_page(self, index: int) -> None:
        if index < 0 or index >= len(self.page_widgets):
            return
        self.pages.setCurrentIndex(index)
        self.page_widgets[index][1].on_activated()

    def _notify_all_pages_database_changed(self) -> None:
        for _, page in self.page_widgets:
            page.on_database_changed()

    def _ensure_demo_database_if_needed(self) -> None:
        try:
            ensure_demo_seed_for_sqlite(self.active_engine())
        except Exception:
            return

    def get_available_tables(self, *, include_audit: bool = False) -> list[str]:
        status = self.manager.current_database_status()
        success, _ = test_connection(status["url"])
        if not success:
            return []
        try:
            return get_table_names(self.active_engine(), include_audit=include_audit)
        except SQLAlchemyError:
            return []

    def refresh_status_bar(self) -> None:
        status = self.manager.current_database_status()
        db_ok, db_message = test_connection(status["url"])
        ollama_ok, ollama_message = check_ollama_health()
        self.active_db_label.setText(f"Active DB: {status['name']}")
        self.db_type_label.setText(f"DB Type: {status['type']}")
        self.ollama_status_label.setText(f"Ollama: {'Online' if ollama_ok else 'Offline'}")
        self.connection_status_label.setText(db_message if not db_ok else "Connection: OK")
        if not db_ok:
            self.statusBar().showMessage("The active database connection is currently failing. Use Connection Manager to switch databases.")
        elif not ollama_ok:
            self.statusBar().showMessage(ollama_message)
        else:
            self.statusBar().showMessage("Ready")

    def connect_to_profile(self, profile: dict[str, Any], *, add_to_session_profiles: bool) -> None:
        with loading_operation("Connecting to database...", self):
            success, message = self.manager.connect_profile(profile, add_to_session_profiles=add_to_session_profiles)
        if not success:
            self.show_warning("Database connection", message)
            self.refresh_status_bar()
            return
        self._ensure_demo_database_if_needed()
        self.refresh_status_bar()
        self._notify_all_pages_database_changed()
        self.status_message(message)

    def status_message(self, message: str) -> None:
        self.statusBar().showMessage(message, 8000)
        QMessageBox.information(self, "Database Control Center", message)

    def save_bytes(self, file_filter: str, payload: bytes, *, default_name: str) -> None:
        file_path, _ = QFileDialog.getSaveFileName(self, "Save file", default_name, file_filter)
        if not file_path:
            return
        Path(file_path).write_bytes(payload)
        self.status_message(f"Saved file to {file_path}")

    def show_error(self, title: str, error: Exception | str) -> None:
        QMessageBox.critical(self, title, str(error))

    def show_warning(self, title: str, message: str) -> None:
        QMessageBox.warning(self, title, message)

    def show_info(self, title: str, message: str) -> None:
        QMessageBox.information(self, title, message)

    def confirm_action(self, title: str, message: str) -> bool:
        answer = QMessageBox.question(self, title, message, QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        return answer == QMessageBox.Yes


def build_application() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    app.setApplicationName("Database Control Center")
    return app


def main() -> int:
    app = build_application()
    window = MainWindow()
    window.show()
    return app.exec()

