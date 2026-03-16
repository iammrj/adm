from __future__ import annotations

from collections import deque
from pathlib import Path
from typing import Any

from PyQt6.QtCore import QSize, QSettings, QTimer, Qt, QUrl
from PyQt6.QtGui import QAction, QActionGroup, QCloseEvent, QDesktopServices, QFontDatabase, QGuiApplication, QKeySequence
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLineEdit,
    QListWidgetItem,
    QListWidget,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from odm.core import category_output_dir, default_output_dir, format_filesize, guess_category, source_host, title_from_url
from odm.storage import JobStore, default_job_db_path
from odm.theme import THEME_FILES, apply_app_appearance
from odm.ui.download_card import DownloadCard
from odm.ui.inspector_panel import InspectorPanel
from odm.ui.new_task_dialog import NewTaskDialog
from odm.workers import DownloadWorkerThread


class MainWindow(QMainWindow):
    APP_VERSION = "1.0.0"
    DEVELOPER_NAME = "Jilani Shaik"
    PROFILE_URL = "https://github.com/iammrj"
    REPO_URL = "https://github.com/iammrj/adm"

    NAV_ITEMS = (
        "All Downloads",
        "Music",
        "Video",
        "Documents",
        "Programs",
        "Compressed",
        "Queued",
        "Completed",
        "Failed",
    )
    NAV_ICONS: dict[str, QStyle.StandardPixmap] = {
        "All Downloads": QStyle.StandardPixmap.SP_DirHomeIcon,
        "Music": QStyle.StandardPixmap.SP_MediaVolume,
        "Video": QStyle.StandardPixmap.SP_MediaPlay,
        "Documents": QStyle.StandardPixmap.SP_FileIcon,
        "Programs": QStyle.StandardPixmap.SP_ComputerIcon,
        "Compressed": QStyle.StandardPixmap.SP_DriveFDIcon,
        "Queued": QStyle.StandardPixmap.SP_BrowserReload,
        "Completed": QStyle.StandardPixmap.SP_DialogApplyButton,
        "Failed": QStyle.StandardPixmap.SP_MessageBoxCritical,
    }
    FONT_CANDIDATES = (
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

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Apex Download Manager")
        self.setMinimumSize(960, 640)

        self.cards: dict[str, DownloadCard] = {}
        self.jobs: dict[str, dict[str, Any]] = {}
        self.pending_queue: deque[str] = deque()
        self.active_workers: dict[str, DownloadWorkerThread] = {}
        self.selected_download_id: str | None = None

        self.max_parallel_downloads = 3
        self.segment_connections = 4
        self.timeout_seconds = 30
        self.next_job_index = 1
        self.default_output_dir_text = str(default_output_dir())
        self.settings = QSettings()
        self.font_options = self._available_font_families()
        self.theme_name = self._read_theme_setting()
        self.font_size = self._read_font_size_setting()
        self.font_family = self._read_font_family_setting()
        self.theme_actions: dict[str, QAction] = {}
        self.font_actions: dict[str, QAction] = {}

        self.job_store = JobStore(default_job_db_path())
        self.job_store.recover_interrupted_jobs()

        self._build_menu_bar()
        self._build_ui()
        self._sync_appearance_actions()
        self._apply_initial_window_geometry()
        self._restore_jobs_from_store()
        self.apply_filters()
        self._start_next_downloads()

    def _available_font_families(self) -> list[str]:
        available = set(QFontDatabase.families())
        choices = [family for family in self.FONT_CANDIDATES if family in available]
        if not choices:
            fallback = QFontDatabase.systemFont(QFontDatabase.SystemFont.GeneralFont).family().strip()
            if fallback:
                choices.append(fallback)
        return choices or ["Arial"]

    def _read_theme_setting(self) -> str:
        value = str(self.settings.value("appearance/theme", "dark") or "dark").strip().lower()
        return value if value in THEME_FILES else "dark"

    def _read_font_size_setting(self) -> int:
        app = QApplication.instance()
        default_size = 11
        if app is not None and app.font().pointSize() > 0:
            default_size = app.font().pointSize()
        raw_value = self.settings.value("appearance/font_size", default_size)
        try:
            parsed = int(raw_value)
        except (TypeError, ValueError):
            parsed = default_size
        return max(self.MIN_FONT_SIZE, min(parsed, self.MAX_FONT_SIZE))

    def _read_font_family_setting(self) -> str:
        fallback = self.font_options[0]
        configured = str(self.settings.value("appearance/font_family", fallback) or fallback).strip()
        return configured if configured in self.font_options else fallback

    def _apply_initial_window_geometry(self) -> None:
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            self.resize(1240, 820)
            return

        available = screen.availableGeometry()
        width = max(self.minimumWidth(), int(available.width() * 0.9))
        height = max(self.minimumHeight(), int(available.height() * 0.9))
        width = min(width, available.width())
        height = min(height, available.height())

        self.resize(width, height)
        self.move(
            available.x() + (available.width() - width) // 2,
            available.y() + (available.height() - height) // 2,
        )

    def _refresh_nav_list_height(self) -> None:
        if not hasattr(self, "nav_list"):
            return
        row_height = self.nav_list.sizeHintForRow(0)
        if row_height <= 0:
            row_height = 36
        total_height = (row_height + self.nav_list.spacing()) * self.nav_list.count() + 6
        self.nav_list.setFixedHeight(total_height)

    def _apply_and_persist_appearance(self) -> None:
        app = QApplication.instance()
        if app is None:
            return

        apply_app_appearance(
            app,
            theme_name=self.theme_name,
            font_family=self.font_family,
            font_size=self.font_size,
        )
        self.settings.setValue("appearance/theme", self.theme_name)
        self.settings.setValue("appearance/font_family", self.font_family)
        self.settings.setValue("appearance/font_size", self.font_size)
        self._sync_appearance_actions()
        QTimer.singleShot(0, self._refresh_nav_list_height)

    def _set_theme(self, theme_name: str) -> None:
        normalized = theme_name.lower().strip()
        if normalized not in THEME_FILES or normalized == self.theme_name:
            return
        self.theme_name = normalized
        self._apply_and_persist_appearance()

    def _set_font_family(self, family: str) -> None:
        selected = family.strip()
        if selected not in self.font_options or selected == self.font_family:
            return
        self.font_family = selected
        self._apply_and_persist_appearance()

    def _change_font_size(self, delta: int) -> None:
        updated = max(self.MIN_FONT_SIZE, min(self.font_size + delta, self.MAX_FONT_SIZE))
        if updated == self.font_size:
            return
        self.font_size = updated
        self._apply_and_persist_appearance()

    def _reset_font_size(self) -> None:
        if self.font_size == 11:
            return
        self.font_size = 11
        self._apply_and_persist_appearance()

    def _sync_appearance_actions(self) -> None:
        for theme_name, action in self.theme_actions.items():
            action.blockSignals(True)
            action.setChecked(theme_name == self.theme_name)
            action.blockSignals(False)

        for family, action in self.font_actions.items():
            action.blockSignals(True)
            action.setChecked(family == self.font_family)
            action.blockSignals(False)

    def _build_menu_bar(self) -> None:
        menu_bar = self.menuBar()

        file_menu = menu_bar.addMenu("File")
        download_action = QAction("Download", self)
        download_action.setShortcut(QKeySequence.StandardKey.New)
        download_action.triggered.connect(self.open_download_dialog)
        file_menu.addAction(download_action)

        open_folder_action = QAction("Open Downloads Folder", self)
        open_folder_action.triggered.connect(self.open_output_location)
        file_menu.addAction(open_folder_action)

        file_menu.addSeparator()
        quit_action = QAction("Quit", self)
        quit_action.setShortcut(QKeySequence.StandardKey.Quit)
        quit_action.triggered.connect(lambda: self.close())
        file_menu.addAction(quit_action)

        downloads_menu = menu_bar.addMenu("Downloads")
        new_download_action = QAction("Download", self)
        new_download_action.setShortcut("Ctrl+D")
        new_download_action.triggered.connect(self.open_download_dialog)
        downloads_menu.addAction(new_download_action)

        downloads_menu.addSeparator()
        pause_all_action = QAction("Pause All", self)
        pause_all_action.setShortcut("Ctrl+Shift+P")
        pause_all_action.triggered.connect(self.pause_all_downloads)
        downloads_menu.addAction(pause_all_action)

        resume_all_action = QAction("Resume All", self)
        resume_all_action.setShortcut("Ctrl+Shift+R")
        resume_all_action.triggered.connect(self.resume_all_downloads)
        downloads_menu.addAction(resume_all_action)

        downloads_menu.addSeparator()
        clear_completed_action = QAction("Clear Completed", self)
        clear_completed_action.triggered.connect(self.clear_completed_downloads)
        downloads_menu.addAction(clear_completed_action)

        view_menu = menu_bar.addMenu("View")
        self.show_inspector_action = QAction("Show Inspector Panel", self)
        self.show_inspector_action.setCheckable(True)
        self.show_inspector_action.setChecked(True)
        self.show_inspector_action.toggled.connect(self.set_inspector_visible)
        view_menu.addAction(self.show_inspector_action)

        appearance_menu = menu_bar.addMenu("Appearance")

        theme_menu = appearance_menu.addMenu("Theme")
        theme_group = QActionGroup(self)
        theme_group.setExclusive(True)
        for theme_name in ("dark", "light"):
            label = theme_name.title()
            action = QAction(label, self)
            action.setCheckable(True)
            action.triggered.connect(lambda checked=False, selected=theme_name: self._set_theme(selected))
            theme_group.addAction(action)
            theme_menu.addAction(action)
            self.theme_actions[theme_name] = action

        font_menu = appearance_menu.addMenu("Font")
        font_group = QActionGroup(self)
        font_group.setExclusive(True)
        for family in self.font_options:
            action = QAction(family, self)
            action.setCheckable(True)
            action.triggered.connect(lambda checked=False, selected=family: self._set_font_family(selected))
            font_group.addAction(action)
            font_menu.addAction(action)
            self.font_actions[family] = action

        appearance_menu.addSeparator()
        font_up_action = QAction("Increase Font Size", self)
        font_up_action.setShortcuts([QKeySequence("Ctrl+="), QKeySequence("Ctrl++")])
        font_up_action.triggered.connect(lambda: self._change_font_size(1))
        appearance_menu.addAction(font_up_action)

        font_down_action = QAction("Decrease Font Size", self)
        font_down_action.setShortcut(QKeySequence("Ctrl+-"))
        font_down_action.triggered.connect(lambda: self._change_font_size(-1))
        appearance_menu.addAction(font_down_action)

        reset_font_action = QAction("Reset Font Size", self)
        reset_font_action.triggered.connect(self._reset_font_size)
        appearance_menu.addAction(reset_font_action)

        help_menu = menu_bar.addMenu("Help")
        about_action = QAction("About ADM", self)
        about_action.triggered.connect(self._show_about_dialog)
        help_menu.addAction(about_action)

    def _show_about_dialog(self) -> None:
        dialog = QDialog(self)
        dialog.setObjectName("AboutDialog")
        dialog.setWindowTitle("About ADM")
        dialog.setModal(True)
        dialog.setMinimumWidth(460)
        dialog.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        icon_label = QLabel()
        app_icon = QApplication.windowIcon()
        if not app_icon.isNull():
            icon_label.setPixmap(app_icon.pixmap(56, 56))
            layout.addWidget(icon_label, 0, Qt.AlignmentFlag.AlignHCenter)

        title = QLabel("<b>Apex Download Manager (ADM)</b>")
        title.setObjectName("AboutTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(title)

        version = QLabel(f"Version {self.APP_VERSION}")
        version.setObjectName("MetaLabel")
        version.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(version)

        details = QLabel(
            f"Developer: {self.DEVELOPER_NAME}<br>"
            f"Profile: <a href='{self.PROFILE_URL}'>{self.PROFILE_URL}</a><br>"
            f"Repository: <a href='{self.REPO_URL}'>{self.REPO_URL}</a>"
        )
        details.setObjectName("AboutDetails")
        details.setWordWrap(True)
        details.setTextFormat(Qt.TextFormat.RichText)
        details.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        details.setOpenExternalLinks(True)
        layout.addWidget(details)

        note = QLabel(
            "Fast segmented downloads, queue recovery, and multi-format analysis "
            "for direct links and streaming sources."
        )
        note.setObjectName("MetaLabel")
        note.setWordWrap(True)
        layout.addWidget(note)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(dialog.accept)
        layout.addWidget(buttons)

        dialog.exec()

    def _build_ui(self) -> None:
        app_container = QWidget()
        app_container.setObjectName("AppContainer")
        self.setCentralWidget(app_container)

        root_layout = QVBoxLayout(app_container)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        body = QWidget()
        body.setObjectName("Body")
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(12, 10, 12, 12)
        body_layout.setSpacing(10)

        body_layout.addWidget(self._create_sidebar())
        body_layout.addWidget(self._create_main_content(), 1)

        self.inspector_panel = InspectorPanel(self)
        self.inspector_panel.setFixedWidth(250)
        self.inspector_panel.collapse_requested.connect(lambda: self.set_inspector_visible(False))
        body_layout.addWidget(self.inspector_panel)

        root_layout.addWidget(body, 1)

    def _create_sidebar(self) -> QWidget:
        sidebar = QWidget()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(212)

        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        self.new_task_button = QPushButton("Download")
        self.new_task_button.setObjectName("PrimaryButton")
        self.new_task_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowDown))
        self.new_task_button.clicked.connect(self.open_download_dialog)
        layout.addWidget(self.new_task_button)

        self.nav_list = QListWidget()
        self.nav_list.setObjectName("NavList")
        self.nav_list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.nav_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.nav_list.setSpacing(1)
        for item in self.NAV_ITEMS:
            icon = self.style().standardIcon(self.NAV_ICONS.get(item, QStyle.StandardPixmap.SP_FileIcon))
            list_item = QListWidgetItem(icon, item)
            list_item.setSizeHint(QSize(0, 36))
            self.nav_list.addItem(list_item)
        self._refresh_nav_list_height()
        self.nav_list.setCurrentRow(0)
        self.nav_list.currentRowChanged.connect(self.apply_filters)
        layout.addWidget(self.nav_list)

        layout.addStretch(1)
        return sidebar

    def _create_main_content(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("MainContent")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        top_controls = QWidget()
        top_controls.setObjectName("TopControls")
        controls_layout = QHBoxLayout(top_controls)
        controls_layout.setContentsMargins(0, 0, 0, 0)
        controls_layout.setSpacing(6)

        self.search_input = QLineEdit()
        self.search_input.setObjectName("SearchInput")
        self.search_input.setPlaceholderText("Search by title, URL, or source")
        self.search_input.textChanged.connect(self.apply_filters)
        controls_layout.addWidget(self.search_input, 1)

        self.open_folder_button = QPushButton("Open Location")
        self.open_folder_button.setObjectName("SecondaryButton")
        self.open_folder_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogOpenButton))
        self.open_folder_button.clicked.connect(self.open_output_location)
        controls_layout.addWidget(self.open_folder_button)

        self.pause_all_button = QPushButton("Pause All")
        self.pause_all_button.setObjectName("SecondaryButton")
        self.pause_all_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPause))
        self.pause_all_button.clicked.connect(self.pause_all_downloads)
        controls_layout.addWidget(self.pause_all_button)

        self.resume_all_button = QPushButton("Resume All")
        self.resume_all_button.setObjectName("SecondaryButton")
        self.resume_all_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay))
        self.resume_all_button.clicked.connect(self.resume_all_downloads)
        controls_layout.addWidget(self.resume_all_button)

        self.clear_completed_button = QPushButton("Clear Completed")
        self.clear_completed_button.setObjectName("DangerButton")
        self.clear_completed_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_TrashIcon))
        self.clear_completed_button.clicked.connect(self.clear_completed_downloads)
        controls_layout.addWidget(self.clear_completed_button)

        self.toggle_inspector_button = QPushButton("Hide Inspector")
        self.toggle_inspector_button.setObjectName("SecondaryButton")
        self.toggle_inspector_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowRight))
        self.toggle_inspector_button.clicked.connect(self.toggle_inspector)
        controls_layout.addWidget(self.toggle_inspector_button)

        layout.addWidget(top_controls)

        self.scroll_area = QScrollArea()
        self.scroll_area.setObjectName("DownloadsScroll")
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)

        self.scroll_content = QWidget()
        self.scroll_content.setObjectName("ScrollContent")
        self.cards_layout = QVBoxLayout(self.scroll_content)
        self.cards_layout.setContentsMargins(2, 2, 2, 2)
        self.cards_layout.setSpacing(10)
        self.cards_layout.addStretch(1)

        self.scroll_area.setWidget(self.scroll_content)
        layout.addWidget(self.scroll_area, 1)
        return panel

    def open_download_dialog(self, *_: object) -> None:
        dialog = NewTaskDialog(self.default_output_dir_text, self)
        if dialog.exec() == 0:
            return

        self.default_output_dir_text = dialog.selected_output_dir()
        drafts = dialog.get_download_drafts()
        for draft in drafts:
            self._queue_draft(draft)

        self.apply_filters()
        self._start_next_downloads()

    def open_output_location(self, *_: object) -> None:
        target = Path(self.default_output_dir_text).expanduser()
        target.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))

    def _next_job_id(self) -> str:
        job_id = f"job-{self.next_job_index}"
        self.next_job_index += 1
        return job_id

    def _build_job_from_draft(self, draft: dict[str, Any]) -> dict[str, Any] | None:
        url = str(draft.get("url") or "").strip()
        if not url:
            return None

        title = str(draft.get("title") or title_from_url(url))
        stream_type_value = draft.get("stream_type")
        if stream_type_value is not None:
            stream_type_value = str(stream_type_value)

        category = guess_category(title, stream_type_value=stream_type_value)
        output_base = Path(self.default_output_dir_text).expanduser()
        output_dir = category_output_dir(output_base, category)
        site = source_host(url).replace("www.", "")

        mode = str(draft.get("mode") or "segmented")
        format_id = str(draft.get("format_id") or "").strip() or None
        if mode == "yt_dlp" and format_id is None:
            mode = "yt_dlp"

        size_label = str(draft.get("size_label") or "unknown")
        headers = draft.get("headers") if isinstance(draft.get("headers"), dict) else None
        raw_height = draft.get("height")
        selected_height: int | None
        try:
            selected_height = int(raw_height) if raw_height is not None else None
        except (TypeError, ValueError):
            selected_height = None

        return {
            "id": self._next_job_id(),
            "title": title,
            "source_url": url,
            "site": site,
            "category": category,
            "output_dir": str(output_dir),
            "mode": mode,
            "headers": headers,
            "format_id": format_id,
            "stream_type": stream_type_value,
            "height": selected_height,
            "size_label": size_label,
            "segment_count": self.segment_connections,
            "timeout_seconds": self.timeout_seconds,
            "status": "Queued",
            "progress": 0,
            "speed": "queued",
            "eta": "waiting",
            "size_text": f"0 B / {size_label}" if size_label != "unknown" else "0 B / unknown",
            "message": "Waiting for a free download slot.",
            "downloaded_bytes": 0,
            "total_bytes": None,
            "destination": str(output_dir),
        }

    def _queue_draft(self, draft: dict[str, Any]) -> None:
        job = self._build_job_from_draft(draft)
        if job is None:
            return

        job_id = str(job["id"])
        self.jobs[job_id] = job
        self.job_store.upsert_job(job)
        self._add_download_card(job)
        self.pending_queue.append(job_id)

    def _add_download_card(self, job: dict[str, Any]) -> None:
        job_id = str(job["id"])
        if job_id in self.cards:
            return

        card = DownloadCard(
            job_id,
            str(job.get("title") or "download"),
            str(job.get("source_url") or ""),
            str(job.get("site") or "unknown"),
            str(job.get("category") or "Programs"),
        )
        card.selected.connect(self.select_card)
        card.pause_toggled.connect(lambda paused, job_id=job_id: self._handle_pause_toggled(job_id, paused))
        card.delete_requested.connect(lambda job_id=job_id: self.remove_download(job_id))

        card.update_progress(
            int(job.get("progress") or 0),
            str(job.get("speed") or "queued"),
            str(job.get("eta") or "waiting"),
            str(job.get("size_text") or "0 B / unknown"),
            str(job.get("status") or "Queued"),
        )

        status = str(job.get("status") or "Queued")
        if status == "Completed":
            card.mark_completed()
            card.size_value.setText(str(job.get("size_text") or card.size_value.text()))
        elif status in {"Stopped", "Cancelled"}:
            card.mark_stopped(status)
        elif status == "Failed":
            card.mark_failed("Failed")

        self.cards_layout.insertWidget(self.cards_layout.count() - 1, card)
        self.cards[job_id] = card

    def _restore_jobs_from_store(self) -> None:
        stored_jobs = self.job_store.list_jobs()
        for payload in stored_jobs:
            job_id = str(payload.get("id") or "").strip()
            if not job_id:
                continue

            if job_id.startswith("job-"):
                try:
                    index = int(job_id.split("-", 1)[1])
                    self.next_job_index = max(self.next_job_index, index + 1)
                except ValueError:
                    pass

            self.jobs[job_id] = payload
            self._add_download_card(payload)

            status = str(payload.get("status") or "")
            if status == "Queued":
                self.pending_queue.append(job_id)

    def _update_job(self, job_id: str, **fields: Any) -> None:
        job = self.jobs.get(job_id)
        if job is None:
            return
        job.update(fields)
        self.job_store.upsert_job(job)

    def _start_next_downloads(self) -> None:
        while self.pending_queue and len(self.active_workers) < self.max_parallel_downloads:
            job_id = self.pending_queue.popleft()
            job = self.jobs.get(job_id)
            if not job:
                continue

            status = str(job.get("status") or "")
            if status == "Completed":
                continue

            output_dir = Path(str(job.get("output_dir") or "")).expanduser()
            try:
                output_dir.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                self._mark_job_failed(job_id, f"Failed to create folder: {exc}")
                continue

            worker = DownloadWorkerThread(job)
            worker.progress.connect(self.on_download_progress)
            worker.succeeded.connect(self.on_download_completed)
            worker.failed.connect(self.on_download_failed)
            worker.finished.connect(lambda job_id=job_id: self.on_worker_finished(job_id))

            self.active_workers[job_id] = worker
            self._update_job(
                job_id,
                status="Starting",
                message="Preparing download.",
                speed="calculating",
                eta="calculating",
            )

            card = self.cards.get(job_id)
            if card is not None:
                card.pause_button.blockSignals(True)
                card.pause_button.setChecked(False)
                card.pause_button.setText("Pause")
                card.pause_button.blockSignals(False)
                card.update_progress(
                    int(job.get("progress") or 0),
                    str(job.get("speed") or "calculating"),
                    str(job.get("eta") or "calculating"),
                    str(job.get("size_text") or "0 B / unknown"),
                    "Starting",
                )

            worker.start()

    def on_download_progress(self, job_id: str, payload: dict[str, Any]) -> None:
        percent = int(payload.get("percent") or 0)
        speed = str(payload.get("speed") or "calculating")
        eta = str(payload.get("eta") or "calculating")
        size_text = str(payload.get("size_text") or "0 B / unknown")
        stage = str(payload.get("stage") or "Downloading")

        self._update_job(
            job_id,
            progress=percent,
            speed=speed,
            eta=eta,
            size_text=size_text,
            status=stage,
            message=str(payload.get("message") or "Downloading..."),
            downloaded_bytes=payload.get("downloaded_bytes"),
            total_bytes=payload.get("total_bytes"),
        )

        card = self.cards.get(job_id)
        if card is not None:
            card.update_progress(percent, speed, eta, size_text, stage)

        if self.selected_download_id == job_id and card is not None:
            self.inspector_panel.update_details(card.details())

    def on_download_completed(self, job_id: str, output_path: str) -> None:
        final_size_label = "Completed"
        target = Path(output_path).expanduser()
        if target.exists() and target.is_file():
            final_size_label = format_filesize(target.stat().st_size)

        self._update_job(
            job_id,
            progress=100,
            speed="done",
            eta="0s",
            size_text=final_size_label,
            status="Completed",
            message="Download completed.",
            destination=output_path,
        )

        card = self.cards.get(job_id)
        if card is not None:
            card.size_value.setText(final_size_label)
            card.mark_completed()

        if self.selected_download_id == job_id and card is not None:
            self.inspector_panel.update_details(card.details())

        self.apply_filters()

    def _mark_job_failed(self, job_id: str, message: str) -> None:
        self._update_job(
            job_id,
            speed="stopped",
            eta="n/a",
            status="Failed",
            message=message,
        )
        card = self.cards.get(job_id)
        if card is not None:
            card.mark_failed("Failed")
        self.apply_filters()

    def on_download_failed(self, job_id: str, message: str) -> None:
        cancelled = "cancelled" in message.lower() or "canceled" in message.lower()
        if cancelled:
            self._update_job(
                job_id,
                speed="stopped",
                eta="n/a",
                status="Stopped",
                message="Download stopped by user.",
            )
            card = self.cards.get(job_id)
            if card is not None:
                card.mark_stopped("Stopped")
        else:
            self._mark_job_failed(job_id, message)

        if self.selected_download_id == job_id:
            card = self.cards.get(job_id)
            if card is not None:
                self.inspector_panel.update_details(card.details())

    def on_worker_finished(self, job_id: str) -> None:
        worker = self.active_workers.pop(job_id, None)
        if worker is not None:
            worker.deleteLater()
        self._start_next_downloads()

    def _remove_pending(self, job_id: str) -> bool:
        original_len = len(self.pending_queue)
        self.pending_queue = deque(item for item in self.pending_queue if item != job_id)
        return len(self.pending_queue) != original_len

    def _handle_pause_toggled(self, job_id: str, paused: bool) -> None:
        job = self.jobs.get(job_id)
        if job is None:
            return

        if paused:
            worker = self.active_workers.get(job_id)
            if worker is not None:
                worker.request_cancel()
                return

            if self._remove_pending(job_id):
                self._update_job(
                    job_id,
                    status="Stopped",
                    speed="stopped",
                    eta="n/a",
                    message="Stopped while waiting in queue.",
                )
                card = self.cards.get(job_id)
                if card is not None:
                    card.mark_stopped("Stopped")
                self.apply_filters()
            return

        status = str(job.get("status") or "")
        if status not in {"Stopped", "Failed", "Cancelled"}:
            return
        if job_id in self.active_workers:
            return
        if any(item == job_id for item in self.pending_queue):
            return

        self._update_job(
            job_id,
            status="Queued",
            speed="queued",
            eta="waiting",
            message="Waiting for a free download slot.",
        )
        self.pending_queue.append(job_id)
        card = self.cards.get(job_id)
        if card is not None:
            card.pause_button.blockSignals(True)
            card.pause_button.setChecked(False)
            card.pause_button.setText("Pause")
            card.pause_button.blockSignals(False)
            card.update_progress(
                int(job.get("progress") or 0),
                "queued",
                "waiting",
                str(job.get("size_text") or "0 B / unknown"),
                "Queued",
            )
        self.apply_filters()
        self._start_next_downloads()

    def select_card(self, download_id: str) -> None:
        if download_id not in self.cards:
            return

        if self.selected_download_id and self.selected_download_id in self.cards:
            self.cards[self.selected_download_id].set_selected(False)

        self.selected_download_id = download_id
        selected_card = self.cards[download_id]
        selected_card.set_selected(True)
        self.inspector_panel.update_details(selected_card.details())

    def remove_download(self, download_id: str) -> None:
        worker = self.active_workers.get(download_id)
        if worker is not None:
            worker.request_cancel()
            worker.wait(200)

        self._remove_pending(download_id)

        card = self.cards.pop(download_id, None)
        if card is not None:
            card.setParent(None)
            card.deleteLater()

        self.jobs.pop(download_id, None)
        self.job_store.delete_job(download_id)

        if self.selected_download_id == download_id:
            self.selected_download_id = None
            self.inspector_panel.clear()

        self.apply_filters()

    def pause_all_downloads(self, *_: object) -> None:
        for job_id, card in self.cards.items():
            job = self.jobs.get(job_id)
            if not job:
                continue
            if str(job.get("status") or "") == "Completed":
                continue
            if not card.pause_button.isChecked():
                card.pause_button.setChecked(True)

    def resume_all_downloads(self, *_: object) -> None:
        for job_id, card in self.cards.items():
            job = self.jobs.get(job_id)
            if not job:
                continue
            status = str(job.get("status") or "")
            if status == "Completed":
                continue
            if card.pause_button.isChecked():
                card.pause_button.setChecked(False)

    def clear_completed_downloads(self, *_: object) -> None:
        completed_ids = [job_id for job_id, job in self.jobs.items() if str(job.get("status") or "") == "Completed"]
        for job_id in completed_ids:
            self.remove_download(job_id)

    def apply_filters(self, *_: object) -> None:
        search_text = self.search_input.text().strip().lower()
        selected_nav = self.nav_list.currentItem().text() if self.nav_list.currentItem() else "All Downloads"

        for job_id, card in self.cards.items():
            job = self.jobs.get(job_id, {})
            is_visible = self._matches_filters(card, job, search_text, selected_nav)
            card.setVisible(is_visible)

        if self.selected_download_id:
            selected_card = self.cards.get(self.selected_download_id)
            if selected_card is None or not selected_card.isVisible():
                if selected_card is not None:
                    selected_card.set_selected(False)
                self.selected_download_id = None
                self.inspector_panel.clear()

    def _matches_filters(
        self,
        card: DownloadCard,
        job: dict[str, Any],
        search_text: str,
        selected_nav: str,
    ) -> bool:
        if search_text:
            has_text = (
                search_text in card.file_name.lower()
                or search_text in card.source_url.lower()
                or search_text in card.site.lower()
            )
            if not has_text:
                return False

        status = str(job.get("status") or "")

        if selected_nav == "All Downloads":
            return True
        if selected_nav == "Completed":
            return status == "Completed"
        if selected_nav == "Queued":
            return status in {"Queued", "Starting", "Downloading", "Finalizing", "Stopped", "Cancelled"}
        if selected_nav == "Failed":
            return status == "Failed"

        category = str(job.get("category") or "")
        return category.lower() == selected_nav.lower()

    def toggle_inspector(self, *_: object) -> None:
        self.set_inspector_visible(not self.inspector_panel.isVisible())

    def set_inspector_visible(self, visible: bool) -> None:
        self.inspector_panel.setVisible(visible)
        self.toggle_inspector_button.setText("Hide Inspector" if visible else "Show Inspector")
        icon = QStyle.StandardPixmap.SP_ArrowRight if visible else QStyle.StandardPixmap.SP_ArrowLeft
        self.toggle_inspector_button.setIcon(self.style().standardIcon(icon))

        if self.show_inspector_action.isChecked() != visible:
            self.show_inspector_action.blockSignals(True)
            self.show_inspector_action.setChecked(visible)
            self.show_inspector_action.blockSignals(False)

    def closeEvent(self, event: QCloseEvent) -> None:
        for worker in list(self.active_workers.values()):
            worker.request_cancel()

        for worker in list(self.active_workers.values()):
            worker.wait(1200)

        self.active_workers.clear()
        super().closeEvent(event)
