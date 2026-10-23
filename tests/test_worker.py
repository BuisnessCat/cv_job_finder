from pathlib import Path
from dataclasses import replace
from datetime import date, timedelta

import pytest
from helpers import model_answer, use_settings

from job_finder import config, db, llm, lmstudio, settings, sources, worker
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
    monkeypatch.setattr(llm, "prepare", lambda model: None)
    monkeypatch.setattr(lmstudio, "everything_ready", lambda model: True)
    # Not the real "Windows is busy" check: a full-screen app open while the tests run would pause the scoring
    monkeypatch.setattr(worker.Worker, "pause_check", staticmethod(lambda: False))
    released = []
    monkeypatch.setattr(llm, "release", lambda wait=True: released.append(wait))
    return released


def test_model_lost_stops_evaluation(setup, monkeypatch):
    calls = []

    def lost(cv_text, job, rules, facts=""):
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
    monkeypatch.setattr(llm, "evaluate", lambda cv_text, job, rules, facts="": model_answer(scores[job.url]))

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
    monkeypatch.setattr(llm, "evaluate", lambda cv_text, job, rules, facts="": model_answer(scores[job.url]))

    assert worker.Worker()._refresh() == "Done: 1 match out of 3 evaluated"


def test_evaluated_rows_carry_first_seen(setup, monkeypatch):
    monkeypatch.setattr(llm, "evaluate", lambda cv_text, job, rules, facts="": model_answer(7))
    w = worker.Worker()
    rows = []
    w.evaluated.connect(rows.append)
    w._refresh()
    assert len(rows) == 3 and all(r["first_seen"] for r in rows)


def test_remote_sources_not_fetched_are_saved_as_such(setup, monkeypatch):
    settings.save(replace(settings.load(), remote=False))
    monkeypatch.setattr(sources, "fetch_all", lambda s: ({"Jobicy": [], "junior.guru": []}, {}))
    saved = []
    monkeypatch.setattr(db, "save_jobs", lambda name, jobs, **kwargs: saved.append((name, kwargs.get("fetched", True))))
    worker.Worker()._refresh()
    assert dict(saved) == {"Jobicy": False, "junior.guru": True}  # Jobicy is remote-only: not asked, not gone


def test_old_jobs_are_not_scored(setup, monkeypatch):
    # Older than the widest freshness filter (30 days): the model's time is not spent on them
    jobs = [Job(url=url, source="Jobicy", title=f"Python dev {url}", company="A", city="", published=published,
                description="") for url, published in [("old", days_ago(31)), ("month", days_ago(30)),
                                                       ("undated", "")]]
    monkeypatch.setattr(sources, "fetch_all", lambda s: ({"Jobicy": jobs}, {}))
    scored = []
    monkeypatch.setattr(llm, "evaluate", lambda cv_text, job, rules, facts="": scored.append(job.url) or model_answer(6))
    worker.Worker()._refresh()
    assert sorted(scored) == ["month", "undated"]


def test_scoring_pauses_while_windows_is_busy(setup, monkeypatch):
    answers = iter([False, True])  # a full-screen game starts after the first job
    monkeypatch.setattr(worker.Worker, "pause_check", staticmethod(lambda: next(answers)))
    scored = []
    monkeypatch.setattr(llm, "evaluate", lambda cv_text, job, rules, facts="": scored.append(job.url) or model_answer(6))
    w = worker.Worker()
    message = w._refresh()
    assert len(scored) == 1 and w.paused and message.startswith("Paused")
    assert setup == [True]  # the model is unloaded, the game gets the graphics card


def test_no_model_no_loading(setup, monkeypatch):
    monkeypatch.setattr(lmstudio, "everything_ready", lambda model: False)
    monkeypatch.setattr(lmstudio, "lms_installed", lambda: True)
    monkeypatch.setattr(llm, "prepare", lambda model: pytest.fail("no model: nothing to load"))
    w = worker.Worker()
    assert w._refresh() == "The AI model isn't downloaded yet: click Get AI model"
    assert w.model_missing
    monkeypatch.setattr(lmstudio, "downloading", True)
    assert w._refresh() == "Downloading the AI model: the jobs will be scored when it has finished"
    monkeypatch.setattr(lmstudio, "downloading", False)
    monkeypatch.setattr(lmstudio, "lms_installed", lambda: False)
    assert w._refresh() == "LM Studio isn't installed: click Get AI model"
    monkeypatch.setattr(lmstudio, "everything_ready", lambda model: True)
    monkeypatch.setattr(llm, "prepare", lambda model: None)
    monkeypatch.setattr(llm, "evaluate", lambda cv_text, job, rules, facts="": model_answer(6))
    assert w._refresh() == "Done: 3 matches out of 3 evaluated"
    assert not w.model_missing


def test_scoring_goes_on_with_the_copy_when_the_cv_file_is_gone(setup, monkeypatch):
    monkeypatch.setattr(llm, "evaluate", lambda cv_text, job, rules, facts="": model_answer(7))
    worker.Worker()._refresh()  # the copy is made
    key = worker.read_cv(settings.load())[1]
    Path(settings.load().cv_path).unlink()
    monkeypatch.setattr(llm, "evaluate", lambda *args: pytest.fail("nothing new to score"))
    message = worker.Worker()._refresh()
    assert "the saved copy is used" in message
    assert worker.read_cv(settings.load())[1] == key  # same key: nothing is scored again


def test_a_big_scoring_waits_unless_asked(setup, monkeypatch):
    monkeypatch.setattr(config, "BIG_PASS_JOBS", 2)
    monkeypatch.setattr(llm, "evaluate", lambda *args: pytest.fail("a big pass waits for the user"))
    w = worker.Worker()
    assert w._refresh() == "3 jobs to score (about 1 min): click Start scoring"
    assert w.waiting == 3
    monkeypatch.setattr(llm, "evaluate", lambda cv_text, job, rules, facts="": model_answer(7))
    w.manual = True  # the button, the setup's Start search, or Save in Settings
    assert w._refresh() == "Done: 3 matches out of 3 evaluated" and w.waiting == 0


def test_cancel_stops_after_the_current_job(setup, monkeypatch):
    w = worker.Worker()
    calls = []

    def evaluate(cv_text, job, rules, facts=""):
        calls.append(job.url)
        w.cancel()  # Save in Settings while this job is scored
        return model_answer(7)

    monkeypatch.setattr(llm, "evaluate", evaluate)
    assert w._refresh().startswith("Stopped: the settings changed")
    assert len(calls) == 1 and setup == [True]  # the model is released


def test_an_edited_cv_file_starts_over(setup, monkeypatch):
    w = worker.Worker()
    calls = []

    def evaluate(cv_text, job, rules, facts=""):
        calls.append(job.url)
        cv = Path(settings.load().cv_path)
        stat = cv.stat()
        cv.write_text("Python and SQL developer", encoding="utf-8")  # saved in its own program
        import os
        os.utime(cv, ns=(stat.st_mtime_ns + 10**9, stat.st_mtime_ns + 10**9))
        return model_answer(7)

    monkeypatch.setattr(llm, "evaluate", evaluate)
    assert w._refresh().startswith("Your CV changed")
    assert len(calls) == 1 and w.cv_changed


def test_the_scoring_never_overwrites_settings_saved_meanwhile(setup):
    stale = settings.load()  # what the pass read at its start
    settings.save(replace(stale, city="Brno"))  # Save in Settings during the pass
    settings.sync_cv(stale)
    assert settings.load().city == "Brno" and settings.load().cv_stamp
