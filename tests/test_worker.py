import pytest

from job_finder import config, db, llm, sources, worker
from job_finder.sources import Job


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "jobs.db")
    cv = tmp_path / "master_cv.md"
    cv.write_text("## Skills\n- Python — main language\n", encoding="utf-8")
    monkeypatch.setattr(config, "CV_PATH", cv)
    db.init()
    jobs = [Job(url=f"u{i}", source="Jobicy", title=f"Python dev {i}", company="A", city="",
                published=f"2026-10-0{i}", description="") for i in (1, 2, 3)]
    monkeypatch.setattr(sources, "fetch_all", lambda: ({"Jobicy": jobs}, {}))
    monkeypatch.setattr(llm, "prepare", lambda: None)
    released = []
    monkeypatch.setattr(llm, "release", lambda wait=True: released.append(wait))
    return released


def test_model_lost_stops_evaluation(setup, monkeypatch):
    calls = []

    def lost(cv_text, job):
        calls.append(job.url)
        raise llm.ModelLost("got an answer from qwen/qwen3.8-27b")

    monkeypatch.setattr(llm, "evaluate", lost)

    message = worker.Worker()._refresh()

    assert calls == ["u3"]  # stopped after the very first job
    assert "qwen/qwen3.8-27b" in message
    assert setup == [True]
    assert len(db.pending_jobs(worker.read_cv()[1])) == 3  # other models' scores are not saved


def test_summary_counts_suitable_and_evaluated(setup, monkeypatch):
    scores = {"u1": 7, "u2": 3, "u3": 6}
    monkeypatch.setattr(llm, "evaluate", lambda cv_text, job: {
        "score": scores[job.url], "summary": "", "have": [], "missing": [], "risks": []})

    assert worker.Worker()._refresh() == "Done: 2 matches out of 3 evaluated"


def test_missing_cv_skips_evaluation(setup, monkeypatch):
    config.CV_PATH.unlink()
    monkeypatch.setattr(llm, "evaluate", lambda cv_text, job: pytest.fail("must not evaluate"))
    assert worker.Worker()._refresh() == "No master_cv.md, evaluation skipped"


def test_key_changes_with_cv_and_rules(setup, monkeypatch):
    key = worker.read_cv()[1]
    rules = llm.RULES
    monkeypatch.setattr(llm, "RULES", rules + " other rules")
    assert worker.read_cv()[1] != key
    monkeypatch.setattr(llm, "RULES", rules)
    assert worker.read_cv()[1] == key
    config.CV_PATH.write_text("## Skills\n- SQL — x\n", encoding="utf-8")  # temporary CV from the fixture
    assert worker.read_cv()[1] != key
