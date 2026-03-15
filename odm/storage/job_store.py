from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


INTERRUPTED_STATUSES = {"Starting", "Downloading", "Finalizing"}


class JobStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    payload_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.commit()

    def upsert_job(self, payload: dict[str, Any]) -> None:
        job_id = str(payload.get("id") or "").strip()
        if not job_id:
            raise ValueError("job payload is missing 'id'")

        payload_json = json.dumps(payload, ensure_ascii=True)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO jobs (job_id, payload_json, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(job_id) DO UPDATE SET
                    payload_json=excluded.payload_json,
                    updated_at=CURRENT_TIMESTAMP
                """,
                (job_id, payload_json),
            )
            conn.commit()

    def delete_job(self, job_id: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM jobs WHERE job_id = ?", (job_id,))
            conn.commit()

    def list_jobs(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute("SELECT payload_json FROM jobs ORDER BY updated_at ASC, job_id ASC").fetchall()

        jobs: list[dict[str, Any]] = []
        for row in rows:
            try:
                payload = json.loads(row["payload_json"])
            except (TypeError, json.JSONDecodeError):
                continue
            if isinstance(payload, dict):
                jobs.append(payload)
        return jobs

    def recover_interrupted_jobs(self) -> None:
        jobs = self.list_jobs()
        for payload in jobs:
            status = str(payload.get("status") or "")
            if status not in INTERRUPTED_STATUSES:
                continue

            payload["status"] = "Stopped"
            payload["speed"] = "stopped"
            payload["eta"] = "n/a"
            payload["message"] = "Recovered after restart. Ready to resume."
            self.upsert_job(payload)


def default_job_db_path() -> Path:
    root = Path(__file__).resolve().parents[1]
    return root / "internal" / "downloads.db"
