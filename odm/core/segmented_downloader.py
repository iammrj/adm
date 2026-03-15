from __future__ import annotations

import asyncio
import shutil
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlparse
from urllib.request import Request, urlopen


USER_AGENT = "OrbitDownloadManager/1.0"
CHUNK_SIZE = 256 * 1024
MIN_SEGMENT_SIZE = 2 * 1024 * 1024


@dataclass(slots=True)
class DownloadRequest:
    job_id: str
    url: str
    output_dir: Path
    file_name: str | None = None
    connections: int = 4
    headers: dict[str, str] | None = None


@dataclass(slots=True)
class ProgressSnapshot:
    stage: str
    downloaded_bytes: int
    total_bytes: int | None
    speed_bytes_per_second: float | None
    eta_seconds: float | None
    message: str
    segment_progress: list[int] | None = None
    segment_labels: list[str] | None = None


@dataclass(slots=True)
class _DownloadMetadata:
    final_path: Path
    total_bytes: int | None
    accepts_ranges: bool


@dataclass(slots=True)
class _Segment:
    start: int
    end: int

    @property
    def size(self) -> int:
        return self.end - self.start + 1


@dataclass(slots=True)
class _ConnectionState:
    start: int | None = None
    end: int | None = None
    downloaded: int = 0
    active: bool = False


class _SharedProgress:
    def __init__(self, total_bytes: int | None, connection_count: int) -> None:
        self.total_bytes = total_bytes
        self.downloaded_bytes = 0
        self.stage = "Preparing"
        self.completed = False
        self.lock = threading.Lock()
        self.connections = [_ConnectionState() for _ in range(max(1, connection_count))]

    def add(self, chunk_size: int, connection_index: int | None = None) -> None:
        with self.lock:
            self.downloaded_bytes += chunk_size
            if connection_index is not None and 0 <= connection_index < len(self.connections):
                self.connections[connection_index].downloaded += chunk_size

    def assign(self, connection_index: int, start: int, end: int) -> None:
        with self.lock:
            connection = self.connections[connection_index]
            connection.start = start
            connection.end = end
            connection.downloaded = 0
            connection.active = True

    def finish_assignment(self, connection_index: int) -> None:
        with self.lock:
            connection = self.connections[connection_index]
            if connection.start is not None and connection.end is not None:
                connection.downloaded = connection.end - connection.start + 1
            connection.active = False

    def snapshot(self) -> tuple[int, int | None, str, list[int], list[str]]:
        with self.lock:
            segment_progress: list[int] = []
            segment_labels: list[str] = []
            for connection in self.connections:
                if connection.start is None or connection.end is None:
                    segment_progress.append(0)
                    segment_labels.append("Idle")
                    continue

                total = max(connection.end - connection.start + 1, 1)
                progress = min(100, int(connection.downloaded / total * 100))
                label = f"{connection.start}-{connection.end}"
                if not connection.active:
                    label = f"Completed {label}"
                segment_progress.append(progress)
                segment_labels.append(label)

            return self.downloaded_bytes, self.total_bytes, self.stage, segment_progress, segment_labels

    def reset(self, stage: str) -> None:
        with self.lock:
            self.downloaded_bytes = 0
            self.stage = stage
            self.connections = [_ConnectionState() for _ in range(len(self.connections))]


class _DynamicSegmentPool:
    def __init__(self, total_bytes: int, min_segment_size: int) -> None:
        self.min_segment_size = min_segment_size
        self.lock = threading.Lock()
        self.segments = [_Segment(0, total_bytes - 1)]

    def claim(self) -> _Segment | None:
        with self.lock:
            if not self.segments:
                return None

            largest_index = max(range(len(self.segments)), key=lambda index: self.segments[index].size)
            segment = self.segments.pop(largest_index)
            if segment.size >= self.min_segment_size * 2:
                half = segment.size // 2
                assigned = _Segment(segment.start, segment.start + half - 1)
                remainder = _Segment(segment.start + half, segment.end)
                self.segments.append(remainder)
                return assigned

            return segment


class SegmentedDownloader:
    def __init__(self, chunk_size: int = CHUNK_SIZE, min_segment_size: int = MIN_SEGMENT_SIZE) -> None:
        self.chunk_size = chunk_size
        self.min_segment_size = min_segment_size

    async def download(
        self,
        request: DownloadRequest,
        progress_callback: Callable[[ProgressSnapshot], None],
        should_cancel: Callable[[], bool] | None = None,
    ) -> Path:
        metadata = await asyncio.to_thread(self._probe, request)
        state = _SharedProgress(metadata.total_bytes, request.connections)
        reporter = asyncio.create_task(self._report_progress(state, progress_callback))

        work_dir = metadata.final_path.parent / f".adm-{request.job_id}"
        work_dir.mkdir(parents=True, exist_ok=True)

        try:
            use_segments = self._should_segment(metadata.total_bytes, metadata.accepts_ranges, request.connections)
            state.stage = "Downloading"
            if use_segments and metadata.total_bytes is not None:
                temp_path = work_dir / "segmented.part"
                with temp_path.open("wb") as handle:
                    handle.truncate(metadata.total_bytes)

                pool = _DynamicSegmentPool(metadata.total_bytes, self.min_segment_size)
                try:
                    tasks = [
                        asyncio.to_thread(
                            self._download_dynamic_connection,
                            request.url,
                            temp_path,
                            index,
                            pool,
                            state,
                            request.headers,
                            should_cancel,
                        )
                        for index in range(max(1, request.connections))
                    ]
                    await asyncio.gather(*tasks)
                except Exception:
                    temp_path.unlink(missing_ok=True)
                    state.reset("Retrying")
                    progress_callback(
                        ProgressSnapshot(
                            stage="Retrying",
                            downloaded_bytes=0,
                            total_bytes=metadata.total_bytes,
                            speed_bytes_per_second=None,
                            eta_seconds=None,
                            message="Segmented transfer failed. Retrying with a single connection.",
                        )
                    )
                    temp_path = work_dir / "single.part"
                    await asyncio.to_thread(
                        self._download_range,
                        request.url,
                        temp_path,
                        None,
                        None,
                        state,
                        request.headers,
                        should_cancel,
                    )
                    state.stage = "Finalizing"
                    temp_path.replace(metadata.final_path)
                else:
                    state.stage = "Finalizing"
                    temp_path.replace(metadata.final_path)
            else:
                temp_path = work_dir / "single.part"
                await asyncio.to_thread(
                    self._download_range,
                    request.url,
                    temp_path,
                    None,
                    None,
                    state,
                    request.headers,
                    should_cancel,
                )
                state.stage = "Finalizing"
                temp_path.replace(metadata.final_path)

            progress_callback(
                ProgressSnapshot(
                    stage="Completed",
                    downloaded_bytes=metadata.total_bytes or state.downloaded_bytes,
                    total_bytes=metadata.total_bytes,
                    speed_bytes_per_second=None,
                    eta_seconds=0,
                    message=f"Saved to {metadata.final_path}",
                )
            )
            return metadata.final_path
        finally:
            state.completed = True
            await reporter
            shutil.rmtree(work_dir, ignore_errors=True)

    def _should_segment(self, total_bytes: int | None, accepts_ranges: bool, connections: int) -> bool:
        return bool(accepts_ranges and total_bytes and connections > 1 and total_bytes >= self.min_segment_size * 2)

    def _probe(self, request: DownloadRequest) -> _DownloadMetadata:
        request.output_dir.mkdir(parents=True, exist_ok=True)

        total_bytes: int | None = None
        accepts_ranges = False
        final_url = request.url
        headers: Any = None

        try:
            head_request = self._make_request(request.url, headers=request.headers, method="HEAD")
            with urlopen(head_request, timeout=30) as response:
                headers = response.headers
                final_url = response.geturl()
                total_bytes = self._parse_int(headers.get("Content-Length"))
                accepts_ranges = "bytes" in headers.get("Accept-Ranges", "").lower()
        except (HTTPError, URLError, TimeoutError, ValueError):
            pass

        if request.connections > 1:
            accepts_ranges = False
            try:
                probe_headers = dict(request.headers or {})
                probe_headers["Range"] = "bytes=0-0"
                range_request = self._make_request(request.url, headers=probe_headers)
                with urlopen(range_request, timeout=30) as response:
                    final_url = response.geturl()
                    status_code = getattr(response, "status", None) or response.getcode()
                    if status_code == 206:
                        headers = response.headers
                        accepts_ranges = True
                        total_bytes = self._parse_content_range(headers.get("Content-Range")) or total_bytes
                    elif not headers:
                        headers = response.headers
            except (HTTPError, URLError, TimeoutError, ValueError):
                accepts_ranges = False

        file_name = request.file_name or self._filename_from_headers(headers) or self._filename_from_url(final_url)
        safe_name = self._sanitize_filename(file_name)
        final_path = self._resolve_output_path(request.output_dir, safe_name)

        return _DownloadMetadata(final_path=final_path, total_bytes=total_bytes, accepts_ranges=accepts_ranges)

    def _download_range(
        self,
        url: str,
        target_path: Path,
        start: int | None,
        end: int | None,
        state: _SharedProgress,
        request_headers: dict[str, str] | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> None:
        headers = dict(request_headers or {})
        if start is not None and end is not None:
            headers["Range"] = f"bytes={start}-{end}"

        request = self._make_request(url, headers=headers)
        with urlopen(request, timeout=60) as response, target_path.open("wb") as handle:
            status_code = getattr(response, "status", None) or response.getcode()
            if start is not None and end is not None and status_code != 206:
                raise RuntimeError(f"Expected partial content for range {start}-{end}, got HTTP {status_code}.")

            expected_remaining = None if start is None or end is None else end - start + 1
            while True:
                if should_cancel and should_cancel():
                    raise RuntimeError("Download cancelled by user.")

                chunk = response.read(self.chunk_size)
                if not chunk:
                    break

                handle.write(chunk)
                state.add(len(chunk))
                if expected_remaining is not None:
                    expected_remaining -= len(chunk)

            if expected_remaining is not None and expected_remaining != 0:
                raise RuntimeError(f"Incomplete response for range {start}-{end}; {expected_remaining} bytes missing.")

    def _download_dynamic_connection(
        self,
        url: str,
        target_path: Path,
        connection_index: int,
        pool: _DynamicSegmentPool,
        state: _SharedProgress,
        request_headers: dict[str, str] | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> None:
        while True:
            if should_cancel and should_cancel():
                raise RuntimeError("Download cancelled by user.")

            segment = pool.claim()
            if segment is None:
                break

            headers = dict(request_headers or {})
            headers["Range"] = f"bytes={segment.start}-{segment.end}"
            request = self._make_request(url, headers=headers)
            state.assign(connection_index, segment.start, segment.end)

            with urlopen(request, timeout=60) as response, target_path.open("r+b") as handle:
                status_code = getattr(response, "status", None) or response.getcode()
                if status_code != 206:
                    raise RuntimeError(
                        f"Expected partial content for range {segment.start}-{segment.end}, got HTTP {status_code}."
                    )

                handle.seek(segment.start)
                remaining = segment.size
                while remaining > 0:
                    if should_cancel and should_cancel():
                        raise RuntimeError("Download cancelled by user.")

                    chunk = response.read(min(self.chunk_size, remaining))
                    if not chunk:
                        break

                    handle.write(chunk)
                    chunk_size = len(chunk)
                    remaining -= chunk_size
                    state.add(chunk_size, connection_index)

                if remaining != 0:
                    raise RuntimeError(
                        f"Incomplete response for range {segment.start}-{segment.end}; {remaining} bytes missing."
                    )

            state.finish_assignment(connection_index)

    async def _report_progress(
        self,
        state: _SharedProgress,
        progress_callback: Callable[[ProgressSnapshot], None],
    ) -> None:
        previous_downloaded = 0
        previous_time = time.monotonic()

        while not state.completed:
            await asyncio.sleep(0.25)
            downloaded_bytes, total_bytes, stage, segment_progress, segment_labels = state.snapshot()
            now = time.monotonic()
            if downloaded_bytes < previous_downloaded:
                previous_downloaded = 0
                previous_time = now

            interval = max(now - previous_time, 0.001)
            delta = downloaded_bytes - previous_downloaded
            speed = delta / interval if delta > 0 else None
            eta = None
            if total_bytes and speed and speed > 0:
                eta = max(total_bytes - downloaded_bytes, 0) / speed

            if stage == "Finalizing":
                message = "Finalizing file..."
            elif total_bytes:
                message = f"Downloading {downloaded_bytes} of {total_bytes} bytes"
            else:
                message = f"Downloading {downloaded_bytes} bytes"

            progress_callback(
                ProgressSnapshot(
                    stage=stage,
                    downloaded_bytes=downloaded_bytes,
                    total_bytes=total_bytes,
                    speed_bytes_per_second=speed,
                    eta_seconds=eta,
                    message=message,
                    segment_progress=segment_progress,
                    segment_labels=segment_labels,
                )
            )

            previous_downloaded = downloaded_bytes
            previous_time = now

    def _make_request(
        self,
        url: str,
        headers: dict[str, str] | None = None,
        method: str | None = None,
    ) -> Request:
        request_headers = {"User-Agent": USER_AGENT, "Accept-Encoding": "identity"}
        if headers:
            request_headers.update(headers)
        return Request(url, headers=request_headers, method=method)

    def _filename_from_headers(self, headers: Any) -> str | None:
        if not headers:
            return None

        content_disposition = headers.get("Content-Disposition")
        if not content_disposition:
            return None

        if "filename*=" in content_disposition:
            encoded = content_disposition.split("filename*=", 1)[1].split(";", 1)[0].strip()
            if "''" in encoded:
                encoded = encoded.split("''", 1)[1]
            return unquote(encoded.strip('"'))

        if "filename=" in content_disposition:
            file_name = content_disposition.split("filename=", 1)[1].split(";", 1)[0]
            return file_name.strip().strip('"')

        return None

    def _filename_from_url(self, url: str) -> str:
        path = unquote(urlparse(url).path)
        candidate = Path(path).name
        return candidate or "download.bin"

    def _sanitize_filename(self, name: str) -> str:
        sanitized = "".join("_" if char in '<>:"/\\|?*\0' else char for char in name).strip()
        return sanitized or "download.bin"

    def _resolve_output_path(self, output_dir: Path, file_name: str) -> Path:
        base_path = output_dir / file_name
        if not base_path.exists():
            return base_path

        stem = base_path.stem
        suffix = base_path.suffix
        counter = 1
        while True:
            candidate = output_dir / f"{stem} ({counter}){suffix}"
            if not candidate.exists():
                return candidate
            counter += 1

    def _parse_int(self, value: str | None) -> int | None:
        if not value:
            return None
        try:
            return int(value)
        except ValueError:
            return None

    def _parse_content_range(self, value: str | None) -> int | None:
        if not value or "/" not in value:
            return None
        total = value.rsplit("/", 1)[1]
        return self._parse_int(total)
