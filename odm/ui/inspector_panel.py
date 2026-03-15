from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class InspectorPanel(QWidget):
    collapse_requested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("InspectorPanel")

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)

        self.title_label = QLabel("Inspector")
        self.title_label.setObjectName("InspectorTitle")
        header.addWidget(self.title_label)
        header.addStretch(1)

        self.collapse_button = QPushButton("Collapse")
        self.collapse_button.setObjectName("SecondaryButton")
        self.collapse_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.collapse_button.clicked.connect(lambda: self.collapse_requested.emit())
        header.addWidget(self.collapse_button)

        root.addLayout(header)

        details_group = QGroupBox("File Details")
        details_group.setObjectName("InspectorGroup")
        details_layout = QFormLayout(details_group)
        details_layout.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)

        self.file_name_value = QLabel("-")
        self.file_name_value.setObjectName("InspectorValue")
        self.file_name_value.setWordWrap(True)

        self.site_value = QLabel("-")
        self.site_value.setObjectName("InspectorValue")
        self.url_value = QLabel("-")
        self.url_value.setObjectName("InspectorValue")
        self.url_value.setWordWrap(True)
        self.size_value = QLabel("-")
        self.size_value.setObjectName("InspectorValue")
        self.status_value = QLabel("-")
        self.status_value.setObjectName("InspectorValue")

        details_layout.addRow("Name:", self.file_name_value)
        details_layout.addRow("Site:", self.site_value)
        details_layout.addRow("URL:", self.url_value)
        details_layout.addRow("Size:", self.size_value)
        details_layout.addRow("Status:", self.status_value)
        root.addWidget(details_group)

        hash_group = QGroupBox("MD5 Hash")
        hash_group.setObjectName("InspectorGroup")
        hash_layout = QVBoxLayout(hash_group)
        self.hash_value = QLabel("-")
        self.hash_value.setObjectName("InspectorValue")
        self.hash_value.setWordWrap(True)
        self.hash_value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        hash_layout.addWidget(self.hash_value)
        root.addWidget(hash_group)

        actions_group = QGroupBox("Post-download actions")
        actions_group.setObjectName("InspectorGroup")
        actions_layout = QVBoxLayout(actions_group)
        self.shutdown_checkbox = QCheckBox("Shutdown")
        self.open_folder_checkbox = QCheckBox("Open Folder")
        actions_layout.addWidget(self.shutdown_checkbox)
        actions_layout.addWidget(self.open_folder_checkbox)
        root.addWidget(actions_group)

        root.addStretch(1)

    def update_details(self, details: dict[str, str]) -> None:
        self.file_name_value.setText(details.get("file_name", "-"))
        self.site_value.setText(details.get("site", "-"))
        self.url_value.setText(details.get("url", "-"))
        self.size_value.setText(details.get("size", "-"))
        self.status_value.setText(details.get("status", "-"))
        self.hash_value.setText(details.get("md5", "-"))

    def clear(self) -> None:
        self.update_details({})
