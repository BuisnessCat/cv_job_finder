"""Jobs and evaluations stored in a single SQLite file."""
import json
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict
from datetime import date, timedelta

from job_finder import config
from job_finder.sources import Job, same_job_key

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
    seen        INTEGER NOT NULL DEFAULT 0, -- 0: appeared after the window was last closed (new)
    first_seen  TEXT,               -- YYYY-MM-DD when the app first saw this job (or its twin)
    salary      TEXT,               -- "$2,000–3,000 / month" when the site gives one
    gone_at     TEXT                -- YYYY-MM-DD when the source stopped listing it (NULL while listed)
)
"""

# Same order as the Job fields
JOB_FIELDS = "url, source, title, company, city, published, description, salary"

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
        conn.execute("CREATE TABLE IF NOT EXISTS settings (id INTEGER PRIMARY KEY CHECK (id = 1), data TEXT NOT NULL)")
        # A database created before the newer columns: add the missing ones, jobs and evaluations are kept
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(jobs)")}
        for column in ("status", "applied_at", "notes", "salary"):
            if column not in columns:
                conn.execute(f"ALTER TABLE jobs ADD COLUMN {column} TEXT")
        if "seen" not in columns:
            conn.execute("ALTER TABLE jobs ADD COLUMN seen INTEGER NOT NULL DEFAULT 0")
            conn.execute("UPDATE jobs SET seen = 1")  # existing jobs count as already seen, not new
        if "first_seen" not in columns:
            conn.execute("ALTER TABLE jobs ADD COLUMN first_seen TEXT")
            # The site's date for existing jobs: no false "reposted" marks right after the update
            conn.execute("UPDATE jobs SET first_seen = COALESCE(NULLIF(published, ''), ?)",
                         (date.today().isoformat(),))
        if "gone_at" not in columns:
            conn.execute("ALTER TABLE jobs ADD COLUMN gone_at TEXT")
            # Nobody noted before when a job went: one first seen in the last month counts as gone today (a good
            # job that just vanished comes back for a week), older ones as gone long ago
            today = date.today()
            conn.execute("UPDATE jobs SET gone_at = CASE WHEN first_seen >= ? THEN ? ELSE '2000-01-01' END "
                         "WHERE active = 0", ((today - timedelta(days=30)).isoformat(), today.isoformat()))


def get_settings() -> dict | None:
    """The settings row as a dict, None if the wizard was never finished."""
    with _connect() as conn:
        row = conn.execute("SELECT data FROM settings WHERE id = 1").fetchone()
    return json.loads(row["data"]) if row else None


def put_settings(data: dict) -> None:
    with _connect() as conn:
        conn.execute("INSERT INTO settings (id, data) VALUES (1, ?) ON CONFLICT(id) DO UPDATE SET data = excluded.data",
                     (json.dumps(data, ensure_ascii=False),))


def save_jobs(source: str, jobs: list[Job], today: str | None = None, fetched: bool = True) -> None:
    """Store a source's fresh batch; its jobs missing from the batch become inactive (gone_at: since when).

    A new job gets first_seen = the earliest first_seen of a job with the same company and title, else today;
    an existing job keeps its first_seen. fetched=False: the source wasn't asked (remote turned off), so its jobs
    are not "no longer listed", just not searched for."""
    today = today or date.today().isoformat()
    with _connect() as conn:
        earliest: dict[tuple[str, str], str] = {}
        for row in conn.execute("SELECT company, title, first_seen FROM jobs WHERE first_seen IS NOT NULL"):
            key = same_job_key(row["company"], row["title"])
            earliest[key] = min(earliest.get(key, row["first_seen"]), row["first_seen"])
        conn.execute("UPDATE jobs SET active = 0 WHERE source = ?", (source,))
        conn.executemany(
            f"""INSERT INTO jobs ({JOB_FIELDS}, first_seen)
                VALUES (:url, :source, :title, :company, :city, :published, :description, :salary, :first_seen)
                ON CONFLICT(url) DO UPDATE SET
                    source = excluded.source, title = excluded.title, company = excluded.company,
                    city = excluded.city, published = excluded.published,
                    description = excluded.description, salary = excluded.salary, active = 1,
                    gone_at = NULL""",
            [{**asdict(job), "first_seen": today if job.source in config.NO_TWIN_SOURCES
              else earliest.get(same_job_key(job.company, job.title), today)}
             for job in jobs],
        )
        conn.execute("UPDATE jobs SET gone_at = ? WHERE source = ? AND active = 0 AND gone_at IS NULL",
                     (today if fetched else "2000-01-01", source))


def pending_jobs(cv_hash: str, gone_days: int = 0, today: str | None = None) -> list[Job]:
    """Active, not hidden jobs with no application and no evaluation under the current key, newest first. With
    gone_days, also jobs gone in the last gone_days days: they are still shown and need a score under the new key."""
    since = (date.fromisoformat(today) if today else date.today()) - timedelta(days=gone_days)
    with _connect() as conn:
        rows = conn.execute(
            f"""SELECT {JOB_FIELDS} FROM jobs
                WHERE (active = 1 OR (? > 0 AND gone_at >= ?)) AND hidden = 0 AND status IS NULL
                  AND (cv_hash IS NULL OR cv_hash != ?)
                ORDER BY published DESC""",
            (gone_days, since.isoformat(), cv_hash),
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


def unhide(url: str) -> None:
    """Undo for "Hide"."""
    with _connect() as conn:
        conn.execute("UPDATE jobs SET hidden = 0 WHERE url = ?", (url,))


def first_seen(url: str) -> str:
    """When the app first saw the job (YYYY-MM-DD), "" if unknown."""
    with _connect() as conn:
        row = conn.execute("SELECT first_seen FROM jobs WHERE url = ?", (url,)).fetchone()
    return (row["first_seen"] if row else None) or ""


def description(url: str) -> str:
    """The job description, read only when the card shows it."""
    with _connect() as conn:
        row = conn.execute("SELECT description FROM jobs WHERE url = ?", (url,)).fetchone()
    return row["description"] if row else ""


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


def has_evaluations() -> bool:
    """Whether any job has a score, under any key: the wizard warns that they will be scored again."""
    with _connect() as conn:
        return conn.execute("SELECT 1 FROM jobs WHERE score IS NOT NULL LIMIT 1").fetchone() is not None


def count_evaluated(cv_hash: str) -> int:
    """How many active, not hidden jobs are evaluated under the current key."""
    with _connect() as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM jobs WHERE active = 1 AND hidden = 0 AND status IS NULL AND cv_hash = ?",
            (cv_hash,),
        ).fetchone()[0]


def evaluations(cv_hash: str) -> list[dict]:
    """Model analyses of the jobs counted in "Done: … evaluated": active, not hidden, no application, current key."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT evaluation FROM jobs WHERE active = 1 AND hidden = 0 AND status IS NULL AND cv_hash = ?",
            (cv_hash,),
        ).fetchall()
    return [json.loads(row["evaluation"]) for row in rows]


def make_row(job: Job, evaluation: dict, first_seen: str = "") -> dict:
    """A row for the window: job fields without the description, the score and the model's analysis."""
    row = asdict(job)
    del row["description"]
    return {**row, "score": evaluation["score"], "evaluation": evaluation, "first_seen": first_seen}


def list_jobs(cv_hash: str, min_score: int, gone_days: int = 0, today: str | None = None) -> list[dict]:
    """Jobs for the window: scored under the current CV at or above the threshold, best first. With gone_days,
    also jobs their source stopped listing in the last gone_days days (gone_at says since when)."""
    since = (date.fromisoformat(today) if today else date.today()) - timedelta(days=gone_days)
    with _connect() as conn:
        rows = conn.execute(
            f"""SELECT {JOB_FIELDS}, evaluation, first_seen, active, gone_at FROM jobs
                WHERE (active = 1 OR (? > 0 AND gone_at >= ?)) AND hidden = 0 AND status IS NULL
                  AND cv_hash = ? AND score >= ?
                ORDER BY score DESC, published DESC""",
            (gone_days, since.isoformat(), cv_hash, min_score),
        ).fetchall()
        # A gone job that is listed again under another link (a repost, or another site) is not shown twice
        listed = {same_job_key(r["company"], r["title"]) for r in conn.execute(
            "SELECT company, title FROM jobs WHERE active = 1")}
    return [{**make_row(Job(*tuple(row)[:8]), json.loads(row["evaluation"]), row["first_seen"] or ""),
             "gone_at": "" if row["active"] else row["gone_at"] or ""}
            for row in rows
            if row["active"] or row["source"] in config.NO_TWIN_SOURCES
            or same_job_key(row["company"], row["title"]) not in listed]


def list_applied() -> list[dict]:
    """Applications for the "My applications" tab: all, newest first, regardless of active, hidden and key."""
    with _connect() as conn:
        rows = conn.execute(
            f"""SELECT {JOB_FIELDS}, evaluation, status, applied_at, notes, first_seen, active FROM jobs
                WHERE status IS NOT NULL
                ORDER BY applied_at DESC, title""",
        ).fetchall()
        listed = {same_job_key(r["company"], r["title"])
                  for r in conn.execute("SELECT company, title FROM jobs WHERE active = 1")}
    return [
        {**make_row(Job(*tuple(row)[:8]), json.loads(row["evaluation"]), row["first_seen"] or ""),
         "status": row["status"], "applied_at": row["applied_at"], "notes": row["notes"] or "",
         # Only sources that return their whole list tell honestly that a job was taken down
         "closed": (not row["active"] and row["source"] in config.FULL_LIST_SOURCES
                    and same_job_key(row["company"], row["title"]) not in listed)}
        for row in rows
    ]
