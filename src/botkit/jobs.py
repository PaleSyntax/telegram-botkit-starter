"""Durable, owner-scoped jobs; one worker claims each queued job."""

from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
import time
import uuid


class JobStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY, owner TEXT NOT NULL, source TEXT NOT NULL,
                state TEXT NOT NULL, result TEXT, error TEXT,
                created REAL NOT NULL, updated REAL NOT NULL,
                UNIQUE(owner, source))""")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def enqueue(self, owner: str, source: str) -> dict:
        now = time.time()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM jobs WHERE owner=? AND source=?", (owner, source)).fetchone()
            if row:
                return dict(row)
            active = db.execute("SELECT count(*) FROM jobs WHERE owner=? AND state IN ('queued','running')", (owner,)).fetchone()[0]
            if active >= 20:
                raise ValueError("At most 20 unfinished jobs per owner")
            job_id = uuid.uuid4().hex
            db.execute("INSERT INTO jobs VALUES (?,?,?,'queued',NULL,NULL,?,?)", (job_id, owner, source, now, now))
            return dict(db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())

    def get(self, job_id: str, owner: str) -> dict | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM jobs WHERE id=? AND owner=?", (job_id, owner)).fetchone()
            return dict(row) if row else None

    def claim(self) -> dict | None:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM jobs WHERE state='queued' ORDER BY created, id LIMIT 1").fetchone()
            if row is None:
                return None
            db.execute("UPDATE jobs SET state='running', updated=? WHERE id=?", (time.time(), row["id"]))
            return {**dict(row), "state": "running"}

    def finish(self, job_id: str, result: dict | None, error: str | None = None):
        with self.connect() as db:
            db.execute("UPDATE jobs SET state=?, result=?, error=?, updated=? WHERE id=? AND state='running'",
                       ("failed" if error else "done", json.dumps(result, ensure_ascii=False) if result else None,
                        error, time.time(), job_id))

    def retry(self, job_id: str, owner: str) -> bool:
        """Only failed jobs may be retried. Running jobs need explicit local recovery."""
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            active = db.execute("SELECT count(*) FROM jobs WHERE owner=? AND state IN ('queued','running')", (owner,)).fetchone()[0]
            if active >= 20:
                return False
            return db.execute("UPDATE jobs SET state='queued', error=NULL, updated=? WHERE id=? AND owner=? AND state='failed'",
                              (time.time(), job_id, owner)).rowcount == 1

    def cancel(self, job_id: str, owner: str) -> bool:
        with self.connect() as db:
            return db.execute("UPDATE jobs SET state='cancelled', updated=? WHERE id=? AND owner=? AND state='queued'",
                              (time.time(), job_id, owner)).rowcount == 1

    def recover(self) -> int:
        """Operator-only: run after stopping every worker, never on automatic startup."""
        with self.connect() as db:
            return db.execute("UPDATE jobs SET state='queued', updated=? WHERE state='running'", (time.time(),)).rowcount
