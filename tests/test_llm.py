import json
import subprocess
from dataclasses import replace

import pytest

from job_finder import config, grounding, hardware, llm
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
    answer = {"requirements": [{"requirement": "Python", "required": True, "match": "yes"}], "blockers": [],
              "summary": "Good fit"}

    def fake_post(url, **kwargs):
        sent.update(url=url, **kwargs)
        return FakeResponse({"model": config.MODEL_ID, "choices": [{"message": {"content": json.dumps(answer)}}]})

    monkeypatch.setattr(llm.requests, "post", fake_post)
    job = Job(url="u", source="Jobicy", title="Python Dev", company="ACME", city="Prague",
              published="2026-10-01", description="x" * 20000)

    result = llm.evaluate("MY CV", job, "RULES-TEXT")

    assert result == answer  # the program counts the score
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
    answer = {"requirements": [], "blockers": [], "summary": ""}
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
    llm.prepare(config.MODEL)
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


def test_fingerprint_uses_model(monkeypatch):
    s = Settings(cv_path="a", skills=["Python"], main_skill="Python", languages={"English": "B2"})
    assert llm.model_name(s) == config.MODEL  # chosen by the graphics card (12 GB in the tests' fixture)
    assert llm.fingerprint(s) == f"{config.MODEL}\n{llm.render_rules(s)}"  # the author's key stays the same
    small = replace(s, model="mistralai/ministral-3-3b")
    assert llm.model_name(small) == "mistralai/ministral-3-3b" and llm.fingerprint(small) != llm.fingerprint(s)
    monkeypatch.setattr(hardware, "default_model", lambda: "mistralai/ministral-3-3b")  # a 6 GB card
    assert llm.model_name(s) == "mistralai/ministral-3-3b"


def test_prepare_reloads_another_model(tmp_path, monkeypatch):
    exe = tmp_path / "lms.exe"
    exe.write_text("")
    monkeypatch.setattr(config, "LMS_EXE", exe)
    monkeypatch.setattr(llm, "_server_up", lambda: True)
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args[1:])
        out = (f'[{{"identifier": "{config.MODEL_ID}", "modelKey": "mistralai/ministral-3-8b"}}]'
               if args[1] == "ps" else "")
        return subprocess.CompletedProcess(args, 0, stdout=out, stderr="")

    monkeypatch.setattr(llm.subprocess, "run", fake_run)
    llm.prepare("mistralai/ministral-3-3b")  # another model is loaded under our name
    assert [call[0] for call in calls] == ["ps", "unload", "load"] and calls[2][1] == "mistralai/ministral-3-3b"
    calls.clear()
    llm.prepare("mistralai/ministral-3-8b")  # the right one is loaded already
    assert [call[0] for call in calls] == ["ps"]


def test_downloaded_models_reads_lms_output_from_a_file(monkeypatch):
    # Not a pipe: lms may start LM Studio's service, which would inherit a pipe and keep the call waiting forever
    seen = {}

    def fake_run(args, **kwargs):
        seen.update(kwargs)
        kwargs["stdout"].write('[{"type": "llm", "modelKey": "mistralai/ministral-3-8b"}]')
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(llm.subprocess, "run", fake_run)
    assert llm.downloaded_models() == {"mistralai/ministral-3-8b"}
    assert hasattr(seen["stdout"], "fileno") and seen["stdout"] is not subprocess.PIPE and "capture_output" not in seen


def test_clean_output():
    assert llm.clean_output("\x1b[31mError\x1b[0m: no model\n") == "Error: no model"
    assert llm.clean_output("x" * 500) == "x" * 300


def test_evaluate_ends_the_ad_with_the_programs_facts(monkeypatch):
    sent = {}
    answer = {"requirements": [], "blockers": [], "summary": ""}

    def fake_post(url, **kwargs):
        sent.update(kwargs)
        return FakeResponse({"model": config.MODEL_ID, "choices": [{"message": {"content": json.dumps(answer)}}]})

    monkeypatch.setattr(llm.requests, "post", fake_post)
    job = Job(url="u", source="Jobicy", title="Dev", company="A", city="", published="", description="We use C#.")
    llm.evaluate("CV", job, "RULES", "Technologies this ad names (found by a program, reliable): C#/.NET.")
    assert sent["json"]["messages"][1]["content"].endswith(
        "We use C#.\n\nTechnologies this ad names (found by a program, reliable): C#/.NET.")


def test_rules_ask_for_requirements_not_a_score():
    rules = llm.render_rules(Settings(cv_path="a", skills=["C/C++"], main_skill="C/C++", levels=["junior"],
                                      languages={"English": "B2"}))
    assert "You do not give a" in rules and "a program counts the score" in rules
    assert "C, C++ and C# are three different languages" in rules and "Java is not JavaScript" in rules
    assert "the technologies a program found in it" in rules and "rely on that list" in rules
    assert "never add a technology the ad does not name" in rules and "do not invent requirements" in rules
    assert "Scale:" not in rules  # no score bands any more
    assert set(llm.SCHEMA["properties"]["blockers"]["items"]["properties"]["kind"]["enum"]) == set(grounding.CAPS)
