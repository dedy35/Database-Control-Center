from __future__ import annotations

from contextlib import contextmanager

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QProgressDialog, QWidget


def floating_spinner_css() -> str:
    return (
        "QProgressDialog {"
        " background-color: #1f2933;"
        " color: #f8fafc;"
        " border: 1px solid #475569;"
        " border-radius: 10px;"
        "}"
        "QProgressDialog QLabel {"
        " color: #f8fafc;"
        " font-size: 13px;"
        " min-width: 240px;"
        "}"
    )


def show_loading_overlay(message: str = "Processing...", parent: QWidget | None = None) -> QProgressDialog:
    dialog = QProgressDialog(message, "", 0, 0, parent)
    dialog.setWindowTitle("Please wait")
    dialog.setWindowModality(Qt.ApplicationModal if parent is not None else Qt.NonModal)
    dialog.setCancelButton(None)
    dialog.setMinimumDuration(0)
    dialog.setAutoClose(False)
    dialog.setAutoReset(False)
    dialog.setWindowFlag(Qt.WindowCloseButtonHint, False)
    dialog.setStyleSheet(floating_spinner_css())
    dialog.show()
    QApplication.processEvents()
    return dialog


def loading_placeholder(message: str = "Processing...", parent: QWidget | None = None) -> QProgressDialog:
    return show_loading_overlay(message=message, parent=parent)


@contextmanager
def loading_operation(message: str = "Processing...", parent: QWidget | None = None):
    dialog = show_loading_overlay(message=message, parent=parent)
    try:
        yield dialog
    finally:
        dialog.close()
        dialog.deleteLater()
        QApplication.processEvents()

