import json
import sqlite3
from datetime import date

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


def test_count_evaluated_counts_current_key_only():
    db.save_jobs("Jobicy", [job("a"), job("b"), job("c")])
    db.save_evaluation("a", evaluation(7), "h1")
    db.save_evaluation("b", evaluation(2), "h1")
    db.save_evaluation("c", evaluation(8), "h2")
    assert db.count_evaluated("h1") == 2
    db.hide("b")
    assert db.count_evaluated("h1") == 1


def test_apply_moves_job_out_of_found_list():
    db.save_jobs("Jobicy", [job("a"), job("b")])
    db.save_evaluation("a", evaluation(8), "h1")
    db.save_evaluation("b", evaluation(7), "h1")
    db.apply("a")
    assert [row["url"] for row in db.list_jobs("h1", 5)] == ["b"]
    applied = db.list_applied()
    assert [(row["url"], row["status"], row["applied_at"]) for row in applied] == [
        ("a", "applied", date.today().isoformat())]
    assert applied[0]["evaluation"]["score"] == 8
    assert db.count_evaluated("h1") == 1
    assert urls(db.pending_jobs("h2")) == ["b"]  # an application is not re-evaluated even after the key changes


def test_application_survives_deactivation_and_new_key():
    db.save_jobs("Jobicy", [job("a"), job("b")])
    db.save_evaluation("a", evaluation(8), "h1")
    db.apply("a")
    db.save_jobs("Jobicy", [job("b")])  # "a" vanished from the site
    assert [row["url"] for row in db.list_applied()] == ["a"]


def test_set_status_and_unapply():
    db.save_jobs("Jobicy", [job("a")])
    db.save_evaluation("a", evaluation(8), "h1")
    db.apply("a")
    db.set_status("a", "accepted")
    applied = db.list_applied()
    assert (applied[0]["status"], applied[0]["applied_at"]) == ("accepted", date.today().isoformat())
    db.unapply("a")
    assert db.list_applied() == []
    assert [row["url"] for row in db.list_jobs("h1", 5)] == ["a"]


def test_unapply_gone_job_leaves_both_lists():
    db.save_jobs("Jobicy", [job("a")])
    db.save_evaluation("a", evaluation(8), "h1")
    db.apply("a")
    db.save_jobs("Jobicy", [])  # the job vanished from the site
    db.unapply("a")
    assert db.list_applied() == []
    assert db.list_jobs("h1", 5) == []


def test_init_adds_columns_to_old_database(tmp_path, monkeypatch):
    old = tmp_path / "old.db"
    conn = sqlite3.connect(old)
    conn.execute("""CREATE TABLE jobs (url TEXT PRIMARY KEY, source TEXT NOT NULL, title TEXT NOT NULL,
        company TEXT NOT NULL, city TEXT NOT NULL, published TEXT NOT NULL, description TEXT NOT NULL,
        active INTEGER NOT NULL DEFAULT 1, hidden INTEGER NOT NULL DEFAULT 0, score INTEGER, evaluation TEXT,
        cv_hash TEXT)""")
    conn.execute("INSERT INTO jobs VALUES ('a', 'Jobicy', 'Job a', 'ACME', 'Praha', '2026-10-01', 'Python',"
                 " 1, 0, 8, ?, 'h1')", (json.dumps(evaluation(8)),))
    conn.commit()
    conn.close()
    monkeypatch.setattr(config, "DB_PATH", old)
    db.init()
    assert [row["url"] for row in db.list_jobs("h1", 5)] == ["a"]  # data kept
    db.apply("a")
    assert db.list_applied()[0]["status"] == "applied"


def test_new_rows_are_unseen_until_marked():
    db.save_jobs("Jobicy", [job("a"), job("b")])
    assert db.unseen_urls() == {"a", "b"}
    db.save_evaluation("a", evaluation(8), "h1")
    db.save_evaluation("b", evaluation(3), "h1")  # evaluated but below the threshold: also seen
    db.mark_all_seen()
    assert db.unseen_urls() == set()
    db.save_jobs("Jobicy", [job("a"), job("c")])  # "a" was already there: stays seen
    assert db.unseen_urls() == {"c"}


def test_init_marks_existing_rows_seen(tmp_path, monkeypatch):
    old = tmp_path / "old.db"
    conn = sqlite3.connect(old)
    conn.execute("""CREATE TABLE jobs (url TEXT PRIMARY KEY, source TEXT NOT NULL, title TEXT NOT NULL,
        company TEXT NOT NULL, city TEXT NOT NULL, published TEXT NOT NULL, description TEXT NOT NULL,
        active INTEGER NOT NULL DEFAULT 1, hidden INTEGER NOT NULL DEFAULT 0, score INTEGER, evaluation TEXT,
        cv_hash TEXT, status TEXT, applied_at TEXT)""")
    conn.execute("INSERT INTO jobs (url, source, title, company, city, published, description, score, evaluation,"
                 " cv_hash) VALUES ('a', 'Jobicy', 'Job a', 'ACME', 'Praha', '2026-10-01', 'Python', 8, ?, 'h1')",
                 (json.dumps(evaluation(8)),))
    conn.commit()
    conn.close()
    monkeypatch.setattr(config, "DB_PATH", old)
    db.init()
    assert db.unseen_urls() == set()  # existing jobs do not light up as new
    assert [row["url"] for row in db.list_jobs("h1", 5)] == ["a"]
    db.save_jobs("Jobicy", [job("a"), job("b")])
    assert db.unseen_urls() == {"b"}


def test_notes_saved_and_listed():
    db.save_jobs("Jobicy", [job("a")])
    db.save_evaluation("a", evaluation(8), "h1")
    db.apply("a")
    assert db.list_applied()[0]["notes"] == ""
    db.set_notes("a", "Emailed HR on 30.09")
    assert db.list_applied()[0]["notes"] == "Emailed HR on 30.09"


def test_mark_all_seen_keeps_unevaluated_jobs_new():
    # The window was closed while the job waited for evaluation (or LM Studio did not start): never shown
    db.save_jobs("Jobicy", [job("shown"), job("queued")])
    db.save_evaluation("shown", evaluation(8), "h1")
    db.mark_all_seen()
    assert db.unseen_urls() == {"queued"}


def test_refetch_rewrites_city():
    # Rows saved before the English UI keep old place names ("Praha") until the next fetch rewrites them
    db.save_jobs("Jobicy", [Job(url="a", source="Jobicy", title="Job a", company="ACME", city="Praha",
                                published="2026-10-01", description="Python")])
    db.save_evaluation("a", evaluation(8), "h1")
    db.save_jobs("Jobicy", [Job(url="a", source="Jobicy", title="Job a", company="ACME", city="Remote",
                                published="2026-10-01", description="Python")])
    assert db.list_jobs("h1", 5)[0]["city"] == "Remote"


def test_evaluations_match_the_evaluated_count():
    db.save_jobs("Jobicy", [job("a"), job("b"), job("c"), job("d")])
    db.save_evaluation("a", evaluation(8), "h1")
    db.save_evaluation("b", evaluation(3), "h1")
    db.save_evaluation("c", evaluation(7), "h2")  # other key
    db.save_evaluation("d", evaluation(9), "h1")
    db.hide("b")
    db.apply("d")
    assert db.evaluations("h1") == [evaluation(8)]
    assert len(db.evaluations("h1")) == db.count_evaluated("h1")
