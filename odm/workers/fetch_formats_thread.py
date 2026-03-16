from __future__ import annotations

from typing import Any

from PyQt6.QtCore import QThread, pyqtSignal

from odm.core import ensure_ssl_certificates, is_certificate_verify_error


class FetchFormatsThread(QThread):
    succeeded = pyqtSignal(dict)
    failed = pyqtSignal(str)

    def __init__(self, url: str) -> None:
        super().__init__()
        self.url = url

    def run(self) -> None:
        try:
            import yt_dlp

            ensure_ssl_certificates()

            options: dict[str, Any] = {
                "quiet": True,
                "no_warnings": True,
                "noplaylist": True,
                "skip_download": True,
            }

            def extract(ydl_options: dict[str, Any]) -> dict[str, Any]:
                with yt_dlp.YoutubeDL(ydl_options) as ydl:
                    return ydl.extract_info(self.url, download=False)

            try:
                info = extract(options)
            except Exception as exc:
                if not is_certificate_verify_error(exc):
                    raise
                insecure_options = dict(options)
                insecure_options["nocheckcertificate"] = True
                info = extract(insecure_options)

            if info.get("entries"):
                info = next((entry for entry in info["entries"] if entry), None)
                if not info:
                    raise RuntimeError("No playable media entries were found for this URL.")

            formats = [fmt for fmt in info.get("formats", []) if fmt.get("format_id")]
            if not formats:
                raise RuntimeError("No downloadable formats were returned.")

            formats.sort(
                key=lambda fmt: (
                    fmt.get("vcodec") != "none",
                    fmt.get("acodec") != "none",
                    fmt.get("height") or 0,
                    fmt.get("tbr") or 0,
                ),
                reverse=True,
            )

            source_url = info.get("webpage_url") or self.url
            payload: dict[str, Any] = {
                "title": info.get("title") or "Untitled media",
                "formats": formats,
                "uploader": info.get("uploader") or info.get("channel") or "Unknown source",
                "duration_seconds": info.get("duration"),
                "source_url": source_url,
                "http_headers": dict(info.get("http_headers") or {}),
            }
            self.succeeded.emit(payload)
        except Exception as exc:
            self.failed.emit(str(exc))
