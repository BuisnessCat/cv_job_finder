import pytest

from job_finder import config, db
from job_finder.sources import Job


@pytest.fixture(autouse=True)
def tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "jobs.db")
    db.init()


def job(url, source="Jobicy", published="2026-10-01"):
    return Job(url=url, source=source, title=f"Job {url}", company="ACME", city="Praha",
               published=published, description="Python")


def evaluation(score):
    return {"score": score, "summary": "ok", "have": ["Python"], "missing": [], "risks": []}


def urls(jobs):
    return [j.url for j in jobs]


def test_pending_contains_new_jobs_newest_first():
    db.save_jobs("Jobicy", [job("a", published="2026-10-01"), job("b", published="2026-10-05")])
    assert urls(db.pending_jobs("h1")) == ["b", "a"]


def test_resave_keeps_evaluation_and_hidden():
    db.save_jobs("Jobicy", [job("a"), job("b")])
    db.save_evaluation("a", evaluation(7), "h1")
    db.hide("b")
    db.save_jobs("Jobicy", [job("a"), job("b")])
    assert [row["url"] for row in db.list_jobs("h1", 5)] == ["a"]
    assert db.pending_jobs("h1") == []


def test_jobs_missing_from_source_are_deactivated():
    db.save_jobs("Jobicy", [job("a"), job("b")])
    db.save_jobs("Himalayas", [job("c", source="Himalayas")])
    for url in ("a", "b", "c"):
        db.save_evaluation(url, evaluation(8), "h1")
    db.save_jobs("Jobicy", [job("a")])
    assert sorted(row["url"] for row in db.list_jobs("h1", 5)) == ["a", "c"]


def test_cv_change_puts_jobs_back_in_queue():
    db.save_jobs("Jobicy", [job("a")])
    db.save_evaluation("a", evaluation(8), "h1")
    assert db.pending_jobs("h1") == []
    assert urls(db.pending_jobs("h2")) == ["a"]
    assert db.list_jobs("h2", 5) == []


def test_hidden_job_not_in_queue_or_list():
    db.save_jobs("Jobicy", [job("a"), job("b")])
    db.save_evaluation("a", evaluation(8), "h1")
    db.hide("a")
    db.hide("b")
    assert db.pending_jobs("h1") == []
    assert db.list_jobs("h1", 5) == []


def test_list_filters_by_threshold_and_sorts():
    db.save_jobs("Jobicy", [job("a"), job("b"), job("c"), job("d", published="2026-10-05")])
    for url, score in [("a", 6), ("b", 4), ("c", 9), ("d", 6)]:
        db.save_evaluation(url, evaluation(score), "h1")
    rows = db.list_jobs("h1", 5)
    assert [row["url"] for row in rows] == ["c", "d", "a"]
    assert rows[0] == db.make_row(job("c"), evaluation(9))


def test_duplicate_url_in_one_batch():
    db.save_jobs("Himalayas", [job("a", source="Himalayas"), job("a", source="Himalayas")])
    assert urls(db.pending_jobs("h1")) == ["a"]
