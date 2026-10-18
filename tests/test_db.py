import json
import sqlite3
from datetime import date, timedelta

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
    assert rows[0] == {**db.make_row(job("c"), evaluation(9), date.today().isoformat()), "gone_at": ""}


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
    salaried = Job(url="b", source="Himalayas", title="Job b", company="ACME", city="Remote",
                   published="2026-10-01", description="", salary="$1,000–2,000 / month")
    db.save_jobs("Himalayas", [salaried])
    assert [j.salary for j in db.pending_jobs("h2")] == ["$1,000–2,000 / month"]  # the new salary column


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


def test_first_seen_is_set_once():
    db.save_jobs("Jobicy", [job("a")], today="2026-10-01")
    db.save_jobs("Jobicy", [job("a", published="2026-10-10")], today="2026-10-12")
    assert db.first_seen("a") == "2026-10-01"


def test_first_seen_inherited_from_same_company_and_title():
    db.save_jobs("Jobicy", [job("old")], today="2026-09-01")  # "Job old" at ACME
    repost = Job(url="new", source="Himalayas", title="Job old", company="acme ", city="Remote",
                 published="2026-10-10", description="")
    db.save_jobs("Himalayas", [repost], today="2026-10-12")
    assert db.first_seen("new") == "2026-09-01"


def test_list_rows_carry_first_seen_and_description_is_read_on_demand():
    db.save_jobs("Jobicy", [job("a")], today="2026-10-01")
    db.save_evaluation("a", evaluation(8), "h1")
    assert db.list_jobs("h1", 5)[0]["first_seen"] == "2026-10-01"
    assert db.description("a") == "Python"


def test_unhide_returns_job():
    db.save_jobs("Jobicy", [job("a")])
    db.save_evaluation("a", evaluation(8), "h1")
    db.hide("a")
    db.unhide("a")
    assert [r["url"] for r in db.list_jobs("h1", 5)] == ["a"]


def test_closed_mark_only_for_full_list_sources():
    # junior.guru only shows jobs from other sites (jobs.cz, LinkedIn) and drops some early: no "probably filled"
    for url, source in [("jb", "Jobicy"), ("jg", "junior.guru"), ("him", "Himalayas")]:
        db.save_jobs(source, [Job(url=url, source=source, title="Dev", company=url, city="Remote",
                                  published="2026-10-01", description="")])
        db.save_evaluation(url, evaluation(8), "h1")
        db.apply(url)
        db.save_jobs(source, [])
    closed = {r["url"]: r["closed"] for r in db.list_applied()}
    assert closed == {"jb": True, "jg": False, "him": False}


def test_closed_mark_skipped_when_listed_elsewhere():
    jb = Job(url="jb", source="Jobicy", title="Dev", company="A", city="Remote", published="2026-10-01",
             description="")
    db.save_jobs("Jobicy", [jb])
    db.save_evaluation("jb", evaluation(8), "h1")
    db.apply("jb")
    db.save_jobs("Jobicy", [])
    db.save_jobs("Himalayas", [Job(url="him", source="Himalayas", title="dev", company="a", city="Remote",
                                   published="2026-10-02", description="")])
    assert db.list_applied()[0]["closed"] is False


def test_init_sets_first_seen_on_old_database(tmp_path, monkeypatch):
    old = tmp_path / "old.db"
    conn = sqlite3.connect(old)
    conn.execute("""CREATE TABLE jobs (url TEXT PRIMARY KEY, source TEXT NOT NULL, title TEXT NOT NULL,
        company TEXT NOT NULL, city TEXT NOT NULL, published TEXT NOT NULL, description TEXT NOT NULL,
        active INTEGER NOT NULL DEFAULT 1, hidden INTEGER NOT NULL DEFAULT 0, score INTEGER, evaluation TEXT,
        cv_hash TEXT, status TEXT, applied_at TEXT, notes TEXT, seen INTEGER NOT NULL DEFAULT 0)""")
    conn.execute("INSERT INTO jobs (url, source, title, company, city, published, description, score, evaluation,"
                 " cv_hash, seen) VALUES ('a', 'Jobicy', 'Job a', 'ACME', 'Praha', '2026-10-01', 'Python', 8, ?, 'h1', 1)",
                 (json.dumps(evaluation(8)),))
    conn.commit()
    conn.close()
    monkeypatch.setattr(config, "DB_PATH", old)
    db.init()
    assert db.first_seen("a") == "2026-10-01"  # no false "reposted" marks right after the update


def test_labour_office_jobs_keep_their_own_first_seen():
    # Its titles are profession classes: the same company and title can be a different, new job
    first = Job(url="a", source="Úřad práce", title="Vývojáři softwaru", company="Skype", city="Prague",
                published="2026-09-01", description="")
    db.save_jobs("Úřad práce", [first], today="2026-09-01")
    second = Job(url="b", source="Úřad práce", title="Vývojáři softwaru", company="Skype", city="Prague",
                 published="2026-10-18", description="")
    db.save_jobs("Úřad práce", [first, second], today="2026-10-18")
    assert db.first_seen("b") == "2026-10-18"


def test_gone_jobs_stay_listed_for_a_week():
    db.save_jobs("Jobicy", [job("a"), job("b")], today="2026-10-10")
    db.save_evaluation("a", evaluation(8), "h1")
    db.save_evaluation("b", evaluation(7), "h1")
    db.save_jobs("Jobicy", [job("b")], today="2026-10-12")  # "a" is gone from the source
    rows = db.list_jobs("h1", 5, gone_days=7, today="2026-10-15")
    assert {r["url"]: r["gone_at"] for r in rows} == {"a": "2026-10-12", "b": ""}
    assert [r["url"] for r in db.list_jobs("h1", 5)] == ["b"]  # the refresh summary counts listed jobs only
    assert [r["url"] for r in db.list_jobs("h1", 5, gone_days=7, today="2026-10-20")] == ["b"]  # a week later
    db.save_jobs("Jobicy", [job("b")], today="2026-10-16")  # still gone: the date it went stays
    assert {r["url"]: r["gone_at"] for r in db.list_jobs("h1", 5, gone_days=7, today="2026-10-16")}["a"] == \
        "2026-10-12"
    db.save_jobs("Jobicy", [job("a"), job("b")], today="2026-10-17")  # back in the list
    assert {r["url"]: r["gone_at"] for r in db.list_jobs("h1", 5, gone_days=7, today="2026-10-17")} == {
        "a": "", "b": ""}
    db.save_jobs("Jobicy", [job("b")], today="2026-10-18")  # gone again: the new date, not the old one
    assert {r["url"]: r["gone_at"] for r in db.list_jobs("h1", 5, gone_days=7, today="2026-10-18")}["a"] == \
        "2026-10-18"


def test_update_shows_recently_gone_jobs_for_a_week(tmp_path, monkeypatch):
    # Before this version nobody noted when a job went: one seen in the last month counts as gone today
    # (so a good job that just vanished comes back for a week); older ones stay hidden
    old = tmp_path / "old.db"
    conn = sqlite3.connect(old)
    conn.execute("""CREATE TABLE jobs (url TEXT PRIMARY KEY, source TEXT NOT NULL, title TEXT NOT NULL,
        company TEXT NOT NULL, city TEXT NOT NULL, published TEXT NOT NULL, description TEXT NOT NULL,
        active INTEGER NOT NULL DEFAULT 1, hidden INTEGER NOT NULL DEFAULT 0, score INTEGER, evaluation TEXT,
        cv_hash TEXT)""")
    for url, days in [("recent", 3), ("old", 60)]:
        published = (date.today() - timedelta(days=days)).isoformat()
        conn.execute("INSERT INTO jobs VALUES (?, 'Jobicy', ?, 'ACME', 'Praha', ?, '', 0, 0, 8, ?, 'h1')",
                     (url, f"Job {url}", published, json.dumps(evaluation(8))))
    conn.commit()
    conn.close()
    monkeypatch.setattr(config, "DB_PATH", old)
    db.init()
    db.save_jobs("Jobicy", [])
    assert {r["url"]: r["gone_at"] for r in db.list_jobs("h1", 5, gone_days=7)} == {
        "recent": date.today().isoformat()}


def test_gone_job_not_shown_next_to_its_repost():
    first = Job(url="a1", source="Jobicy", title="Dev", company="ACME", city="Remote", published="2026-10-01",
                description="")
    db.save_jobs("Jobicy", [first], today="2026-10-10")
    db.save_evaluation("a1", evaluation(8), "h1")
    db.save_jobs("Jobicy", [Job(url="a2", source="Jobicy", title="Dev", company="ACME", city="Remote",
                                published="2026-10-11", description="")], today="2026-10-11")  # a new link
    db.save_evaluation("a2", evaluation(8), "h1")
    assert [r["url"] for r in db.list_jobs("h1", 5, gone_days=7, today="2026-10-12")] == ["a2"]
    # The labour office's titles are profession classes: another job with the same title is not the same job
    for url, day in [("u1", "2026-10-10"), ("u2", "2026-10-11")]:
        db.save_jobs("Úřad práce", [Job(url=url, source="Úřad práce", title="Vývojáři softwaru", company="Skype",
                                        city="Prague", published=day, description="")], today=day)
        db.save_evaluation(url, evaluation(7), "h1")
    assert {r["url"] for r in db.list_jobs("h1", 5, gone_days=7, today="2026-10-12")} >= {"u1", "u2"}


def test_sources_not_fetched_are_not_gone():
    # Remote turned off: the remote sites aren't asked, their jobs are not "no longer listed"
    db.save_jobs("Remote OK", [job("r", source="Remote OK")], today="2026-10-10")
    db.save_evaluation("r", evaluation(8), "h1")
    db.save_jobs("Remote OK", [], today="2026-10-11", fetched=False)
    assert db.list_jobs("h1", 5, gone_days=7, today="2026-10-12") == []


def test_recently_gone_jobs_are_scored_again():
    # After a CV or settings change a job still shown as "no longer listed" needs its new score
    db.save_jobs("Jobicy", [job("a"), job("old")], today="2026-10-01")
    db.save_jobs("Jobicy", [job("old")], today="2026-10-10")  # "a" is gone since 10-10
    assert set(urls(db.pending_jobs("new", gone_days=7, today="2026-10-12"))) == {"a", "old"}
    assert urls(db.pending_jobs("new")) == ["old"]  # without gone_days: listed jobs only
    assert urls(db.pending_jobs("new", gone_days=7, today="2026-10-30")) == ["old"]  # gone over a week ago
