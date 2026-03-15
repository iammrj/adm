from __future__ import annotations

import hashlib

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)


class DownloadCard(QWidget):
    selected = pyqtSignal(str)
    pause_toggled = pyqtSignal(bool)
    delete_requested = pyqtSignal()

    def __init__(self, download_id: str, file_name: str, source_url: str, site: str, category: str) -> None:
        super().__init__()
        self.download_id = download_id
        self.file_name = file_name
        self.source_url = source_url
        self.site = site
        self.category = category
        self.is_completed = False
        self.md5_hash = hashlib.md5(f"{file_name}|{source_url}".encode("utf-8")).hexdigest()

        self.setObjectName("DownloadCard")
        self.setProperty("selected", False)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(124)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(8)

        header_layout = QHBoxLayout()
        header_layout.setSpacing(10)

        self.source_badge = QLabel(self._site_initials(site))
        self.source_badge.setObjectName("SourceBadge")
        self.source_badge.setStyleSheet(
            f"background-color: {self._site_color(site)}; color: #f8fafc; border-radius: 17px;"
        )
        self.source_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.source_badge.setFixedSize(34, 34)
        header_layout.addWidget(self.source_badge)

        title_layout = QVBoxLayout()
        title_layout.setSpacing(2)

        self.file_name_label = QLabel(file_name)
        self.file_name_label.setObjectName("FileName")
        self.file_name_label.setWordWrap(True)
        title_layout.addWidget(self.file_name_label)

        self.source_url_label = QLabel(source_url)
        self.source_url_label.setObjectName("SourceUrl")
        self.source_url_label.setWordWrap(True)
        title_layout.addWidget(self.source_url_label)

        header_layout.addLayout(title_layout, 1)
        root.addLayout(header_layout)

        self.progress_bar = QProgressBar()
        self.progress_bar.setObjectName("DownloadProgress")
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        root.addWidget(self.progress_bar)

        footer_layout = QHBoxLayout()
        footer_layout.setSpacing(12)

        self.speed_label = QLabel("Speed:")
        self.speed_label.setObjectName("MetaLabel")
        self.speed_value = QLabel("0.0 MB/s")
        self.speed_value.setObjectName("MetaValue")

        self.eta_label = QLabel("ETA:")
        self.eta_label.setObjectName("MetaLabel")
        self.eta_value = QLabel("-")
        self.eta_value.setObjectName("MetaValue")

        self.size_label = QLabel("Size:")
        self.size_label.setObjectName("MetaLabel")
        self.size_value = QLabel("0.0 MB")
        self.size_value.setObjectName("MetaValue")

        self.status_label = QLabel("Status:")
        self.status_label.setObjectName("MetaLabel")
        self.status_value = QLabel("Queued")
        self.status_value.setObjectName("MetaValue")

        footer_layout.addWidget(self.speed_label)
        footer_layout.addWidget(self.speed_value)
        footer_layout.addSpacing(8)
        footer_layout.addWidget(self.eta_label)
        footer_layout.addWidget(self.eta_value)
        footer_layout.addSpacing(8)
        footer_layout.addWidget(self.size_label)
        footer_layout.addWidget(self.size_value)
        footer_layout.addSpacing(8)
        footer_layout.addWidget(self.status_label)
        footer_layout.addWidget(self.status_value)
        footer_layout.addStretch(1)

        self.pause_button = QPushButton("Pause")
        self.pause_button.setObjectName("ActionButton")
        self.pause_button.setCheckable(True)
        self.pause_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.pause_button.toggled.connect(self._on_pause_toggled)

        self.delete_button = QPushButton("Delete")
        self.delete_button.setObjectName("DangerButton")
        self.delete_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.delete_button.clicked.connect(lambda: self.delete_requested.emit())

        footer_layout.addWidget(self.pause_button)
        footer_layout.addWidget(self.delete_button)
        root.addLayout(footer_layout)

    def update_progress(
        self,
        progress: int,
        speed: float | str,
        eta_text: str,
        size_text: str,
        status_text: str | None = None,
    ) -> None:
        if self.is_completed:
            return

        self.progress_bar.setValue(max(0, min(progress, 100)))
        self.size_value.setText(size_text)
        if isinstance(speed, (int, float)):
            self.speed_value.setText(f"{float(speed):.1f} MB/s")
        else:
            self.speed_value.setText(str(speed))
        self.eta_value.setText(eta_text)
        if status_text:
            self.status_value.setText(status_text)

    def mark_completed(self) -> None:
        self.is_completed = True
        self.progress_bar.setValue(100)
        self.speed_value.setText("Done")
        self.eta_value.setText("Completed")
        self.status_value.setText("Completed")
        self.pause_button.blockSignals(True)
        self.pause_button.setChecked(False)
        self.pause_button.blockSignals(False)
        self.pause_button.setEnabled(False)
        self.pause_button.setText("Done")

    def mark_stopped(self, reason: str = "Stopped") -> None:
        if self.is_completed:
            return
        self.status_value.setText(reason)
        self.speed_value.setText("stopped")
        self.eta_value.setText("n/a")
        self.pause_button.blockSignals(True)
        self.pause_button.setChecked(True)
        self.pause_button.setText("Resume")
        self.pause_button.blockSignals(False)
        self.pause_button.setEnabled(True)

    def mark_failed(self, reason: str = "Failed") -> None:
        if self.is_completed:
            return
        self.status_value.setText(reason)
        self.speed_value.setText("stopped")
        self.eta_value.setText("n/a")
        self.pause_button.blockSignals(True)
        self.pause_button.setChecked(True)
        self.pause_button.setText("Resume")
        self.pause_button.blockSignals(False)
        self.pause_button.setEnabled(True)

    def set_selected(self, selected: bool) -> None:
        self.setProperty("selected", selected)
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def details(self) -> dict[str, str]:
        return {
            "file_name": self.file_name,
            "url": self.source_url,
            "site": self.site,
            "size": self.size_value.text(),
            "md5": self.md5_hash,
            "status": self.status_value.text(),
        }

    def _on_pause_toggled(self, paused: bool) -> None:
        self.pause_button.setText("Resume" if paused else "Pause")
        self.pause_toggled.emit(paused)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.selected.emit(self.download_id)
        super().mousePressEvent(event)

    @staticmethod
    def _site_initials(site: str) -> str:
        compact = "".join(part[0] for part in site.split() if part)
        if not compact:
            return "NA"
        return compact[:2].upper()

    @staticmethod
    def _site_color(site: str) -> str:
        palette = ("#4f46e5", "#0ea5e9", "#14b8a6", "#f97316", "#84cc16", "#ec4899")
        index = sum(ord(c) for c in site) % len(palette)
        return palette[index]
