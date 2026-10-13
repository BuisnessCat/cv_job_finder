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

RULES = """Ты помогаешь студенту решить, стоит ли откликаться на вакансию. Ниже его резюме.
Оцени по шкале от 1 до 10, насколько реально кандидат может пройти отбор и справиться с работой.

Как оценивать:
1. Определи суть роли: чем человек будет заниматься и 2–4 действительно обязательных требования.
   Вакансии часто перечисляют все технологии компании подряд — это пожелания, а не условия.
   Не снижай оценку за отсутствие второстепенных инструментов (JIRA, конкретная BI-система, облако,
   CI, мониторинг и т. п.) и пунктов «будет плюсом».
2. Засчитывай близкие навыки: Django или Flask вместо FastAPI, MySQL или MSSQL вместо PostgreSQL,
   любой REST/HTTP API, любой Git-хостинг.
3. На junior-позициях и стажировках многому учат на месте: если основа (язык, SQL, веб/API)
   совпадает, недостающие технологии — повод учиться, а не отказ.
4. Сильно снижай оценку только за настоящие блокеры: нужно 2+ года коммерческого опыта или уровень
   mid/senior; основной язык другой (Java, C#, PHP, C/C++ и т. п.) или совсем другая область
   (embedded, мобильная разработка, дизайн, продажи); обязателен свободный чешский или английский C1+;
   офис вне Праги без удалёнки; нужно гражданство или резидентство другой страны.
   Это НЕ проблемы: офис или гибрид в Праге, удалёнка из Чехии или ЕС, разрешение на работу в Чехии
   (кандидату оно не нужно), английский B2 (если не требуют C1 или носителя), чешский B1.

Шкала:
9–10 — junior или стажировка, основа стека совпадает, блокеров нет;
7–8 — junior или стажировка, основа совпадает, не хватает технологий, которым можно научиться;
5–6 — смежная роль или другой фреймворк, но реально попробовать;
3–4 — серьёзный пробел: уровень выше junior или основной стек заметно другой;
1–2 — не подходит: senior, другой основной язык или область, или жёсткий блокер.

Ответь JSON-объектом:
- score — оценка от 1 до 10;
- summary — 1–2 предложения: почему такая оценка;
- have — важные требования вакансии, которые у кандидата есть (с учётом близких навыков);
- missing — только существенные требования, которых нет;
- risks — только настоящие блокеры из пункта 4; пустой список, если их нет.
В каждом списке не больше 5 пунктов, каждый пункт — до 10 слов.
Все тексты пиши по-русски, обычным текстом без Markdown. Опирайся только на факты из резюме и текста вакансии.

Резюме кандидата:
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
        raise RuntimeError(f"не найден {config.LMS_EXE}")
    if not _server_up():
        _lms("server", "start", "--port", str(config.LM_PORT), timeout=60)
        deadline = time.monotonic() + 30
        while not _server_up():
            if time.monotonic() > deadline:
                raise RuntimeError("сервер не запустился за 30 с")
            time.sleep(1)
    if config.MODEL_ID not in _lms("ps", "--json").stdout:
        # --ttl: если приложение закроется посреди загрузки, LM Studio сама выгрузит модель
        result = _lms(
            "load", config.MODEL, "--identifier", config.MODEL_ID,
            "--context-length", str(config.CONTEXT_LENGTH), "--gpu", "max", "--ttl", "300", "-y",
            timeout=300,
        )
        if result.returncode != 0:
            raise RuntimeError(f"модель не загрузилась: {(result.stderr or result.stdout).strip()[-300:]}")


def evaluate(cv_text: str, job: Job) -> dict:
    """Оценить одну вакансию: score, summary, have, missing, risks."""
    vacancy = (
        f"Название: {job.title}\nКомпания: {job.company}\nГород: {job.city}\nИсточник: {job.source}\n\n"
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
        raise ModelLost(f"модель {config.MODEL_ID} выгружена (ответила {data.get('model')}), оценка остановлена")
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
