"""Хранение вакансий и оценок в одном файле SQLite."""
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
    score       INTEGER,            -- NULL, пока не оценена
    evaluation  TEXT,               -- JSON-ответ модели
    cv_hash     TEXT,               -- ключ оценки: SHA-256 резюме, модели и правил
    status      TEXT,               -- отклик: NULL, 'applied', 'accepted', 'rejected'
    applied_at  TEXT,               -- дата отклика YYYY-MM-DD
    notes       TEXT,               -- заметка к отклику
    seen        INTEGER NOT NULL DEFAULT 0  -- 0 — появилась после прошлого закрытия окна (новая)
)
"""

# Порядок совпадает с полями Job
JOB_FIELDS = "url, source, title, company, city, published, description"

STATUSES = ("applied", "accepted", "rejected")  # ждём ответа, приняли, отказали


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
        # База, созданная до новых колонок: добавить недостающие, вакансии и оценки сохраняются
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(jobs)")}
        for column in ("status", "applied_at", "notes"):
            if column not in columns:
                conn.execute(f"ALTER TABLE jobs ADD COLUMN {column} TEXT")
        if "seen" not in columns:
            conn.execute("ALTER TABLE jobs ADD COLUMN seen INTEGER NOT NULL DEFAULT 0")
            conn.execute("UPDATE jobs SET seen = 1")  # имевшиеся вакансии — уже просмотренные, не новые


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
    """Активные нескрытые вакансии без отклика и без оценки по текущему ключу, сначала самые новые."""
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
    """«Подался»: вакансия уходит из найденных в отклики со статусом «ждём ответа» и сегодняшней датой."""
    with _connect() as conn:
        conn.execute("UPDATE jobs SET status = 'applied', applied_at = ? WHERE url = ?",
                     (date.today().isoformat(), url))


def set_status(url: str, status: str) -> None:
    """Итог отклика: один из STATUSES; дата отклика не меняется."""
    with _connect() as conn:
        conn.execute("UPDATE jobs SET status = ? WHERE url = ?", (status, url))


def unapply(url: str) -> None:
    """«Вернуть в найденные»: убрать статус и дату отклика."""
    with _connect() as conn:
        conn.execute("UPDATE jobs SET status = NULL, applied_at = NULL WHERE url = ?", (url,))


def set_notes(url: str, notes: str) -> None:
    """Заметка к отклику: с кем общались, когда собеседование."""
    with _connect() as conn:
        conn.execute("UPDATE jobs SET notes = ? WHERE url = ?", (notes, url))


def mark_all_seen() -> None:
    """Отметить просмотренными (при закрытии окна) все оценённые вакансии: новыми станут только пришедшие потом.

    Ещё не оценённые (ждали в очереди, LM Studio не поднялась) окно показать не могло — они остаются новыми."""
    with _connect() as conn:
        conn.execute("UPDATE jobs SET seen = 1 WHERE seen = 0 AND score IS NOT NULL")


def unseen_urls() -> set[str]:
    """url вакансий, появившихся после прошлого закрытия окна."""
    with _connect() as conn:
        return {row["url"] for row in conn.execute("SELECT url FROM jobs WHERE seen = 0")}


def count_evaluated(cv_hash: str) -> int:
    """Сколько активных нескрытых вакансий оценено с текущим ключом."""
    with _connect() as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM jobs WHERE active = 1 AND hidden = 0 AND status IS NULL AND cv_hash = ?",
            (cv_hash,),
        ).fetchone()[0]


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
                WHERE active = 1 AND hidden = 0 AND status IS NULL AND cv_hash = ? AND score >= ?
                ORDER BY score DESC, published DESC""",
            (cv_hash, min_score),
        ).fetchall()
    return [make_row(Job(*tuple(row)[:7]), json.loads(row["evaluation"])) for row in rows]


def list_applied() -> list[dict]:
    """Отклики для вкладки «Мои отклики»: все, новые сверху, независимо от active, hidden и ключа оценки."""
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
