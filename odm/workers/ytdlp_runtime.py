from __future__ import annotations

import os
import shutil
from functools import lru_cache
from pathlib import Path
from typing import Callable


JS_RUNTIME_CANDIDATES = ("node", "deno", "quickjs", "bun")


def _fallback_runtime_paths(runtime: str) -> list[Path]:
    home = Path.home()
    if runtime == "node":
        paths = [
            Path("/opt/homebrew/bin/node"),
            Path("/usr/local/bin/node"),
            Path("/usr/bin/node"),
            home / ".volta" / "bin" / "node",
            home / ".fnm" / "aliases" / "default" / "bin" / "node",
        ]
        paths.extend((home / ".nvm" / "versions" / "node").glob("*/bin/node"))
        paths.extend(Path("/opt/homebrew/opt").glob("node@*/bin/node"))
        return paths

    if runtime == "deno":
        return [
            Path("/opt/homebrew/bin/deno"),
            Path("/usr/local/bin/deno"),
            home / ".deno" / "bin" / "deno",
        ]

    if runtime == "quickjs":
        return [
            Path("/opt/homebrew/bin/qjs"),
            Path("/usr/local/bin/qjs"),
            Path("/usr/bin/qjs"),
        ]

    if runtime == "bun":
        return [
            Path("/opt/homebrew/bin/bun"),
            Path("/usr/local/bin/bun"),
            home / ".bun" / "bin" / "bun",
        ]

    return []


def _runtime_path(runtime: str) -> str | None:
    if runtime == "quickjs":
        direct_binary = shutil.which("qjs") or shutil.which("quickjs")
    else:
        direct_binary = shutil.which(runtime)

    if direct_binary and _is_executable_file(direct_binary):
        return direct_binary

    for path in _fallback_runtime_paths(runtime):
        if path.is_file() and os.access(path, os.X_OK):
            return str(path)

    return None


def js_runtime_config() -> dict[str, dict[str, str]]:
    runtimes: dict[str, dict[str, str]] = {}
    for runtime in JS_RUNTIME_CANDIDATES:
        path = _runtime_path(runtime)
        if path:
            runtimes[runtime] = {"path": path}
    return runtimes


def _is_executable_file(path: str | Path) -> bool:
    candidate = Path(path)
    return candidate.is_file() and os.access(candidate, os.X_OK)


@lru_cache(maxsize=1)
def resolve_ffmpeg_executable() -> str | None:
    ffmpeg_from_path = shutil.which("ffmpeg")
    if ffmpeg_from_path and _is_executable_file(ffmpeg_from_path):
        return ffmpeg_from_path

    try:
        import imageio_ffmpeg

        bundled_ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None

    if bundled_ffmpeg and _is_executable_file(bundled_ffmpeg):
        return str(bundled_ffmpeg)
    return None


@lru_cache(maxsize=1)
def has_media_merger() -> bool:
    return bool(resolve_ffmpeg_executable() or shutil.which("avconv"))


class QuietYtdlpLogger:
    _SUPPRESSED_WARNING_SNIPPETS = (
        "No supported JavaScript runtime could be found",
        "YouTube extraction without a JS runtime has been deprecated",
    )

    def __init__(self, warning_handler: Callable[[str], None] | None = None) -> None:
        self._warning_handler = warning_handler

    def debug(self, msg: str) -> None:
        _ = msg

    def info(self, msg: str) -> None:
        _ = msg

    def warning(self, msg: str) -> None:
        text = str(msg)
        if not text:
            return
        if any(snippet in text for snippet in self._SUPPRESSED_WARNING_SNIPPETS):
            return
        if self._warning_handler is not None:
            self._warning_handler(text)

    def error(self, msg: str) -> None:
        text = str(msg)
        if self._warning_handler is not None and text:
            self._warning_handler(text)
