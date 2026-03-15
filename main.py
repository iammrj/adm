from pathlib import Path
import sys

from PyQt6.QtCore import QSettings
from PyQt6.QtGui import QFontDatabase, QIcon
from PyQt6.QtWidgets import QApplication

from odm.core import ensure_ssl_certificates
from odm.theme import THEME_FILES, apply_app_appearance
from odm.ui.main_window import MainWindow


PREFERRED_FONT_FAMILIES = (
    "Inter",
    "SF Pro Text",
    "Segoe UI",
    "Helvetica Neue",
    "Arial",
    "Noto Sans",
    "DejaVu Sans",
)
MIN_FONT_SIZE = 10
MAX_FONT_SIZE = 18


def resolve_default_font_family() -> str:
    available = set(QFontDatabase.families())
    for family in PREFERRED_FONT_FAMILIES:
        if family in available:
            return family
    system_family = QFontDatabase.systemFont(QFontDatabase.SystemFont.GeneralFont).family().strip()
    return system_family or "Arial"


def resolve_default_font_size(app: QApplication) -> int:
    screen = app.primaryScreen()
    if screen is None:
        return 11
    return 12 if screen.availableGeometry().height() >= 980 else 11


def read_appearance_settings(app: QApplication) -> tuple[str, str, int]:
    default_theme = "dark"
    default_family = resolve_default_font_family()
    default_size = resolve_default_font_size(app)

    settings = QSettings()
    raw_theme = str(settings.value("appearance/theme", default_theme) or default_theme).strip().lower()
    theme_name = raw_theme if raw_theme in THEME_FILES else default_theme

    raw_family = str(settings.value("appearance/font_family", default_family) or default_family).strip()
    font_family = raw_family if raw_family in set(QFontDatabase.families()) else default_family

    raw_size = settings.value("appearance/font_size", default_size)
    try:
        font_size = int(raw_size)
    except (TypeError, ValueError):
        font_size = default_size
    font_size = max(MIN_FONT_SIZE, min(font_size, MAX_FONT_SIZE))
    return theme_name, font_family, font_size


def main() -> None:
    ensure_ssl_certificates()
    app = QApplication(sys.argv)
    app.setOrganizationName("ADM")
    app.setApplicationName("Apex Download Manager")

    icon_path = Path(__file__).resolve().parent / "assets" / "icons" / "adm.png"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    theme_name, font_family, font_size = read_appearance_settings(app)
    apply_app_appearance(
        app,
        theme_name=theme_name,
        font_family=font_family,
        font_size=font_size,
    )

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
