from __future__ import annotations

import json
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QPlainTextEdit,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from src.ai_action_router import AIActionRouter
from src.ai_operator import AIOperator
from src.ui_styles import AppCard, ModernMessageBanner, PillBadge, PrimaryButton, SecondaryButton, SectionHeader


class AIResponseCard(QFrame):
    def __init__(self, title: str, message: str, role: str = "primary", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("card", True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(8)
        header = QHBoxLayout()
        header.addWidget(PillBadge(title, role))
        header.addStretch(1)
        layout.addLayout(header)
        self.message_label = QLabel(message)
        self.message_label.setWordWrap(True)
        self.message_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.message_label)
        self.actions_layout = QHBoxLayout()
        self.actions_layout.addStretch(1)
        layout.addLayout(self.actions_layout)

    def add_action(self, button: QPushButton) -> None:
        self.actions_layout.insertWidget(self.actions_layout.count() - 1, button)


class AIChatPanel(QWidget):
    def __init__(self, window) -> None:
        super().__init__(window)
        self.window = window
        self.router = AIActionRouter(window)
        self.setMinimumWidth(360)
        self.setMaximumWidth(460)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        header_card = AppCard()
        header_row = QHBoxLayout()
        title = SectionHeader("AI Operator", "Ask about the current page, table, row, filters, or audit trail.")
        header_row.addWidget(title, 1)
        self.collapse_button = QToolButton()
        self.collapse_button.setText("Hide")
        header_row.addWidget(self.collapse_button)
        header_card.content_layout.addLayout(header_row)
        header_card.content_layout.addWidget(
            ModernMessageBanner(
                "AI can help operate the app, but database changes require your approval.",
                "warning",
            )
        )
        layout.addWidget(header_card)

        context_card = AppCard("Context")
        self.include_page_context = QCheckBox("Include current page context")
        self.include_page_context.setChecked(True)
        self.include_schema = QCheckBox("Include selected table/schema")
        self.include_schema.setChecked(True)
        self.include_selected_row = QCheckBox("Include selected row")
        self.include_selected_row.setChecked(True)
        self.include_result_sample = QCheckBox("Include current result sample")
        self.include_result_sample.setChecked(True)
        for checkbox in (
            self.include_page_context,
            self.include_schema,
            self.include_selected_row,
            self.include_result_sample,
        ):
            context_card.content_layout.addWidget(checkbox)
        layout.addWidget(context_card)

        history_card = AppCard("Conversation")
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.history_root = QWidget()
        self.history_layout = QVBoxLayout(self.history_root)
        self.history_layout.setContentsMargins(0, 0, 0, 0)
        self.history_layout.setSpacing(10)
        self.history_layout.addStretch(1)
        self.scroll_area.setWidget(self.history_root)
        history_card.content_layout.addWidget(self.scroll_area)
        layout.addWidget(history_card, 1)

        input_card = AppCard()
        self.input_edit = QPlainTextEdit()
        self.input_edit.setPlaceholderText("Ask AI about this page, selected data, schema, or request a safe operation plan.")
        self.input_edit.setFixedHeight(120)
        input_card.content_layout.addWidget(self.input_edit)
        buttons = QHBoxLayout()
        self.clear_button = SecondaryButton("Clear Chat")
        self.send_button = PrimaryButton("Send")
        buttons.addWidget(self.clear_button)
        buttons.addStretch(1)
        buttons.addWidget(self.send_button)
        input_card.content_layout.addLayout(buttons)
        layout.addWidget(input_card)

        self.clear_button.clicked.connect(self.clear_history)
        self.send_button.clicked.connect(self.send_message)
        self.collapse_button.clicked.connect(self.toggle_collapsed)

    def current_context_options(self) -> dict[str, bool]:
        return {
            "include_page_context": self.include_page_context.isChecked(),
            "include_schema": self.include_schema.isChecked(),
            "include_selected_row": self.include_selected_row.isChecked(),
            "include_result_sample": self.include_result_sample.isChecked(),
        }

    def clear_history(self) -> None:
        while self.history_layout.count() > 1:
            item = self.history_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def add_user_message(self, message: str) -> None:
        card = AIResponseCard("You", message, "primary")
        self.history_layout.insertWidget(self.history_layout.count() - 1, card)
        self._scroll_to_bottom()

    def add_response(self, response: dict[str, Any]) -> None:
        response_type = str(response.get("type") or "explanation")
        role_lookup = {
            "explanation": "primary",
            "filter_plan": "success",
            "write_proposal": "warning",
            "report_draft": "primary",
            "warning": "warning",
            "unsupported": "danger",
        }
        message = str(response.get("message") or "").strip()
        if response_type == "report_draft" and response.get("report_draft"):
            message = str(response["report_draft"])
        if response_type == "filter_plan" and response.get("filter_plan"):
            message = f"{message}\n\n{json.dumps(response['filter_plan'], ensure_ascii=False, indent=2)}"
        if response_type == "write_proposal" and response.get("write_proposal"):
            message = f"{message}\n\n{json.dumps(response['write_proposal'], ensure_ascii=False, indent=2)}"
        card = AIResponseCard(response_type.replace("_", " ").title(), message, role_lookup.get(response_type, "primary"))

        filter_plan = response.get("filter_plan")
        if isinstance(filter_plan, dict):
            apply_button = PrimaryButton("Apply Filter Plan")
            apply_button.clicked.connect(lambda: self.router.apply_filter_plan(filter_plan))
            card.add_action(apply_button)

        write_plan = response.get("write_plan")
        if write_plan is not None:
            review_button = PrimaryButton("Review Proposed Change")
            review_button.clicked.connect(lambda: self.router.review_write_plan(write_plan))
            card.add_action(review_button)

        report_text = response.get("report_draft")
        if report_text:
            copy_button = SecondaryButton("Copy Draft")
            copy_button.clicked.connect(lambda: self.window.copy_text_to_clipboard(str(report_text)))
            card.add_action(copy_button)

        self.history_layout.insertWidget(self.history_layout.count() - 1, card)
        self._scroll_to_bottom()

    def send_message(self) -> None:
        message = self.input_edit.toPlainText().strip()
        if not message:
            return
        self.add_user_message(message)
        self.input_edit.clear()
        page_context = self.window.current_ai_context(self.current_context_options())
        operator = AIOperator(self.window.selected_ollama_model)
        try:
            response = operator.operate(message, page_context)
            routed = self.router.route(response, page_context)
        except Exception as exc:
            routed = {
                "type": "warning",
                "message": f"AI error: {exc}",
                "filter_plan": None,
                "write_proposal": None,
                "report_draft": None,
                "confidence": "low",
                "requires_user_confirmation": False,
            }
        self.add_response(routed)

    def ask_from_page(self, message: str) -> None:
        self.input_edit.setPlainText(message)
        self.send_message()

    def set_collapsed(self, collapsed: bool) -> None:
        self.setVisible(not collapsed)
        self.window.ai_panel_collapsed = collapsed

    def toggle_collapsed(self) -> None:
        self.set_collapsed(not self.window.ai_panel_collapsed)
        self.window.sync_ai_panel_visibility()

    def _scroll_to_bottom(self) -> None:
        bar = self.scroll_area.verticalScrollBar()
        bar.setValue(bar.maximum())

