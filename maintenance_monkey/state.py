"""SQLite state for incidents, jobs, and fingerprints."""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator


@dataclass
class Incident:
    id: str
    source: str
    fingerprint: str
    title: str
    body: str
    status: str
    created_at: float
    meta: dict[str, Any]


@dataclass
class Job:
    id: str
    incident_id: str
    fingerprint: str
    status: str
    branch: str | None
    worktree: str | None
    pr_url: str | None
    session_id: str | None
    error: str | None
    created_at: float
    updated_at: float
    meta: dict[str, Any]


class State:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS incidents (
                    id TEXT PRIMARY KEY,
                    source TEXT NOT NULL,
                    fingerprint TEXT NOT NULL,
                    title TEXT NOT NULL,
                    body TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    meta TEXT NOT NULL DEFAULT '{}'
                );
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    incident_id TEXT NOT NULL,
                    fingerprint TEXT NOT NULL,
                    status TEXT NOT NULL,
                    branch TEXT,
                    worktree TEXT,
                    pr_url TEXT,
                    session_id TEXT,
                    error TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    meta TEXT NOT NULL DEFAULT '{}',
                    FOREIGN KEY (incident_id) REFERENCES incidents(id)
                );
                CREATE TABLE IF NOT EXISTS fingerprints (
                    fingerprint TEXT PRIMARY KEY,
                    last_seen REAL NOT NULL,
                    last_job_id TEXT,
                    open_job_id TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
                CREATE INDEX IF NOT EXISTS idx_incidents_fp ON incidents(fingerprint);
                """
            )

    def add_incident(
        self,
        *,
        source: str,
        fingerprint: str,
        title: str,
        body: str,
        meta: dict[str, Any] | None = None,
    ) -> Incident:
        inc_id = uuid.uuid4().hex[:12]
        now = time.time()
        incident = Incident(
            id=inc_id,
            source=source,
            fingerprint=fingerprint,
            title=title,
            body=body,
            status="open",
            created_at=now,
            meta=meta or {},
        )
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO incidents (id, source, fingerprint, title, body, status, created_at, meta)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    incident.id,
                    incident.source,
                    incident.fingerprint,
                    incident.title,
                    incident.body,
                    incident.status,
                    incident.created_at,
                    json.dumps(incident.meta),
                ),
            )
            conn.execute(
                """
                INSERT INTO fingerprints (fingerprint, last_seen, last_job_id, open_job_id)
                VALUES (?, ?, NULL, NULL)
                ON CONFLICT(fingerprint) DO UPDATE SET last_seen = excluded.last_seen
                """,
                (fingerprint, now),
            )
        return incident

    def should_skip_fingerprint(self, fingerprint: str, cooldown_seconds: int) -> tuple[bool, str]:
        """Return (skip, reason)."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM fingerprints WHERE fingerprint = ?",
                (fingerprint,),
            ).fetchone()
            if not row:
                return False, ""
            if row["open_job_id"]:
                job = conn.execute(
                    "SELECT status FROM jobs WHERE id = ?",
                    (row["open_job_id"],),
                ).fetchone()
                if job and job["status"] in ("queued", "running", "pushing", "done"):
                    if job["status"] == "done":
                        # clear open if done
                        conn.execute(
                            "UPDATE fingerprints SET open_job_id = NULL WHERE fingerprint = ?",
                            (fingerprint,),
                        )
                    else:
                        return True, f"open job {row['open_job_id']} status={job['status']}"
            last = float(row["last_seen"] or 0)
            # Also check last successful/queued job time via jobs table
            recent = conn.execute(
                """
                SELECT id, status, created_at FROM jobs
                WHERE fingerprint = ? AND status IN ('queued','running','pushing','done')
                ORDER BY created_at DESC LIMIT 1
                """,
                (fingerprint,),
            ).fetchone()
            if recent:
                age = time.time() - float(recent["created_at"])
                if recent["status"] in ("queued", "running", "pushing"):
                    return True, f"job {recent['id']} still {recent['status']}"
                if recent["status"] == "done" and age < cooldown_seconds:
                    return True, f"cooldown ({int(cooldown_seconds - age)}s left) after job {recent['id']}"
            # last_seen alone shouldn't block first job; only cooldown after job
            _ = last
        return False, ""

    def create_job(self, incident: Incident) -> Job:
        job_id = uuid.uuid4().hex[:12]
        now = time.time()
        job = Job(
            id=job_id,
            incident_id=incident.id,
            fingerprint=incident.fingerprint,
            status="queued",
            branch=None,
            worktree=None,
            pr_url=None,
            session_id=None,
            error=None,
            created_at=now,
            updated_at=now,
            meta={},
        )
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO jobs
                (id, incident_id, fingerprint, status, branch, worktree, pr_url,
                 session_id, error, created_at, updated_at, meta)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job.id,
                    job.incident_id,
                    job.fingerprint,
                    job.status,
                    None,
                    None,
                    None,
                    None,
                    None,
                    job.created_at,
                    job.updated_at,
                    "{}",
                ),
            )
            conn.execute(
                """
                UPDATE fingerprints SET open_job_id = ?, last_job_id = ?, last_seen = ?
                WHERE fingerprint = ?
                """,
                (job.id, job.id, now, incident.fingerprint),
            )
        return job

    def update_job(self, job_id: str, **fields: Any) -> None:
        allowed = {
            "status",
            "branch",
            "worktree",
            "pr_url",
            "session_id",
            "error",
            "meta",
        }
        sets = []
        values: list[Any] = []
        for key, val in fields.items():
            if key not in allowed:
                continue
            if key == "meta" and isinstance(val, dict):
                val = json.dumps(val)
            sets.append(f"{key} = ?")
            values.append(val)
        if not sets:
            return
        sets.append("updated_at = ?")
        values.append(time.time())
        values.append(job_id)
        with self._conn() as conn:
            conn.execute(f"UPDATE jobs SET {', '.join(sets)} WHERE id = ?", values)
            if fields.get("status") in ("done", "failed", "cancelled"):
                conn.execute(
                    """
                    UPDATE fingerprints SET open_job_id = NULL
                    WHERE open_job_id = ?
                    """,
                    (job_id,),
                )

    def get_job(self, job_id: str) -> Job | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
            if not row:
                return None
            return self._job_from_row(row)

    def get_incident(self, incident_id: str) -> Incident | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM incidents WHERE id = ?", (incident_id,)
            ).fetchone()
            if not row:
                return None
            return self._incident_from_row(row)

    def list_jobs(self, limit: int = 50) -> list[Job]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [self._job_from_row(r) for r in rows]

    def list_incidents(self, limit: int = 50) -> list[Incident]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM incidents ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [self._incident_from_row(r) for r in rows]

    def next_queued_job(self) -> Job | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM jobs WHERE status = 'queued' ORDER BY created_at ASC LIMIT 1"
            ).fetchone()
            if not row:
                return None
            return self._job_from_row(row)

    def count_active_jobs(self) -> int:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS c FROM jobs WHERE status IN ('queued','running','pushing')"
            ).fetchone()
            return int(row["c"])

    def count_running(self) -> int:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS c FROM jobs WHERE status IN ('running','pushing')"
            ).fetchone()
            return int(row["c"])

    @staticmethod
    def _job_from_row(row: sqlite3.Row) -> Job:
        meta = json.loads(row["meta"] or "{}")
        return Job(
            id=row["id"],
            incident_id=row["incident_id"],
            fingerprint=row["fingerprint"],
            status=row["status"],
            branch=row["branch"],
            worktree=row["worktree"],
            pr_url=row["pr_url"],
            session_id=row["session_id"],
            error=row["error"],
            created_at=float(row["created_at"]),
            updated_at=float(row["updated_at"]),
            meta=meta,
        )

    @staticmethod
    def _incident_from_row(row: sqlite3.Row) -> Incident:
        meta = json.loads(row["meta"] or "{}")
        return Incident(
            id=row["id"],
            source=row["source"],
            fingerprint=row["fingerprint"],
            title=row["title"],
            body=row["body"],
            status=row["status"],
            created_at=float(row["created_at"]),
            meta=meta,
        )
