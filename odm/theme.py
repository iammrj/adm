from __future__ import annotations

from pathlib import Path

from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QApplication


THEME_FILES = {
    "dark": "dark_theme.qss",
    "light": "light_theme.qss",
}


def load_qss(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def load_theme_qss(theme_name: str, base_dir: Path | None = None) -> str:
    normalized = theme_name.lower().strip()
    file_name = THEME_FILES.get(normalized, THEME_FILES["dark"])

    theme_dir = (base_dir or Path(__file__).resolve().parent) / "theme"
    return load_qss(theme_dir / file_name)


def compose_runtime_qss(base_qss: str, font_size: int) -> str:
    base = max(10, min(font_size, 18))
    menu_size = max(base - 1, 9)
    input_size = min(base + 1, 22)
    caption_size = max(base - 1, 9)
    title_size = min(base + 2, 24)
    badge_size = max(base - 1, 10)

    runtime_overrides = f"""
QWidget {{
    font-size: {base}px;
}}
QMenuBar, QMenu {{
    font-size: {menu_size}px;
}}
QListWidget#NavList {{
    font-size: {base}px;
}}
QPushButton, QToolButton {{
    font-size: {base}px;
}}
QLineEdit#SearchInput,
QDialog QLineEdit,
QDialog QTextEdit,
QDialog QPlainTextEdit,
QDialog QComboBox {{
    font-size: {input_size}px;
}}
QDialog QComboBox QAbstractItemView {{
    font-size: {input_size}px;
}}
QLabel#MetaLabel,
QLabel#MetaValue,
QLabel#InspectorValue,
QLabel#SourceUrl {{
    font-size: {caption_size}px;
}}
QLabel#FileName,
QLabel#InspectorTitle {{
    font-size: {title_size}px;
}}
QLabel#SourceBadge {{
    font-size: {badge_size}px;
}}
"""
    return f"{base_qss}\n{runtime_overrides}\n"


def apply_app_appearance(
    app: QApplication,
    *,
    theme_name: str,
    font_family: str,
    font_size: int,
) -> None:
    app.setFont(QFont(font_family, max(8, min(font_size, 24))))
    base_qss = load_theme_qss(theme_name)
    app.setStyleSheet(compose_runtime_qss(base_qss, font_size))
