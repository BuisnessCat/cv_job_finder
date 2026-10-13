import json

from job_finder import config, llm
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
    answer = {"score": "7", "summary": "Подходит", "have": ["Python"], "missing": ["Django"], "risks": []}

    def fake_post(url, **kwargs):
        sent.update(url=url, **kwargs)
        return FakeResponse({"choices": [{"message": {"content": json.dumps(answer)}}]})

    monkeypatch.setattr(llm.requests, "post", fake_post)
    job = Job(url="u", source="Jobicy", title="Python Dev", company="ACME", city="Praha",
              published="2026-10-01", description="x" * 20000)

    result = llm.evaluate("МОЁ РЕЗЮМЕ", job)

    assert result == {**answer, "score": 7}
    assert sent["url"] == f"{config.LM_URL}/chat/completions"
    body = sent["json"]
    assert body["model"] == config.MODEL_ID
    assert body["response_format"]["type"] == "json_schema"
    assert body["messages"][0]["content"].endswith("МОЁ РЕЗЮМЕ")
    user = body["messages"][1]["content"]
    assert "Python Dev" in user and "ACME" in user and "Praha" in user
    assert user.count("x") == config.MAX_DESCRIPTION_CHARS
