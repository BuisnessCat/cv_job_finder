import json
import subprocess
from dataclasses import replace

import pytest

from job_finder import config, llm
from job_finder.settings import Settings
from job_finder.sources import Job


class FakeResponse:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self._data


def test_evaluate_sends_cv_and_truncated_vacancy(monkeypatch):
    sent = {}
    answer = {"score": "7", "summary": "Good fit", "have": ["Python"], "missing": ["Django"], "risks": []}

    def fake_post(url, **kwargs):
        sent.update(url=url, **kwargs)
        return FakeResponse({"model": config.MODEL_ID, "choices": [{"message": {"content": json.dumps(answer)}}]})

    monkeypatch.setattr(llm.requests, "post", fake_post)
    job = Job(url="u", source="Jobicy", title="Python Dev", company="ACME", city="Prague",
              published="2026-10-01", description="x" * 20000)

    result = llm.evaluate("MY CV", job, "RULES-TEXT")

    assert result == {**answer, "score": 7}
    assert sent["url"] == f"{config.LM_URL}/chat/completions"
    body = sent["json"]
    assert body["model"] == config.MODEL_ID
    assert body["response_format"]["type"] == "json_schema"
    assert body["messages"][0]["content"] == "RULES-TEXT" + "MY CV"
    user = body["messages"][1]["content"]
    assert "Python Dev" in user and "ACME" in user and "Prague" in user
    assert user.count("x") == config.MAX_DESCRIPTION_CHARS
    assert user.startswith("Title: Python Dev\nCompany: ACME\nLocation: Prague\nSource: Jobicy\n\n")


def test_evaluate_rejects_answer_from_another_model(monkeypatch):
    # If our model was unloaded (e.g. from the LM Studio window), the server answers with another model
    answer = {"score": 5, "summary": "", "have": [], "missing": [], "risks": []}
    monkeypatch.setattr(llm.requests, "post", lambda url, **kwargs: FakeResponse(
        {"model": "qwen/qwen3.8-27b", "choices": [{"message": {"content": json.dumps(answer)}}]}))
    job = Job(url="u", source="Jobicy", title="Python Dev", company="ACME", city="", published="2026-10-01",
              description="")
    with pytest.raises(llm.ModelLost, match="qwen/qwen3.8-27b"):
        llm.evaluate("CV", job, "RULES")


def test_prepare_starts_server_without_capturing_output(tmp_path, monkeypatch):
    # The LM Studio service started by the command may inherit captured output pipes,
    # and then subprocess.run waits for them to close forever, despite the timeout
    exe = tmp_path / "lms.exe"
    exe.write_text("")
    monkeypatch.setattr(config, "LMS_EXE", exe)
    states = iter([False, True])
    monkeypatch.setattr(llm, "_server_up", lambda: next(states))
    calls = []

    def fake_run(args, **kwargs):
        calls.append((args[1:], kwargs))
        return subprocess.CompletedProcess(args, 0, stdout=f'[{{"identifier": "{config.MODEL_ID}"}}]', stderr="")

    monkeypatch.setattr(llm.subprocess, "run", fake_run)
    llm.prepare()
    (start_args, start_kwargs), (ps_args, _) = calls
    assert start_args[:2] == ["server", "start"]
    assert start_kwargs.get("stdout") is subprocess.DEVNULL
    assert start_kwargs.get("stderr") is subprocess.DEVNULL
    assert ps_args == ["ps", "--json"]


def test_rules_follow_settings():
    s = Settings(cv_path="a", skills=["Java"], main_skill="Java", city="Brno", remote=False,
                 levels=["intern", "junior"], languages={"English": "C1", "Russian": "Native"})
    rules = llm.render_rules(s)
    assert "Brno" in rules and "remote-only jobs are not a fit" in rules
    assert "internship or junior roles" in rules and "2+ years" in rules  # the blocker of the highest level
    assert "English C1" in rules and "Russian native" in rules
    assert "permit" not in rules.lower()
    assert "student" not in rules.lower() and "(Java, C#" not in rules  # nothing assumes a Python student
    senior = llm.render_rules(replace(s, levels=["senior"]))
    assert "10+ years" in senior and "clearly below senior level" in senior
    mid = llm.render_rules(replace(s, levels=["mid", "senior"]))
    assert "clearly below mid level" in mid and "level level" not in mid
    assert "Write all texts in English" in rules and rules.endswith("Candidate's CV:" + chr(10))


def test_fingerprint_ignores_skills_and_main_skill():
    s = Settings(cv_path="a", skills=["Python"], main_skill="Python", languages={"English": "B2"})
    assert llm.fingerprint(s) == llm.fingerprint(replace(s, skills=["Go"], main_skill="Go", min_score=7))
    assert llm.fingerprint(s) != llm.fingerprint(replace(s, levels=["mid"]))
    assert llm.fingerprint(s) != llm.fingerprint(replace(s, languages={"English": "C1"}))
