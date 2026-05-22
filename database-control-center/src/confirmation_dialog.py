from __future__ import annotations

import json
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QDialog, QDialogButtonBox, QLabel, QPlainTextEdit, QVBoxLayout, QWidget

from src.ui_styles import ModernMessageBanner, SectionHeader
from src.write_guard import WriteActionPlan, create_confirmation_token, plan_to_preview_data


def _diff_text(before_data: Any, after_data: Any) -> str:
    if not isinstance(before_data, dict) or not isinstance(after_data, dict):
        return json.dumps({"before": before_data, "after": after_data}, ensure_ascii=False, indent=2, default=str)
    lines: list[str] = []
    keys = sorted(set(before_data) | set(after_data))
    for key in keys:
        before_value = before_data.get(key)
        after_value = after_data.get(key)
        if before_value != after_value:
            lines.append(f"{key}: {before_value!r} -> {after_value!r}")
    return "\n".join(lines) if lines else "No field-level difference detected."


class ConfirmationPreviewDialog(QDialog):
    def __init__(self, plan: WriteActionPlan, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.plan = plan
        self.confirmation_token: str | None = None
        self.setWindowTitle("Review Database Change")
        self.setModal(True)
        self.resize(760, 680)

        layout = QVBoxLayout(self)
        layout.addWidget(SectionHeader("Review Database Change", "This action will modify the active database."))
        layout.addWidget(ModernMessageBanner("AI writes require approval. Press Cancel if anything looks wrong.", "warning"))

        preview_data = plan_to_preview_data(plan)
        meta_text = (
            f"Database: {preview_data['database_name']}\n"
            f"Database type: {preview_data['database_type']}\n"
            f"Table: {preview_data['table'] or 'audit_log'}\n"
            f"Action: {preview_data['action']}\n"
            f"Primary key: {preview_data['primary_key_column']} = {preview_data['primary_key_value']}\n"
            f"Risk level: {preview_data['risk_level']}\n"
            f"Source: {preview_data['source']}\n"
            f"Reason: {preview_data['reason']}"
        )
        meta_block = QPlainTextEdit()
        meta_block.setReadOnly(True)
        meta_block.setPlainText(meta_text)
        layout.addWidget(meta_block)

        before_after = QPlainTextEdit()
        before_after.setReadOnly(True)
        before_after.setPlainText(
            json.dumps(
                {
                    "before_data": preview_data["before_data"],
                    "after_data": preview_data["after_data"],
                    "rows": plan.rows[:20],
                    "diff": _diff_text(preview_data["before_data"], preview_data["after_data"]),
                },
                ensure_ascii=False,
                indent=2,
                default=str,
            )
        )
        layout.addWidget(QLabel("Preview"))
        layout.addWidget(before_after, 1)

        self.approval_checkbox = QCheckBox("I understand and approve this database change.")
        layout.addWidget(self.approval_checkbox)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Cancel)
        self.approve_button = self.buttons.addButton("Approve and Execute", QDialogButtonBox.AcceptRole)
        self.approve_button.setAutoDefault(False)
        self.approve_button.setDefault(False)
        cancel_button = self.buttons.button(QDialogButtonBox.Cancel)
        if cancel_button is not None:
            cancel_button.setDefault(True)
            cancel_button.setAutoDefault(True)
        layout.addWidget(self.buttons)

        self.buttons.rejected.connect(self.reject)
        self.approve_button.clicked.connect(self._approve)

    def _approve(self) -> None:
        if not self.approval_checkbox.isChecked():
            return
        self.confirmation_token = create_confirmation_token(self.plan)
        self.accept()

