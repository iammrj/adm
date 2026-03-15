from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import urlparse


CATEGORY_DEFINITIONS: dict[str, dict[str, set[str] | str]] = {
    "Music": {
        "extensions": {"aac", "aiff", "alac", "flac", "m4a", "mp3", "ogg", "opus", "wav", "wma"},
        "folder": "Music",
    },
    "Video": {
        "extensions": {
            "3gp",
            "avi",
            "m2ts",
            "m4v",
            "mkv",
            "mov",
            "mp4",
            "mpeg",
            "mpg",
            "ts",
            "webm",
            "wmv",
        },
        "folder": "Video",
    },
    "Programs": {
        "extensions": {"apk", "app", "dmg", "exe", "iso", "msi", "pkg", "sh", "whl", "zipapp"},
        "folder": "Programs",
    },
    "Documents": {
        "extensions": {"csv", "doc", "docx", "epub", "pdf", "ppt", "pptx", "rtf", "txt", "xls", "xlsx"},
        "folder": "Documents",
    },
    "Compressed": {
        "extensions": {"7z", "bz2", "gz", "rar", "tar", "tgz", "xz", "zip"},
        "folder": "Compressed",
    },
}


def default_output_dir() -> Path:
    downloads_dir = Path.home() / "Downloads"
    return downloads_dir if downloads_dir.exists() else Path.cwd()


def source_host(url: str) -> str:
    return urlparse(url.strip()).netloc or "unknown.site"


def title_from_url(url: str) -> str:
    path_name = Path(urlparse(url).path).name
    return path_name or source_host(url)


def format_filesize(size_bytes: float | int | None) -> str:
    if not size_bytes:
        return "unknown"

    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(size_bytes)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.1f} {unit}"
        size /= 1024
    return "unknown"


def format_duration(seconds: int | float | None) -> str:
    if seconds is None:
        return "calculating"

    total_seconds = int(seconds)
    if total_seconds < 0:
        total_seconds = 0

    hours, remainder = divmod(total_seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes:02d}m {secs:02d}s"
    if minutes:
        return f"{minutes}m {secs:02d}s"
    return f"{secs}s"


def format_eta(seconds: int | float | None) -> str:
    if seconds is None:
        return "calculating"
    return format_duration(seconds)


def format_speed(bytes_per_second: float | int | None) -> str:
    if not bytes_per_second:
        return "calculating"
    return f"{format_filesize(bytes_per_second)}/s"


def format_downloaded_amount(downloaded_bytes: int, total_bytes: int | float | None) -> str:
    downloaded_label = format_filesize(downloaded_bytes)
    if total_bytes:
        return f"{downloaded_label} / {format_filesize(total_bytes)}"
    return downloaded_label


def stream_type(fmt: dict[str, Any]) -> str:
    if fmt.get("vcodec") == "none":
        return "Audio"
    if fmt.get("acodec") == "none":
        return "Video"
    return "Muxed"


def resolution_label(fmt: dict[str, Any]) -> str:
    resolution = fmt.get("resolution")
    if resolution and resolution != "audio only":
        return str(resolution)

    width = fmt.get("width")
    height = fmt.get("height")
    if width and height:
        return f"{width}x{height}"

    abr = fmt.get("abr")
    if abr:
        return f"{abr:.0f} kbps"

    if fmt.get("vcodec") == "none":
        return "Audio only"

    return "Unknown"


def protocol_label(fmt: dict[str, Any]) -> str | None:
    protocol = str(fmt.get("protocol") or "").strip().lower()
    if not protocol:
        return None

    protocol_labels = {
        "m3u8": "HLS",
        "m3u8_native": "HLS",
        "http_dash_segments": "DASH",
        "dash": "DASH",
        "https": "Direct",
        "http": "Direct",
    }
    if protocol in protocol_labels:
        return protocol_labels[protocol]

    return protocol.replace("_", " ").upper()


def stream_label(fmt: dict[str, Any]) -> str:
    protocol = protocol_label(fmt)
    quality = resolution_label(fmt)
    raw_format_id = str(fmt.get("format_id") or "").strip()

    if protocol in {"HLS", "DASH"}:
        if quality != "Unknown":
            return f"{protocol} {quality}"

        tbr = fmt.get("tbr")
        if tbr:
            return f"{protocol} {float(tbr):.0f} kbps"

        return protocol

    if raw_format_id:
        if raw_format_id.isdigit():
            return f"ID {raw_format_id}"
        cleaned = raw_format_id.replace("_", " ").replace("-", " ").strip()
        return cleaned or raw_format_id

    return protocol or "Unknown"


def estimated_stream_size_bytes(fmt: dict[str, Any], duration_seconds: int | float | None) -> tuple[float | None, bool]:
    exact_size = fmt.get("filesize")
    if exact_size:
        return float(exact_size), False

    approx_size = fmt.get("filesize_approx")
    if approx_size:
        return float(approx_size), True

    duration = fmt.get("duration") or duration_seconds
    if not duration:
        return None, False

    total_bitrate = fmt.get("tbr")
    if not total_bitrate:
        total_bitrate = float(fmt.get("vbr") or 0) + float(fmt.get("abr") or 0)

    if not total_bitrate:
        return None, False

    estimated_size = float(total_bitrate) * 1000 * float(duration) / 8
    return estimated_size, True


def format_stream_size(fmt: dict[str, Any], duration_seconds: int | float | None) -> str:
    size_bytes, estimated = estimated_stream_size_bytes(fmt, duration_seconds)
    if size_bytes is None:
        return "unknown"

    size_label = format_filesize(size_bytes)
    return f"~{size_label}" if estimated else size_label


def guess_category(
    file_name: str,
    *,
    stream_type_value: str | None = None,
    explicit_category: str | None = None,
) -> str:
    if explicit_category in CATEGORY_DEFINITIONS:
        return explicit_category

    extension = Path(file_name).suffix.lower().lstrip(".")
    if extension:
        for category, definition in CATEGORY_DEFINITIONS.items():
            extensions = definition["extensions"]
            if isinstance(extensions, set) and extension in extensions:
                return category

    if stream_type_value == "Audio":
        return "Music"
    if stream_type_value in {"Video", "Muxed"}:
        return "Video"

    return "Programs"


def category_output_dir(base_dir: Path, category: str) -> Path:
    if category not in CATEGORY_DEFINITIONS:
        return base_dir

    folder_name = str(CATEGORY_DEFINITIONS[category]["folder"])
    if base_dir.name.lower() == folder_name.lower():
        return base_dir
    return base_dir / folder_name
