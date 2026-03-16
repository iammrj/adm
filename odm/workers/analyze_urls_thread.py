from __future__ import annotations

from typing import Any

from PyQt6.QtCore import QThread, pyqtSignal

from odm.core import (
    ensure_ssl_certificates,
    format_stream_size,
    is_certificate_verify_error,
    resolution_label,
    stream_label,
    stream_type,
    title_from_url,
)
from odm.workers.ytdlp_runtime import QuietYtdlpLogger, js_runtime_config


class AnalyzeUrlsThread(QThread):
    succeeded = pyqtSignal(dict)
    failed = pyqtSignal(str)

    def __init__(self, urls: list[str], include_options: bool = False) -> None:
        super().__init__()
        self.urls = urls
        self.include_options = include_options

    def run(self) -> None:
        try:
            import yt_dlp

            ensure_ssl_certificates()
            results: list[dict[str, Any]] = []
            errors: list[str] = []

            base_options: dict[str, Any] = {
                "quiet": True,
                "no_warnings": True,
                "noplaylist": True,
                "skip_download": True,
                "logger": QuietYtdlpLogger(),
            }
            runtimes = js_runtime_config()
            if runtimes:
                base_options["js_runtimes"] = runtimes

            def extract_with_options(url: str, *, insecure: bool) -> dict[str, Any]:
                options = dict(base_options)
                if insecure:
                    options["nocheckcertificate"] = True
                with yt_dlp.YoutubeDL(options) as ydl:
                    return ydl.extract_info(url, download=False)

            for url in self.urls:
                insecure_used = False
                try:
                    try:
                        info = extract_with_options(url, insecure=False)
                    except Exception as exc:
                        if not is_certificate_verify_error(exc):
                            raise
                        insecure_used = True
                        info = extract_with_options(url, insecure=True)

                    if info.get("entries"):
                        info = next((entry for entry in info["entries"] if entry), None)
                    if not info:
                        raise RuntimeError("No playable media entries were found.")

                    formats = [fmt for fmt in info.get("formats", []) if fmt.get("format_id")]
                    duration_seconds = info.get("duration")
                    title = str(info.get("title") or title_from_url(url))
                    headers = dict(info.get("http_headers") or {})

                    if not formats:
                        results.append(
                            {
                                "url": url,
                                "title": title,
                                "mode": "segmented",
                                "headers": headers or None,
                                "stream_type": None,
                                "size_label": "unknown",
                                "options": [],
                                "selected_option": None,
                            }
                        )
                        continue

                    # Keep IDM-style ordering: higher video quality first.
                    sorted_formats = sorted(
                        formats,
                        key=lambda fmt: (
                            fmt.get("vcodec") != "none",
                            fmt.get("acodec") != "none",
                            fmt.get("height") or 0,
                            fmt.get("tbr") or 0,
                        ),
                        reverse=True,
                    )

                    option_limit = 8 if self.include_options else 1
                    options: list[dict[str, Any]] = []
                    seen_quality: set[str] = set()

                    video_candidates = [fmt for fmt in sorted_formats if fmt.get("vcodec") != "none"]
                    candidates = video_candidates or sorted_formats

                    for fmt in candidates:
                        format_id = str(fmt.get("format_id") or "").strip()
                        if not format_id:
                            continue

                        quality_key = resolution_label(fmt)
                        if quality_key in seen_quality:
                            continue
                        seen_quality.add(quality_key)

                        option_stream_type = stream_type(fmt)
                        option_size = format_stream_size(fmt, duration_seconds)
                        height_value = fmt.get("height")
                        option_height: int | None
                        try:
                            option_height = int(height_value) if height_value is not None else None
                        except (TypeError, ValueError):
                            option_height = None
                        option_label = (
                            f"{resolution_label(fmt)} | {str(fmt.get('ext', 'n/a')).upper()} | "
                            f"{option_stream_type} | {option_size}"
                        )
                        options.append(
                            {
                                "format_id": format_id,
                                "label": option_label,
                                "size_label": option_size,
                                "stream_type": option_stream_type,
                                "stream_label": stream_label(fmt),
                                "height": option_height,
                            }
                        )

                        if len(options) >= option_limit:
                            break

                    selected_option = options[0] if options else None
                    results.append(
                        {
                            "url": url,
                            "title": title,
                            "mode": "yt_dlp",
                            "headers": headers or None,
                            "stream_type": selected_option.get("stream_type") if selected_option else None,
                            "size_label": selected_option.get("size_label", "unknown") if selected_option else "unknown",
                            "options": options,
                            "selected_option": selected_option,
                        }
                    )
                    if insecure_used:
                        errors.append(f"{url}: SSL certificate validation failed; used insecure fallback for this analysis.")
                except Exception as exc:
                    errors.append(f"{url}: {exc}")
                    results.append(
                        {
                            "url": url,
                            "title": title_from_url(url),
                            "mode": "segmented",
                            "headers": None,
                            "stream_type": None,
                            "size_label": "unknown",
                            "options": [],
                            "selected_option": None,
                        }
                    )

            self.succeeded.emit({"results": results, "errors": errors})
        except Exception as exc:
            self.failed.emit(str(exc))
