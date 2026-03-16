from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Any

from PyQt6.QtCore import QThread, pyqtSignal

from odm.core import (
    DownloadRequest,
    ProgressSnapshot,
    SegmentedDownloader,
    ensure_ssl_certificates,
    format_downloaded_amount,
    format_eta,
    format_filesize,
    format_speed,
    is_certificate_verify_error,
)
from odm.workers.ytdlp_runtime import (
    QuietYtdlpLogger,
    has_media_merger,
    js_runtime_config,
    resolve_ffmpeg_executable,
)


class DownloadWorkerThread(QThread):
    progress = pyqtSignal(str, dict)
    succeeded = pyqtSignal(str, str)
    failed = pyqtSignal(str, str)

    def __init__(self, job: dict[str, Any]) -> None:
        super().__init__()
        self.job = job
        self.cancel_requested = False

    def request_cancel(self) -> None:
        self.cancel_requested = True

    @staticmethod
    def _best_muxed_selector(max_height: int | None) -> str:
        if max_height is not None and max_height > 0:
            return f"best[height<={max_height}][acodec!=none]/best[acodec!=none]/best"
        return "best[acodec!=none]/best"

    @staticmethod
    def _merge_warning_detected(messages: list[str]) -> bool:
        warning_text = " ".join(message.lower() for message in messages)
        snippets = (
            "ffmpeg not found",
            "won't be merged",
            "cannot merge",
            "merging of formats failed",
            "postprocessing:",
        )
        return any(snippet in warning_text for snippet in snippets)

    def run(self) -> None:
        mode = str(self.job.get("mode") or "segmented")
        if mode == "yt_dlp":
            self._run_ytdlp()
            return
        self._run_segmented()

    def _run_segmented(self) -> None:
        job_id = str(self.job["id"])
        output_dir = Path(str(self.job["output_dir"])).expanduser()
        request = DownloadRequest(
            job_id=job_id,
            url=str(self.job["source_url"]),
            output_dir=output_dir,
            connections=max(1, int(self.job.get("segment_count") or 4)),
            headers=self.job.get("headers") if isinstance(self.job.get("headers"), dict) else None,
        )

        downloader = SegmentedDownloader()

        def handle_progress(snapshot: ProgressSnapshot) -> None:
            total_bytes = snapshot.total_bytes
            downloaded_text = format_downloaded_amount(snapshot.downloaded_bytes, total_bytes)
            percent = min(100, int(snapshot.downloaded_bytes / total_bytes * 100)) if total_bytes else 0
            payload = {
                "stage": snapshot.stage,
                "message": snapshot.message,
                "percent": percent,
                "speed": format_speed(snapshot.speed_bytes_per_second),
                "eta": format_eta(snapshot.eta_seconds),
                "size": format_filesize(total_bytes),
                "size_text": downloaded_text,
                "downloaded_bytes": snapshot.downloaded_bytes,
                "total_bytes": total_bytes,
            }
            self.progress.emit(job_id, payload)

        try:
            final_path = asyncio.run(
                downloader.download(
                    request,
                    handle_progress,
                    should_cancel=lambda: self.cancel_requested,
                )
            )
            self.succeeded.emit(job_id, str(final_path))
        except Exception as exc:
            self.failed.emit(job_id, str(exc))

    def _run_ytdlp(self) -> None:
        job_id = str(self.job["id"])
        try:
            import yt_dlp

            ensure_ssl_certificates()
            output_dir = Path(str(self.job["output_dir"])).expanduser()
            output_dir.mkdir(parents=True, exist_ok=True)
            output_template = str(output_dir / "%(title)s.%(ext)s")
            timeout_seconds = int(self.job.get("timeout_seconds") or 30)
            final_path: str | None = None
            warning_messages: list[str] = []

            def progress_hook(payload: dict[str, Any]) -> None:
                nonlocal final_path
                if self.cancel_requested:
                    raise RuntimeError("Download cancelled by user.")

                status = str(payload.get("status") or "")
                if status == "downloading":
                    total_bytes = payload.get("total_bytes") or payload.get("total_bytes_estimate")
                    downloaded_bytes = int(payload.get("downloaded_bytes") or 0)
                    downloaded_text = format_downloaded_amount(downloaded_bytes, total_bytes)
                    percent = min(100, int(downloaded_bytes / total_bytes * 100)) if total_bytes else 0
                    self.progress.emit(
                        job_id,
                        {
                            "stage": "Downloading",
                            "message": f"Downloading {downloaded_text}",
                            "percent": percent,
                            "speed": format_speed(payload.get("speed")),
                            "eta": format_eta(payload.get("eta")),
                            "size": format_filesize(total_bytes),
                            "size_text": downloaded_text,
                            "downloaded_bytes": downloaded_bytes,
                            "total_bytes": total_bytes,
                        },
                    )
                elif status == "finished":
                    final_path = str(payload.get("filename") or "")
                    self.progress.emit(
                        job_id,
                        {
                            "stage": "Finalizing",
                            "message": "Finalizing file...",
                            "percent": 100,
                            "speed": "done",
                            "eta": "0s",
                            "size": self.job.get("size_label", "unknown"),
                            "size_text": self.job.get("size_label", "unknown"),
                            "downloaded_bytes": None,
                            "total_bytes": None,
                        },
                    )

            def postprocessor_hook(payload: dict[str, Any]) -> None:
                nonlocal final_path
                info = payload.get("info_dict")
                if not isinstance(info, dict):
                    return
                filepath = str(info.get("filepath") or info.get("_filename") or "").strip()
                if filepath:
                    final_path = filepath

            options: dict[str, Any] = {
                "quiet": True,
                "no_warnings": True,
                "noplaylist": True,
                "continuedl": True,
                "retries": 5,
                "progress_hooks": [progress_hook],
                "postprocessor_hooks": [postprocessor_hook],
                "outtmpl": output_template,
                "socket_timeout": timeout_seconds,
                "concurrent_fragment_downloads": max(1, int(self.job.get("segment_count") or 4)),
                "logger": QuietYtdlpLogger(warning_handler=warning_messages.append),
            }
            runtimes = js_runtime_config()
            if runtimes:
                options["js_runtimes"] = runtimes
            ffmpeg_executable = resolve_ffmpeg_executable()
            if ffmpeg_executable:
                options["ffmpeg_location"] = ffmpeg_executable

            format_id = self.job.get("format_id")
            stream_type = str(self.job.get("stream_type") or "")
            ffmpeg_available = has_media_merger()
            raw_height = self.job.get("height")
            selected_height: int | None
            try:
                selected_height = int(raw_height) if raw_height is not None else None
            except (TypeError, ValueError):
                selected_height = None
            fallback_selector = self._best_muxed_selector(selected_height)
            expect_merge = False
            if format_id:
                format_id_text = str(format_id)
                if stream_type == "Video":
                    if ffmpeg_available:
                        # Video-only formats need explicit audio pairing.
                        options["format"] = (
                            f"{format_id_text}+bestaudio[ext=m4a]/"
                            f"{format_id_text}+bestaudio/"
                            f"{fallback_selector}"
                        )
                        options["merge_output_format"] = "mp4"
                        expect_merge = True
                    else:
                        # Keep audio when merge tools are unavailable in packaged builds.
                        options["format"] = fallback_selector
                elif stream_type in {"Audio", "Muxed"}:
                    options["format"] = format_id_text
                else:
                    # Backward compatibility for older queued jobs without stream_type metadata.
                    if ffmpeg_available:
                        options["format"] = (
                            f"{format_id_text}+bestaudio[ext=m4a]/"
                            f"{format_id_text}+bestaudio/"
                            f"{format_id_text}/"
                            f"{fallback_selector}"
                        )
                        options["merge_output_format"] = "mp4"
                        expect_merge = True
                    else:
                        options["format"] = f"{format_id_text}/{fallback_selector}"
            else:
                if ffmpeg_available:
                    options["format"] = "bestvideo*+bestaudio[ext=m4a]/bestvideo*+bestaudio/best"
                    options["merge_output_format"] = "mp4"
                    expect_merge = True
                else:
                    options["format"] = self._best_muxed_selector(None)

            headers = self.job.get("headers")
            if isinstance(headers, dict) and headers:
                options["http_headers"] = {str(k): str(v) for k, v in headers.items()}

            source_url = str(self.job["source_url"])

            def execute_download(ydl_options: dict[str, Any]) -> int:
                with yt_dlp.YoutubeDL(ydl_options) as ydl:
                    return ydl.download([source_url])

            try:
                exit_code = execute_download(options)
            except Exception as exc:
                if not is_certificate_verify_error(exc):
                    raise

                insecure_options = dict(options)
                insecure_options["nocheckcertificate"] = True
                exit_code = execute_download(insecure_options)

            if exit_code:
                raise RuntimeError(f"yt-dlp exited with status {exit_code}.")

            likely_unmerged_partial = bool(final_path and re.search(r"\.f\d+\.", final_path))
            if expect_merge and (self._merge_warning_detected(warning_messages) or likely_unmerged_partial):
                retry_options = dict(options)
                retry_options["format"] = fallback_selector
                retry_options.pop("merge_output_format", None)
                retry_options["noprogress"] = True
                retry_options["logger"] = QuietYtdlpLogger()

                retry_exit_code = execute_download(retry_options)
                if retry_exit_code:
                    raise RuntimeError(f"yt-dlp fallback retry failed with status {retry_exit_code}.")

            self.succeeded.emit(job_id, final_path or str(output_dir))
        except Exception as exc:
            self.failed.emit(job_id, str(exc))
