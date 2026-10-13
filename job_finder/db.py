"""Хранение вакансий и оценок в одном файле SQLite."""
import json
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict

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
    score       INTEGER,            -- NULL, пока не оценена
    evaluation  TEXT,               -- JSON-ответ модели
    cv_hash     TEXT                -- SHA-256 master_cv.md на момент оценки
)
"""

# Порядок совпадает с полями Job
JOB_FIELDS = "url, source, title, company, city, published, description"


@contextmanager
def _connect():
    # Своё короткое соединение на каждый вызов: базой пользуются и окно, и фоновый поток
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        with conn:  # коммит или откат транзакции
            yield conn
    finally:
        conn.close()


def init() -> None:
    with _connect() as conn:
        conn.execute(SCHEMA)


def save_jobs(source: str, jobs: list[Job]) -> None:
    """Записать свежую выборку источника; его вакансии, которых в ней нет, становятся неактивными."""
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
    """Активные нескрытые вакансии без оценки по текущему резюме, сначала самые новые."""
    with _connect() as conn:
        rows = conn.execute(
            f"""SELECT {JOB_FIELDS} FROM jobs
                WHERE active = 1 AND hidden = 0 AND (cv_hash IS NULL OR cv_hash != ?)
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


def make_row(job: Job, evaluation: dict) -> dict:
    """Строка для окна: поля вакансии без описания, оценка и разбор модели."""
    row = asdict(job)
    del row["description"]
    return {**row, "score": evaluation["score"], "evaluation": evaluation}


def list_jobs(cv_hash: str, min_score: int) -> list[dict]:
    """Вакансии для окна: оценка по текущему резюме не ниже порога, лучшие сверху."""
    with _connect() as conn:
        rows = conn.execute(
            f"""SELECT {JOB_FIELDS}, evaluation FROM jobs
                WHERE active = 1 AND hidden = 0 AND cv_hash = ? AND score >= ?
                ORDER BY score DESC, published DESC""",
            (cv_hash, min_score),
        ).fetchall()
    return [make_row(Job(*tuple(row)[:7]), json.loads(row["evaluation"])) for row in rows]
