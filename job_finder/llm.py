"""Единственное место вызова модели. Чтобы перейти на Claude API, достаточно переписать
prepare / evaluate / release: prepare и release станут пустыми, evaluate будет вызывать API."""
import json
import logging
import subprocess
import time

import requests

from job_finder import config
from job_finder.sources import Job

log = logging.getLogger(__name__)

SCHEMA = {
    "type": "object",
    "properties": {
        "score": {"type": "integer", "minimum": 1, "maximum": 10},
        "summary": {"type": "string"},
        "have": {"type": "array", "items": {"type": "string"}},
        "missing": {"type": "array", "items": {"type": "string"}},
        "risks": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["score", "summary", "have", "missing", "risks"],
    "additionalProperties": False,
}

RULES = """You help a student decide whether to apply for a job. Their CV is below.
Rate from 1 to 10 how realistically the candidate can get through the hiring process and do the job.

How to rate:
1. Identify the core of the role: what the person will do and the 2–4 truly required skills.
   Job ads often list every technology the company uses — those are wishes, not requirements.
   Do not lower the score for missing secondary tools (JIRA, a specific BI system, cloud,
   CI, monitoring, etc.) or "nice to have" items.
2. Count adjacent skills: Django or Flask instead of FastAPI, MySQL or MSSQL instead of PostgreSQL,
   any REST/HTTP API, any Git hosting.
3. Junior positions and internships teach a lot on the job: if the basics (language, SQL, web/API)
   match, missing technologies are a reason to learn, not a reason to reject.
4. Lower the score sharply only for real blockers: 2+ years of commercial experience or a mid/senior
   level is required; the main language is different (Java, C#, PHP, C/C++, etc.) or the field is
   entirely different (embedded, mobile development, design, sales); fluent Czech or English C1+ is
   mandatory; an office outside Prague with no remote option; citizenship or residency of another
   country is required.
   These are NOT problems: an office or hybrid in Prague, remote work from Czechia or the EU, a work
   permit for Czechia (the candidate does not need one), English B2 (unless C1 or native is required),
   Czech B1.

Scale:
9–10 — junior or internship, the core stack matches, no blockers;
7–8 — junior or internship, the core matches, some technologies are missing but can be learned;
5–6 — adjacent role or a different framework, but worth a try;
3–4 — serious gap: above junior level or a noticeably different main stack;
1–2 — not a fit: senior, a different main language or field, or a hard blocker.

Answer with a JSON object:
- score — a score from 1 to 10;
- summary — 1–2 sentences: why this score;
- have — important job requirements the candidate meets (counting adjacent skills);
- missing — only significant requirements the candidate lacks;
- risks — only real blockers from point 4; an empty list if there are none.
Each list has at most 5 items, each item up to 10 words.
Write all texts in English, as plain text without Markdown. Rely only on facts from the CV and the job ad.

Candidate's CV:
"""


def fingerprint() -> str:
    """Что определяет оценку, кроме резюме: если это изменится, прежние оценки устарели."""
    return f"{config.MODEL}\n{RULES}"


class ModelLost(RuntimeError):
    """Ответила не наша модель: её выгрузили из LM Studio посреди оценки (например, из окна чата)."""


def _lms(*args: str, timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(config.LMS_EXE), *args], stdin=subprocess.DEVNULL, capture_output=True,
        text=True, encoding="utf-8", errors="replace", timeout=timeout,
        creationflags=subprocess.CREATE_NO_WINDOW,  # без мелькающих консолей
    )


def _server_up() -> bool:
    try:
        requests.get(f"{config.LM_URL}/models", timeout=2).raise_for_status()
        return True
    except requests.RequestException:
        return False


def prepare() -> None:
    """Поднять сервер LM Studio и загрузить модель, если она ещё не загружена."""
    if not config.LMS_EXE.exists():
        raise RuntimeError(f"not found: {config.LMS_EXE}")
    if not _server_up():
        # Вывод не перехватываем: запущенный командой сервис LM Studio унаследовал бы наши каналы,
        # и subprocess.run ждал бы их закрытия бесконечно, несмотря на timeout
        subprocess.run(
            [str(config.LMS_EXE), "server", "start", "--port", str(config.LM_PORT)],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=60, creationflags=subprocess.CREATE_NO_WINDOW,
        )
        deadline = time.monotonic() + 30
        while not _server_up():
            if time.monotonic() > deadline:
                raise RuntimeError("server did not start within 30 s")
            time.sleep(1)
    if config.MODEL_ID not in _lms("ps", "--json").stdout:
        # --ttl: если приложение закроется посреди загрузки, LM Studio сама выгрузит модель
        result = _lms(
            "load", config.MODEL, "--identifier", config.MODEL_ID,
            "--context-length", str(config.CONTEXT_LENGTH), "--gpu", "max", "--ttl", "300", "-y",
            timeout=300,
        )
        if result.returncode != 0:
            raise RuntimeError(f"model failed to load: {(result.stderr or result.stdout).strip()[-300:]}")


def evaluate(cv_text: str, job: Job) -> dict:
    """Оценить одну вакансию: score, summary, have, missing, risks."""
    vacancy = (
        f"Title: {job.title}\nCompany: {job.company}\nLocation: {job.city}\nSource: {job.source}\n\n"
        f"{job.description[:config.MAX_DESCRIPTION_CHARS]}"
    )
    response = requests.post(
        f"{config.LM_URL}/chat/completions",
        json={
            "model": config.MODEL_ID,
            "messages": [
                {"role": "system", "content": RULES + cv_text},
                {"role": "user", "content": vacancy},
            ],
            "temperature": 0,
            "max_tokens": 700,
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "evaluation", "strict": True, "schema": SCHEMA},
            },
        },
        timeout=120,
    )
    response.raise_for_status()
    data = response.json()
    # Без нашей модели LM Studio молча отвечает любой загруженной — такой ответ не годится
    if data.get("model") != config.MODEL_ID:
        raise ModelLost(f"model {config.MODEL_ID} was unloaded (got an answer from {data.get('model')}), "
                        "evaluation stopped")
    result = json.loads(data["choices"][0]["message"]["content"])
    result["score"] = int(result["score"])
    return result


def release(wait: bool = True) -> None:
    """Выгрузить модель из видеопамяти. wait=False — не ждать завершения (при закрытии окна)."""
    try:
        if wait:
            _lms("unload", config.MODEL_ID)
        else:
            subprocess.Popen(
                [str(config.LMS_EXE), "unload", config.MODEL_ID], stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
    except (OSError, subprocess.SubprocessError):
        log.exception("Не удалось выгрузить модель")
