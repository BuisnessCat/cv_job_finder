"""Jobs and evaluations stored in a single SQLite file."""
import json
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict
from datetime import date

from job_finder import config
from job_finder.sources import Job

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    url         TEXT PRIMARY KEY,
    source      TEXT NOT NULL,
    title       TEXT NOT NULL,
    company     TEXT NOT NULL,
    city        TEXT NOT NULL,
    published   TEXT NOT NULL,      -- YYYY-MM-DD
    description TEXT NOT NULL,
    active      INTEGER NOT NULL DEFAULT 1,
    hidden      INTEGER NOT NULL DEFAULT 0,
    score       INTEGER,            -- NULL until evaluated
    evaluation  TEXT,               -- the model's JSON answer
    cv_hash     TEXT,               -- evaluation key: SHA-256 of the CV, model and rules
    status      TEXT,               -- application: NULL, 'applied', 'accepted', 'rejected'
    applied_at  TEXT,               -- application date YYYY-MM-DD
    notes       TEXT,               -- application notes
    seen        INTEGER NOT NULL DEFAULT 0  -- 0: appeared after the window was last closed (new)
)
"""

# Same order as the Job fields
JOB_FIELDS = "url, source, title, company, city, published, description"

STATUSES = ("applied", "accepted", "rejected")  # waiting, accepted, rejected


@contextmanager
def _connect():
    # A short connection per call: both the window and the background thread use the database
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        with conn:  # commit or roll back the transaction
            yield conn
    finally:
        conn.close()


def init() -> None:
    with _connect() as conn:
        conn.execute(SCHEMA)
        # A database created before the newer columns: add the missing ones, jobs and evaluations are kept
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(jobs)")}
        for column in ("status", "applied_at", "notes"):
            if column not in columns:
                conn.execute(f"ALTER TABLE jobs ADD COLUMN {column} TEXT")
        if "seen" not in columns:
            conn.execute("ALTER TABLE jobs ADD COLUMN seen INTEGER NOT NULL DEFAULT 0")
            conn.execute("UPDATE jobs SET seen = 1")  # existing jobs count as already seen, not new


def save_jobs(source: str, jobs: list[Job]) -> None:
    """Store a source's fresh batch; its jobs missing from the batch become inactive."""
    with _connect() as conn:
        conn.execute("UPDATE jobs SET active = 0 WHERE source = ?", (source,))
        conn.executemany(
            f"""INSERT INTO jobs ({JOB_FIELDS})
                VALUES (:url, :source, :title, :company, :city, :published, :description)
                ON CONFLICT(url) DO UPDATE SET
                    source = excluded.source, title = excluded.title, company = excluded.company,
                    city = excluded.city, published = excluded.published,
                    description = excluded.description, active = 1""",
            [asdict(job) for job in jobs],
        )


def pending_jobs(cv_hash: str) -> list[Job]:
    """Active, not hidden jobs with no application and no evaluation under the current key, newest first."""
    with _connect() as conn:
        rows = conn.execute(
            f"""SELECT {JOB_FIELDS} FROM jobs
                WHERE active = 1 AND hidden = 0 AND status IS NULL AND (cv_hash IS NULL OR cv_hash != ?)
                ORDER BY published DESC""",
            (cv_hash,),
        ).fetchall()
    return [Job(**dict(row)) for row in rows]


def save_evaluation(url: str, evaluation: dict, cv_hash: str) -> None:
    with _connect() as conn:
        conn.execute(
            "UPDATE jobs SET score = ?, evaluation = ?, cv_hash = ? WHERE url = ?",
            (evaluation["score"], json.dumps(evaluation, ensure_ascii=False), cv_hash, url),
        )


def hide(url: str) -> None:
    with _connect() as conn:
        conn.execute("UPDATE jobs SET hidden = 1 WHERE url = ?", (url,))


def apply(url: str) -> None:
    """I applied: the job moves from found to applications with status "waiting" and today's date."""
    with _connect() as conn:
        conn.execute("UPDATE jobs SET status = 'applied', applied_at = ? WHERE url = ?",
                     (date.today().isoformat(), url))


def set_status(url: str, status: str) -> None:
    """Outcome of an application: one of STATUSES; the application date does not change."""
    with _connect() as conn:
        conn.execute("UPDATE jobs SET status = ? WHERE url = ?", (status, url))


def unapply(url: str) -> None:
    """Back to found: clear the application status and date."""
    with _connect() as conn:
        conn.execute("UPDATE jobs SET status = NULL, applied_at = NULL WHERE url = ?", (url,))


def set_notes(url: str, notes: str) -> None:
    """Application notes: who you talked to, when the interview is."""
    with _connect() as conn:
        conn.execute("UPDATE jobs SET notes = ? WHERE url = ?", (notes, url))


def mark_all_seen() -> None:
    """Mark all evaluated jobs as seen (when the window closes): only jobs arriving later will be new.

    Jobs not evaluated yet (waiting in the queue, LM Studio did not start) were never shown, they stay new."""
    with _connect() as conn:
        conn.execute("UPDATE jobs SET seen = 1 WHERE seen = 0 AND score IS NOT NULL")


def unseen_urls() -> set[str]:
    """URLs of jobs that appeared after the window was last closed."""
    with _connect() as conn:
        return {row["url"] for row in conn.execute("SELECT url FROM jobs WHERE seen = 0")}


def count_evaluated(cv_hash: str) -> int:
    """How many active, not hidden jobs are evaluated under the current key."""
    with _connect() as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM jobs WHERE active = 1 AND hidden = 0 AND status IS NULL AND cv_hash = ?",
            (cv_hash,),
        ).fetchone()[0]


def make_row(job: Job, evaluation: dict) -> dict:
    """A row for the window: job fields without the description, the score and the model's analysis."""
    row = asdict(job)
    del row["description"]
    return {**row, "score": evaluation["score"], "evaluation": evaluation}


def list_jobs(cv_hash: str, min_score: int) -> list[dict]:
    """Jobs for the window: scored under the current CV at or above the threshold, best first."""
    with _connect() as conn:
        rows = conn.execute(
            f"""SELECT {JOB_FIELDS}, evaluation FROM jobs
                WHERE active = 1 AND hidden = 0 AND status IS NULL AND cv_hash = ? AND score >= ?
                ORDER BY score DESC, published DESC""",
            (cv_hash, min_score),
        ).fetchall()
    return [make_row(Job(*tuple(row)[:7]), json.loads(row["evaluation"])) for row in rows]


def list_applied() -> list[dict]:
    """Applications for the "My applications" tab: all, newest first, regardless of active, hidden and key."""
    with _connect() as conn:
        rows = conn.execute(
            f"""SELECT {JOB_FIELDS}, evaluation, status, applied_at, notes FROM jobs
                WHERE status IS NOT NULL
                ORDER BY applied_at DESC, title""",
        ).fetchall()
    return [
        {**make_row(Job(*tuple(row)[:7]), json.loads(row["evaluation"])),
         "status": row["status"], "applied_at": row["applied_at"], "notes": row["notes"] or ""}
        for row in rows
    ]
