from __future__ import annotations

from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget


APP_STYLE_SHEET = """
QMainWindow, QWidget {
    background-color: #F5F7FA;
    color: #1F2937;
    font-family: "Segoe UI";
    font-size: 12px;
}
QMenuBar {
    background-color: #F5F7FA;
    border-bottom: 1px solid #E5E7EB;
}
QStatusBar {
    background-color: #FFFFFF;
    border-top: 1px solid #E5E7EB;
    color: #6B7280;
}
QFrame[card="true"], QGroupBox {
    background-color: #FFFFFF;
    border: 1px solid #E5E7EB;
    border-radius: 16px;
}
QGroupBox {
    margin-top: 12px;
    padding: 16px 16px 12px 16px;
    font-weight: 600;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 16px;
    padding: 0 4px 0 4px;
    color: #374151;
}
QListWidget {
    background-color: #FFFFFF;
    border: 1px solid #E5E7EB;
    border-radius: 18px;
    outline: none;
    padding: 10px;
}
QListWidget::item {
    margin: 4px 0;
    padding: 12px 14px;
    border-radius: 12px;
    color: #374151;
}
QListWidget::item:selected {
    background-color: #E8F1FF;
    color: #007AFF;
    font-weight: 600;
}
QPushButton {
    min-height: 34px;
    padding: 8px 14px;
    border-radius: 14px;
    border: 1px solid #D1D5DB;
    background-color: #FFFFFF;
    color: #1F2937;
}
QPushButton:hover {
    background-color: #F9FAFB;
}
QPushButton:pressed {
    background-color: #EEF2F7;
}
QPushButton[role="primary"] {
    background-color: #007AFF;
    border: 1px solid #007AFF;
    color: #FFFFFF;
}
QPushButton[role="primary"]:hover {
    background-color: #167FFB;
}
QPushButton[role="danger"] {
    background-color: #FEE2E2;
    border: 1px solid #FCA5A5;
    color: #B91C1C;
}
QPushButton[role="secondary"] {
    background-color: #F3F4F6;
    border: 1px solid #E5E7EB;
    color: #374151;
}
QLineEdit, QPlainTextEdit, QComboBox, QSpinBox, QDateEdit, QTableView {
    background-color: #FFFFFF;
    border: 1px solid #D1D5DB;
    border-radius: 12px;
    padding: 8px 10px;
}
QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus, QSpinBox:focus, QDateEdit:focus {
    border: 1px solid #007AFF;
}
QTableView {
    alternate-background-color: #F9FAFB;
    gridline-color: #E5E7EB;
    selection-background-color: #DCEEFF;
    selection-color: #111827;
}
QHeaderView::section {
    background-color: #F8FAFC;
    border: none;
    border-bottom: 1px solid #E5E7EB;
    padding: 8px;
    color: #6B7280;
    font-weight: 600;
}
QCheckBox {
    spacing: 8px;
}
QSplitter::handle {
    background-color: #E5E7EB;
}
QLabel[muted="true"] {
    color: #6B7280;
}
QLabel[pill="true"] {
    background-color: #EEF2FF;
    color: #374151;
    border: 1px solid #DDE6F5;
    border-radius: 999px;
    padding: 6px 10px;
    font-weight: 600;
}
QLabel[pillRole="success"] {
    background-color: #DCFCE7;
    color: #166534;
    border: 1px solid #86EFAC;
}
QLabel[pillRole="warning"] {
    background-color: #FEF3C7;
    color: #92400E;
    border: 1px solid #FCD34D;
}
QLabel[pillRole="danger"] {
    background-color: #FEE2E2;
    color: #991B1B;
    border: 1px solid #FCA5A5;
}
QLabel[pillRole="primary"] {
    background-color: #DBEAFE;
    color: #1D4ED8;
    border: 1px solid #93C5FD;
}
"""


class AppCard(QFrame):
    def __init__(self, title: str | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("card", True)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(18, 18, 18, 18)
        self._layout.setSpacing(12)
        if title:
            self._layout.addWidget(SectionHeader(title))

    @property
    def content_layout(self) -> QVBoxLayout:
        return self._layout


class SectionHeader(QWidget):
    def __init__(self, title: str, subtitle: str | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        title_label = QLabel(title)
        title_label.setStyleSheet("font-size: 16px; font-weight: 700; color: #111827;")
        layout.addWidget(title_label)
        if subtitle:
            subtitle_label = QLabel(subtitle)
            subtitle_label.setProperty("muted", True)
            subtitle_label.setWordWrap(True)
            layout.addWidget(subtitle_label)


class PillBadge(QLabel):
    def __init__(self, text: str, role: str = "primary", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setProperty("pill", True)
        self.setProperty("pillRole", role)


class PrimaryButton(QPushButton):
    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setProperty("role", "primary")


class SecondaryButton(QPushButton):
    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setProperty("role", "secondary")


class DangerButton(QPushButton):
    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setProperty("role", "danger")


class EmptyStateWidget(QFrame):
    def __init__(self, title: str, message: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("card", True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 24, 20, 24)
        layout.setSpacing(8)
        heading = QLabel(title)
        heading.setStyleSheet("font-size: 15px; font-weight: 700; color: #111827;")
        body = QLabel(message)
        body.setWordWrap(True)
        body.setProperty("muted", True)
        layout.addWidget(heading)
        layout.addWidget(body)


class ModernMessageBanner(QFrame):
    def __init__(self, message: str, role: str = "primary", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        colors = {
            "primary": ("#DBEAFE", "#1D4ED8", "#93C5FD"),
            "success": ("#DCFCE7", "#166534", "#86EFAC"),
            "warning": ("#FEF3C7", "#92400E", "#FCD34D"),
            "danger": ("#FEE2E2", "#991B1B", "#FCA5A5"),
        }
        background, text_color, border = colors.get(role, colors["primary"])
        self.setStyleSheet(
            f"QFrame {{ background-color: {background}; border: 1px solid {border}; border-radius: 14px; }}"
            f"QLabel {{ color: {text_color}; }}"
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        label = QLabel(message)
        label.setWordWrap(True)
        layout.addWidget(label)


class ModernSearchInput(QLineEdit):
    def __init__(self, placeholder: str = "Search", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setPlaceholderText(placeholder)
        self.setClearButtonEnabled(True)


class ModernTableToolbar(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("card", True)
        self.layout_root = QHBoxLayout(self)
        self.layout_root.setContentsMargins(12, 12, 12, 12)
        self.layout_root.setSpacing(8)


def apply_light_style(app) -> None:
    app.setStyleSheet(APP_STYLE_SHEET)

