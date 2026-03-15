"""Core downloader primitives and helpers."""

from .download_helpers import (
    CATEGORY_DEFINITIONS,
    category_output_dir,
    default_output_dir,
    format_downloaded_amount,
    format_duration,
    format_eta,
    format_filesize,
    format_speed,
    format_stream_size,
    guess_category,
    resolution_label,
    source_host,
    stream_label,
    stream_type,
    title_from_url,
)
from .segmented_downloader import DownloadRequest, ProgressSnapshot, SegmentedDownloader
from .ssl_helpers import ensure_ssl_certificates, is_certificate_verify_error

__all__ = [
    "CATEGORY_DEFINITIONS",
    "DownloadRequest",
    "ProgressSnapshot",
    "SegmentedDownloader",
    "category_output_dir",
    "default_output_dir",
    "format_downloaded_amount",
    "format_duration",
    "format_eta",
    "format_filesize",
    "format_speed",
    "format_stream_size",
    "guess_category",
    "ensure_ssl_certificates",
    "is_certificate_verify_error",
    "resolution_label",
    "source_host",
    "stream_label",
    "stream_type",
    "title_from_url",
]
