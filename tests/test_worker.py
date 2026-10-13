from job_finder import config, db, llm, sources, worker
from job_finder.sources import Job


def test_model_lost_stops_evaluation(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "jobs.db")
    cv = tmp_path / "master_cv.md"
    cv.write_text("## Skills\n- Python — main language\n", encoding="utf-8")
    monkeypatch.setattr(config, "CV_PATH", cv)
    db.init()
    jobs = [Job(url=f"u{i}", source="Jobicy", title=f"Python dev {i}", company="A", city="",
                published=f"2026-10-0{i}", description="") for i in (1, 2, 3)]
    monkeypatch.setattr(sources, "fetch_all", lambda: ({"Jobicy": jobs}, {}))
    calls, released = [], []

    def lost(cv_text, job):
        calls.append(job.url)
        raise llm.ModelLost("ответила qwen/qwen3.8-27b")

    monkeypatch.setattr(llm, "prepare", lambda: None)
    monkeypatch.setattr(llm, "evaluate", lost)
    monkeypatch.setattr(llm, "release", lambda wait=True: released.append(wait))

    message = worker.Worker()._refresh()

    assert calls == ["u3"]  # остановились после первой же вакансии
    assert "qwen/qwen3.8-27b" in message
    assert released == [True]
    assert len(db.pending_jobs(worker.read_cv()[1])) == 3  # чужие оценки не сохранены
