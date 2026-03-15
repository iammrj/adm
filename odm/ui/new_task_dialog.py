from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QDesktopServices, QResizeEvent
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from odm.core import default_output_dir
from odm.workers import AnalyzeUrlsThread


class ExpandingComboBox(QComboBox):
    EXTRA_WIDTH = 560
    HORIZONTAL_MARGIN = 36

    def showPopup(self) -> None:
        view = self.view()
        dialog = self.window()
        max_width = max(self.width(), dialog.width() - self.HORIZONTAL_MARGIN)
        target_width = min(max_width, self.width() + self.EXTRA_WIDTH)
        view.setMinimumWidth(target_width)
        view.setMaximumWidth(max_width)
        super().showPopup()


class NewTaskDialog(QDialog):
    def __init__(self, default_output: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("DownloadDialog")
        self.setWindowTitle("Download")
        self.setMinimumSize(1060, 720)
        self.resize(1120, 760)

        self._analysis_thread: AnalyzeUrlsThread | None = None
        self._analyzed_results: list[dict[str, Any]] = []
        self._download_drafts: list[dict[str, Any]] = []
        self._selected_single_option: dict[str, Any] | None = None
        self._analysis_signature: tuple[str, ...] = ()
        self._default_output = default_output or str(default_output_dir())

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(14)

        intro = QLabel(
            "Add one URL or a list of URLs, analyze them, select quality (for single URL), then click Download."
        )
        intro.setWordWrap(True)
        root.addWidget(intro)

        content_row = QHBoxLayout()
        content_row.setSpacing(14)

        left_col = QVBoxLayout()
        left_col.setSpacing(14)
        left_col.addWidget(self._build_single_url_group())
        left_col.addWidget(self._build_bulk_url_group(), 1)

        right_col = QVBoxLayout()
        right_col.setSpacing(14)
        right_col.addWidget(self._build_save_to_group())
        right_col.addWidget(self._build_format_group())
        right_col.addWidget(self._build_summary_group(), 1)

        content_row.addLayout(left_col, 4)
        content_row.addLayout(right_col, 7)
        root.addLayout(content_row, 1)

        self.status_label = QLabel("")
        self.status_label.setObjectName("MetaLabel")
        self.status_label.setVisible(False)
        root.addWidget(self.status_label)

        self.error_label = QLabel("")
        self.error_label.setObjectName("ErrorLabel")
        self.error_label.setVisible(False)
        root.addWidget(self.error_label)

        footer = QHBoxLayout()
        footer.addStretch(1)

        self.analyze_button = QPushButton("Analyze")
        self.analyze_button.setObjectName("PrimaryButton")
        self.analyze_button.clicked.connect(self._on_analyze_clicked)
        footer.addWidget(self.analyze_button)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.download_button = buttons.addButton("Download", QDialogButtonBox.ButtonRole.AcceptRole)
        self.download_button.setObjectName("PrimaryButton")
        self.download_button.clicked.connect(self._on_download_clicked)
        buttons.rejected.connect(self.reject)
        footer.addWidget(buttons)

        root.addLayout(footer)

    def _build_single_url_group(self) -> QWidget:
        group = QGroupBox("Single URL")
        layout = QVBoxLayout(group)
        layout.setContentsMargins(14, 16, 14, 14)
        layout.setSpacing(10)

        self.single_url_input = QLineEdit()
        self.single_url_input.setPlaceholderText("https://example.com/video")
        self.single_url_input.setMinimumHeight(36)
        self.single_url_input.textChanged.connect(self._on_urls_changed)

        hint = QLabel("Use this for one-off downloads where you may choose a specific quality.")
        hint.setObjectName("MetaLabel")
        hint.setWordWrap(True)

        layout.addWidget(self.single_url_input)
        layout.addWidget(hint)
        return group

    def _build_bulk_url_group(self) -> QWidget:
        group = QGroupBox("URL List")
        layout = QVBoxLayout(group)
        layout.setContentsMargins(14, 16, 14, 14)
        layout.setSpacing(10)

        self.bulk_urls_input = QTextEdit()
        self.bulk_urls_input.setPlaceholderText(
            "https://example.com/video1\nhttps://example.com/video2\nhttps://example.com/video3"
        )
        self.bulk_urls_input.setMinimumHeight(190)
        self.bulk_urls_input.textChanged.connect(self._on_urls_changed)

        self.bulk_hint = QLabel("")
        self.bulk_hint.setObjectName("MetaLabel")
        self.bulk_hint.setWordWrap(True)

        layout.addWidget(self.bulk_urls_input, 1)
        layout.addWidget(self.bulk_hint)
        self._update_bulk_hint(0)
        return group

    def _build_save_to_group(self) -> QWidget:
        group = QGroupBox("Save To")
        layout = QVBoxLayout(group)
        layout.setContentsMargins(14, 16, 14, 14)
        layout.setSpacing(10)

        row = QHBoxLayout()
        row.setSpacing(8)

        self.output_input = QLineEdit(self._default_output)
        self.output_input.setMinimumHeight(36)

        browse_btn = QPushButton("Browse")
        browse_btn.setObjectName("SecondaryButton")
        browse_btn.setMinimumHeight(36)
        browse_btn.clicked.connect(self._choose_output_dir)

        open_btn = QPushButton("Open")
        open_btn.setObjectName("SecondaryButton")
        open_btn.setMinimumHeight(36)
        open_btn.clicked.connect(self._open_output_dir)

        row.addWidget(self.output_input, 1)
        row.addWidget(browse_btn)
        row.addWidget(open_btn)

        hint = QLabel("ADM auto-creates category folders (Music, Video, Documents, etc.) inside this base folder.")
        hint.setObjectName("MetaLabel")
        hint.setWordWrap(True)

        layout.addLayout(row)
        layout.addWidget(hint)
        return group

    def _build_format_group(self) -> QWidget:
        group = QGroupBox("Format Selection")
        layout = QVBoxLayout(group)
        layout.setContentsMargins(14, 16, 14, 14)
        layout.setSpacing(10)

        self.format_combo = ExpandingComboBox()
        self.format_combo.setMinimumHeight(36)
        self.format_combo.setObjectName("FormatCombo")
        self.format_combo.setEnabled(False)
        self.format_combo.setMaxVisibleItems(10)
        self.format_combo.setMinimumContentsLength(28)
        self.format_combo.currentIndexChanged.connect(self._on_format_changed)

        self.selection_hint = QLabel("Analyze a single URL to pick quality from the dropdown.")
        self.selection_hint.setObjectName("MetaLabel")
        self.selection_hint.setWordWrap(True)

        self.format_detail_label = QLabel("")
        self.format_detail_label.setObjectName("MetaLabel")
        self.format_detail_label.setWordWrap(True)
        self.format_detail_label.setVisible(False)

        layout.addWidget(self.format_combo)
        layout.addWidget(self.selection_hint)
        layout.addWidget(self.format_detail_label)
        return group

    def _build_summary_group(self) -> QWidget:
        group = QGroupBox("Analyze Summary")
        layout = QVBoxLayout(group)
        layout.setContentsMargins(14, 16, 14, 14)
        layout.setSpacing(10)

        self.summary_output = QPlainTextEdit()
        self.summary_output.setReadOnly(True)
        self.summary_output.setMinimumHeight(220)
        self.summary_output.setPlaceholderText("Analysis results will appear here...")
        layout.addWidget(self.summary_output, 1)
        return group

    def _on_urls_changed(self) -> None:
        self._analysis_signature = ()
        self._analyzed_results.clear()
        self._download_drafts.clear()
        self._selected_single_option = None

        self.summary_output.clear()
        self.format_combo.clear()
        self.format_combo.setEnabled(False)
        self.format_detail_label.clear()
        self.format_detail_label.setVisible(False)
        self.selection_hint.setText("Analyze a single URL to pick quality from the dropdown.")
        self._update_bulk_hint(len(self._parse_urls()))

        self.status_label.clear()
        self.status_label.setVisible(False)
        self.error_label.clear()
        self.error_label.setVisible(False)

    def _choose_output_dir(self) -> None:
        selected = QFileDialog.getExistingDirectory(
            self,
            "Select Download Folder",
            self.output_input.text().strip() or str(default_output_dir()),
        )
        if selected:
            self.output_input.setText(selected)

    def _open_output_dir(self) -> None:
        target = Path(self.output_input.text().strip() or str(default_output_dir())).expanduser()
        target.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))

    def _is_valid_url(self, url: str) -> bool:
        parsed = urlparse(url.strip())
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)

    def _parse_urls(self) -> list[str]:
        ordered: list[str] = []
        seen: set[str] = set()

        candidates = [self.single_url_input.text().strip()]
        candidates.extend(line.strip() for line in self.bulk_urls_input.toPlainText().splitlines())

        for value in candidates:
            if not value:
                continue
            normalized = value if "://" in value else f"https://{value}"
            if not self._is_valid_url(normalized):
                continue
            if normalized in seen:
                continue
            seen.add(normalized)
            ordered.append(normalized)

        return ordered

    def _set_error(self, text: str) -> None:
        self.error_label.setText(text)
        self.error_label.setVisible(True)
        self.status_label.setVisible(False)

    def _set_status(self, text: str) -> None:
        self.status_label.setText(text)
        self.status_label.setVisible(True)
        self.error_label.setVisible(False)

    def _on_analyze_clicked(self) -> None:
        if self._analysis_thread is not None:
            return

        urls = self._parse_urls()
        if not urls:
            self._set_error("Enter at least one valid URL before analyzing.")
            return

        output_dir = self.output_input.text().strip()
        if not output_dir:
            self._set_error("Choose a base download folder.")
            return

        self.summary_output.clear()
        self.error_label.setVisible(False)
        include_options = len(urls) == 1

        self._analysis_thread = AnalyzeUrlsThread(urls, include_options=include_options)
        self._analysis_thread.succeeded.connect(self._on_analyze_succeeded)
        self._analysis_thread.failed.connect(self._on_analyze_failed)
        self._analysis_thread.finished.connect(self._on_analyze_finished)
        self._analysis_thread.start()

        self._set_status("Analyzing URL(s)...")

    def _on_analyze_succeeded(self, payload: dict[str, Any]) -> None:
        results = list(payload.get("results") or [])
        errors = list(payload.get("errors") or [])
        urls = self._parse_urls()
        self._analysis_signature = tuple(urls)
        self._analyzed_results = results

        summary_lines: list[str] = []
        for index, result in enumerate(results, start=1):
            title = str(result.get("title") or "download")
            mode = str(result.get("mode") or "segmented")
            size_label = str(result.get("size_label") or "unknown")
            if mode == "yt_dlp":
                option = result.get("selected_option") or {}
                label = str(option.get("label") or f"Best available | {size_label}")
                summary_lines.append(f"{index}. {title} -> {label}")
            else:
                summary_lines.append(f"{index}. {title} -> Direct download (format analysis unavailable)")

        self.summary_output.setPlainText("\n".join(summary_lines))

        self.format_combo.clear()
        if len(results) == 1:
            options = list(results[0].get("options") or [])
            if options:
                for option in options:
                    compact_label = self._compact_option_label(option)
                    self.format_combo.addItem(compact_label, option)
                    self.format_combo.setItemData(
                        self.format_combo.count() - 1,
                        str(option.get("label") or compact_label),
                        Qt.ItemDataRole.ToolTipRole,
                    )
                self.format_combo.setEnabled(True)
                self._selected_single_option = options[0]
                self.selection_hint.setText("Default is best quality. Use dropdown arrow to select another quality.")
                self._set_format_detail(options[0])
            else:
                self.format_combo.addItem("Direct download")
                self.format_combo.setEnabled(False)
                self.selection_hint.setText("No format list available. Download will use direct mode.")
                self.format_detail_label.clear()
                self.format_detail_label.setVisible(False)
        else:
            self.format_combo.addItem("Best available per URL")
            self.format_combo.setEnabled(False)
            self.selection_hint.setText("Multiple URLs use best available format automatically.")
            self.format_detail_label.clear()
            self.format_detail_label.setVisible(False)

        if errors:
            self._set_status(f"Analyze completed with {len(errors)} fallback(s). Some URLs may use direct mode.")
        else:
            self._set_status(f"Analyze complete for {len(results)} URL(s). Click Download to start.")

    def _on_analyze_failed(self, message: str) -> None:
        self._set_error(f"Analyze failed: {message}")

    def _on_analyze_finished(self) -> None:
        self._analysis_thread = None

    def _on_format_changed(self, index: int) -> None:
        if index < 0:
            return
        data = self.format_combo.itemData(index)
        if isinstance(data, dict):
            self._selected_single_option = data
            self._set_format_detail(data)

    def _on_download_clicked(self) -> None:
        urls = self._parse_urls()
        if not urls:
            self._set_error("Enter at least one valid URL.")
            return

        output_text = self.output_input.text().strip()
        if not output_text:
            self._set_error("Choose a base download folder.")
            return

        if tuple(urls) != self._analysis_signature or not self._analyzed_results:
            self._set_error("Click Analyze first, then click Download.")
            return

        self._download_drafts = []
        for result in self._analyzed_results:
            mode = str(result.get("mode") or "segmented")
            selected_option = result.get("selected_option")

            if len(self._analyzed_results) == 1 and self._selected_single_option is not None:
                selected_option = self._selected_single_option

            draft = {
                "url": str(result.get("url") or ""),
                "title": str(result.get("title") or "download"),
                "mode": mode,
                "headers": result.get("headers") if isinstance(result.get("headers"), dict) else None,
                "format_id": selected_option.get("format_id") if isinstance(selected_option, dict) else None,
                "size_label": selected_option.get("size_label", result.get("size_label", "unknown"))
                if isinstance(selected_option, dict)
                else str(result.get("size_label") or "unknown"),
                "stream_type": selected_option.get("stream_type") if isinstance(selected_option, dict) else result.get("stream_type"),
            }
            self._download_drafts.append(draft)

        self.accept()

    def selected_output_dir(self) -> str:
        return self.output_input.text().strip() or str(default_output_dir())

    def get_download_drafts(self) -> list[dict[str, Any]]:
        return list(self._download_drafts)

    def _compact_option_label(self, option: dict[str, Any]) -> str:
        raw_label = str(option.get("label") or "Best available")
        parts = [part.strip() for part in raw_label.split("|")]
        if len(parts) >= 4:
            return f"{parts[0]} • {parts[1]} • {parts[3]}"
        return raw_label

    def _set_format_detail(self, option: dict[str, Any]) -> None:
        full_label = str(option.get("label") or "")
        if not full_label:
            self.format_detail_label.clear()
            self.format_detail_label.setVisible(False)
            return
        self.format_detail_label.setText(f"Selected: {full_label}")
        self.format_detail_label.setVisible(True)

    def _update_bulk_hint(self, url_count: int) -> None:
        compact = self.width() < 1140
        if url_count <= 1:
            text = "Add one URL per line. Duplicate URLs are skipped automatically."
            if compact:
                text = "One URL per line.\nDuplicate URLs are skipped."
        else:
            text = f"{url_count} URLs ready. ADM will use best available quality for each URL."
        self.bulk_hint.setText(text)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._update_bulk_hint(len(self._parse_urls()))
