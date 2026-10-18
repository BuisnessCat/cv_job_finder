from pathlib import Path
from dataclasses import replace
from datetime import date, timedelta

import pytest
from helpers import use_settings

from job_finder import config, db, llm, settings, sources, worker
from job_finder.sources import Job


def days_ago(n):
    return (date.today() - timedelta(days=n)).isoformat()


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "jobs.db")
    cv = tmp_path / "master_cv.md"
    db.init()
    use_settings(cv)
    jobs = [Job(url=f"u{i}", source="Jobicy", title=f"Python dev {i}", company="A", city="",
                published=days_ago(4 - i), description="") for i in (1, 2, 3)]  # u3 is the newest
    monkeypatch.setattr(sources, "fetch_all", lambda s: ({"Jobicy": jobs}, {}))
    monkeypatch.setattr(llm, "prepare", lambda: None)
    # Not the real "Windows is busy" check: a full-screen app open while the tests run would pause the scoring
    monkeypatch.setattr(worker.Worker, "pause_check", staticmethod(lambda: False))
    released = []
    monkeypatch.setattr(llm, "release", lambda wait=True: released.append(wait))
    return released


def test_model_lost_stops_evaluation(setup, monkeypatch):
    calls = []

    def lost(cv_text, job, rules):
        calls.append(job.url)
        raise llm.ModelLost("got an answer from qwen/qwen3.8-27b")

    monkeypatch.setattr(llm, "evaluate", lost)

    message = worker.Worker()._refresh()

    assert calls == ["u3"]  # stopped after the very first job
    assert "qwen/qwen3.8-27b" in message
    assert setup == [True]
    assert len(db.pending_jobs(worker.read_cv(settings.load())[1])) == 3  # other models' scores are not saved


def test_summary_counts_suitable_and_evaluated(setup, monkeypatch):
    scores = {"u1": 7, "u2": 3, "u3": 6}
    monkeypatch.setattr(llm, "evaluate", lambda cv_text, job, rules: {
        "score": scores[job.url], "summary": "", "have": [], "missing": [], "risks": []})

    assert worker.Worker()._refresh() == "Done: 2 matches out of 3 evaluated"


def test_incomplete_settings_stop_the_refresh(setup, monkeypatch):
    settings.save(replace(settings.load(), languages={}))  # e.g. saved by an older version of the app
    monkeypatch.setattr(sources, "fetch_all", lambda s: pytest.fail("nothing is fetched without complete settings"))
    assert worker.Worker()._refresh() == "Finish the setup in Settings first"


def test_unreadable_cv_stops_before_evaluation(setup, monkeypatch):
    s = settings.load()
    settings.save(replace(s, cv_path=s.cv_path + ".missing"))
    monkeypatch.setattr(llm, "evaluate", lambda *a: pytest.fail("must not evaluate"))
    assert worker.Worker()._refresh().startswith("Can't read your CV")


def test_key_changes_with_cv_and_scoring_settings(setup):
    s = settings.load()
    key = worker.read_cv(s)[1]
    assert worker.read_cv(replace(s, city="Brno"))[1] != key
    assert worker.read_cv(replace(s, main_skill="Go", skills=["Go"]))[1] == key
    Path(s.cv_path).write_text("Senior SQL developer", encoding="utf-8")  # temporary CV from the fixture
    assert worker.read_cv(s)[1] != key
    assert worker.read_cv(None) is None


def test_summary_uses_singular_for_one_match(setup, monkeypatch):
    scores = {"u1": 7, "u2": 3, "u3": 2}
    monkeypatch.setattr(llm, "evaluate", lambda cv_text, job, rules: {
        "score": scores[job.url], "summary": "", "have": [], "missing": [], "risks": []})

    assert worker.Worker()._refresh() == "Done: 1 match out of 3 evaluated"


def test_evaluated_rows_carry_first_seen(setup, monkeypatch):
    monkeypatch.setattr(llm, "evaluate", lambda cv_text, job, rules: {
        "score": 7, "summary": "", "have": [], "missing": [], "risks": []})
    w = worker.Worker()
    rows = []
    w.evaluated.connect(rows.append)
    w._refresh()
    assert len(rows) == 3 and all(r["first_seen"] for r in rows)


def test_old_jobs_are_not_scored(setup, monkeypatch):
    # Older than the widest freshness filter (30 days): the model's time is not spent on them
    jobs = [Job(url=url, source="Jobicy", title=f"Python dev {url}", company="A", city="", published=published,
                description="") for url, published in [("old", days_ago(31)), ("month", days_ago(30)),
                                                       ("undated", "")]]
    monkeypatch.setattr(sources, "fetch_all", lambda s: ({"Jobicy": jobs}, {}))
    scored = []
    monkeypatch.setattr(llm, "evaluate", lambda cv_text, job, rules: scored.append(job.url) or {
        "score": 6, "summary": "", "have": [], "missing": [], "risks": []})
    worker.Worker()._refresh()
    assert sorted(scored) == ["month", "undated"]


def test_scoring_pauses_while_windows_is_busy(setup, monkeypatch):
    answers = iter([False, True])  # a full-screen game starts after the first job
    monkeypatch.setattr(worker.Worker, "pause_check", staticmethod(lambda: next(answers)))
    scored = []
    monkeypatch.setattr(llm, "evaluate", lambda cv_text, job, rules: scored.append(job.url) or {
        "score": 6, "summary": "", "have": [], "missing": [], "risks": []})
    w = worker.Worker()
    message = w._refresh()
    assert len(scored) == 1 and w.paused and message.startswith("Paused")
    assert setup == [True]  # the model is unloaded, the game gets the graphics card
