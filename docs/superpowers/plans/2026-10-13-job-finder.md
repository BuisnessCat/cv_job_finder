# Подбор вакансий — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Десктопное окно на PySide6, которое скачивает вакансии из четырёх агрегаторов, отсеивает их по навыкам из `master_cv.md`, оценивает остальные локальной моделью в LM Studio и показывает подходящие.

**Architecture:** Пакет `job_finder/` из маленьких модулей с одной задачей каждый: `sources` (загрузка и разбор), `db` (SQLite), `skills` (отсев без ИИ), `llm` (единственное место вызова модели), `worker` (фоновое обновление), `window` (окно). Фоновый поток — daemon-`threading.Thread`, который шлёт сигналы Qt в окно. LM Studio управляется через CLI `lms`, оценка — POST к его OpenAI-совместимому API с JSON-схемой ответа.

**Tech Stack:** Python 3.11, PySide6, requests, beautifulsoup4, sqlite3, pytest; LM Studio + модель `mistralai/ministral-3-8b`.

**Spec:** `docs/superpowers/specs/2026-10-13-job-finder-design.md`

## Global Constraints

- Windows 11; Python 3.11 (`py -3.11`); окружение `.venv` в корне проекта.
- Все команды плана — в Bash (Git Bash) из корня проекта; Python — `.venv/Scripts/python`.
- Интерфейс только на русском. В окне — только обычные виджеты Qt, у всех `QLabel` `Qt.PlainText`; без браузера, веб-сервера и HTML.
- Запуск через `pythonw.exe -m job_finder`, без консоли; все вызовы `lms.exe` — с `creationflags=subprocess.CREATE_NO_WINDOW`.
- Данные — один файл `jobs.db` в корне проекта; `master_cv.md`, `*.db`, `*.log` — в `.gitignore`.
- Модель вызывается только в `job_finder/llm.py`: `mistralai/ministral-3-8b`, идентификатор `job-finder`, контекст 8192, порт 1234.
- Порог `MIN_SCORE = 5` — одна константа в `job_finder/config.py`.
- Источники — только четыре API из раздела 2 спека, с параметрами из `config.py`.
- Автотесты не ходят в сеть и не требуют LM Studio.
- Каждое сообщение коммита заканчивается строкой `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **CSV junior.guru с BOM или без кодировки в заголовке** → чешские буквы читаются правильно, первый столбец `title` находится. Тест: `test_fetch_juniorguru_decodes_utf8_with_bom` (задача 1).
2. **Пустые или отсутствующие поля в ответе источника** (нет города, `locationRestrictions` = null, `description` = null) → вакансия разбирается с пустыми значениями, источник не падает целиком. Тесты: образцы в `test_parse_juniorguru`, `test_parse_himalayas` (задача 1).
3. **Один и тот же url дважды в одной выборке** (страницы Himalayas сдвигаются, пока мы их листаем) → `save_jobs` не падает, в базе одна запись. Тест: `test_duplicate_url_in_one_batch` (задача 2).
4. **Модель вернула `score` строкой, описание вакансии огромное** → `evaluate` возвращает целый `score`, описание обрезается до 8000 символов. Тест: `test_evaluate_sends_cv_and_truncated_vacancy` (задача 4).
5. **`master_cv.md` с переводами строк CRLF и BOM или без раздела Skills** → навыки разбираются, а без раздела получается пустой список без исключений (окно пишет понятное сообщение). Тесты: `test_load_skills_crlf_and_bom`, `test_load_skills_without_section` (задача 3).

---

### Task 1: Каркас и источники вакансий

**Files:**
- Create: `requirements.txt`, `job_finder/__init__.py`, `job_finder/config.py`, `job_finder/sources.py`
- Modify: `.gitignore` (заменить целиком)
- Test: `tests/test_sources.py`

**Interfaces:**
- Consumes: —
- Produces:
  - `job_finder.config`: `ROOT`, `CV_PATH`, `DB_PATH`, `LOG_PATH`, `MIN_SCORE`, `LMS_EXE`, `LM_PORT`, `LM_URL`, `MODEL`, `MODEL_ID`, `CONTEXT_LENGTH`, `MAX_DESCRIPTION_CHARS`, `HTTP_TIMEOUT`, параметры источников.
  - `job_finder.sources.Job` — dataclass `(url, source, title, company, city, published, description)`, все поля `str`, именно в этом порядке.
  - `sources.fetch_all() -> tuple[dict[str, list[Job]], dict[str, str]]` — вакансии по источникам без дублей и тексты ошибок по источникам.
  - `sources.parse_juniorguru(text: str)`, `parse_himalayas(data: dict)`, `parse_jobicy(data: dict)`, `parse_workingnomads(data: list)` → `list[Job]`; `sources.dedupe(fetched: dict[str, list[Job]]) -> dict[str, list[Job]]`; `sources.SOURCES` — список пар `(имя, функция загрузки)`.

- [ ] **Step 1: Создать `requirements.txt`**

```text
PySide6>=6.7
requests>=2.31
beautifulsoup4>=4.12
pytest>=8
```

- [ ] **Step 2: Заменить `.gitignore` целиком**

```gitignore
# Личные данные и данные приложения — никогда не коммитить
master_cv.md
*.db
*.db-*
*.log

# Python
.venv/
__pycache__/
*.pyc
.pytest_cache/
```

- [ ] **Step 3: Создать окружение и поставить зависимости**

Run: `py -3.11 -m venv .venv && .venv/Scripts/python -m pip install -r requirements.txt`
Expected: в конце `Successfully installed ... PySide6-... requests-... beautifulsoup4-... pytest-...`

- [ ] **Step 4: Создать `job_finder/__init__.py` (пустой файл) и `job_finder/config.py`**

```python
"""Настройки приложения."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CV_PATH = ROOT / "master_cv.md"
DB_PATH = ROOT / "jobs.db"
LOG_PATH = ROOT / "job_finder.log"

# Показываем вакансии с оценкой не ниже порога
MIN_SCORE = 5

# LM Studio
LMS_EXE = Path.home() / ".lmstudio" / "bin" / "lms.exe"
LM_PORT = 1234
LM_URL = f"http://localhost:{LM_PORT}/v1"
MODEL = "mistralai/ministral-3-8b"
MODEL_ID = "job-finder"  # идентификатор загруженной модели в LM Studio и в API
CONTEXT_LENGTH = 8192
MAX_DESCRIPTION_CHARS = 8000

# Источники
HTTP_TIMEOUT = 30
JUNIORGURU_URL = "https://junior.guru/api/jobs.csv"
HIMALAYAS_URL = "https://himalayas.app/jobs/api/search"
# Чтобы сократить первую оценку, можно оставить только "Entry-level"
HIMALAYAS_PARAMS = {"q": "python", "country": "CZ", "seniority": "Entry-level,Mid-level", "sort": "recent"}
HIMALAYAS_MAX_PAGES = 10  # по 20 вакансий на страницу
JOBICY_URL = "https://jobicy.com/api/v2/remote-jobs"
JOBICY_PARAMS = {"count": 50, "geo": "czechia", "industry": "dev"}
WORKINGNOMADS_URL = "https://www.workingnomads.com/api/exposed_jobs/"
```

- [ ] **Step 5: Написать падающие тесты `tests/test_sources.py`**

```python
from job_finder import config, sources
from job_finder.sources import Job

JG_CSV = (
    "title,company_name,url,remote,first_seen_at,locations_0_name,description_html\n"
    'Junior Python vývojář,Firma s.r.o.,https://www.jobs.cz/rpd/1/?utm_source=juniorguru,False,'
    '2026-10-12 00:00:00,Praha,"<p>Hledáme <b>Python</b> vývojáře</p>"\n'
    "Remote tester,Remote a.s.,https://example.com/2,True,2026-10-10 00:00:00,,<p>Testování</p>\n"
    "Office job,Office s.r.o.,https://example.com/3,False,2026-10-09 00:00:00,,\n"
)

HIMALAYAS = {"jobs": [
    {"title": "Junior Backend Developer", "companyName": "Acme",
     "guid": "https://himalayas.app/companies/acme/jobs/junior-backend", "pubDate": 1791876793,
     "locationRestrictions": [], "description": "<p>Python &amp; SQL</p>"},
    {"title": "Python Engineer", "companyName": "Beta",
     "guid": "https://himalayas.app/companies/beta/jobs/python", "pubDate": "1791876793",
     "locationRestrictions": ["Czechia", "Slovakia", "Poland", "Hungary"], "description": None},
]}

JOBICY = {"jobs": [
    {"url": "https://jobicy.com/jobs/1-python-dev", "jobTitle": "Python Developer", "companyName": "Gamma",
     "jobGeo": "Europe", "pubDate": "2026-10-13T02:48:27+00:00", "jobDescription": "<div><p>Django</p></div>"},
]}

WORKINGNOMADS = [
    {"url": "https://www.workingnomads.com/job/go/1/", "title": "Backend Developer", "company_name": "Delta",
     "category_name": "Development", "location": "Time zone: CET (+/- 3 hours)",
     "pub_date": "2026-10-08T12:54:14-04:00", "description": "<p>Python</p>"},
    {"url": "https://www.workingnomads.com/job/go/2/", "title": "Support Agent", "company_name": "Delta",
     "category_name": "Customer Success", "location": "", "pub_date": "2026-10-08T12:54:14-04:00",
     "description": "<p>Help</p>"},
]


class FakeResponse:
    def __init__(self, content=b"", data=None):
        self.content = content
        self._data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self._data


def make(url, source, company="ACME", title="Python Dev"):
    return Job(url=url, source=source, title=title, company=company, city="", published="2026-10-01",
               description="")


def test_parse_juniorguru():
    jobs = sources.parse_juniorguru(JG_CSV)
    assert jobs[0] == Job(
        url="https://www.jobs.cz/rpd/1/?utm_source=juniorguru", source="junior.guru",
        title="Junior Python vývojář", company="Firma s.r.o.", city="Praha", published="2026-10-12",
        description="Hledáme\nPython\nvývojáře",
    )
    assert (jobs[1].city, jobs[1].published, jobs[1].description) == ("Удалённо", "2026-10-10", "Testování")
    assert (jobs[2].city, jobs[2].description) == ("", "")


def test_parse_himalayas():
    jobs = sources.parse_himalayas(HIMALAYAS)
    assert jobs[0] == Job(
        url="https://himalayas.app/companies/acme/jobs/junior-backend", source="Himalayas",
        title="Junior Backend Developer", company="Acme", city="Удалённо", published="2026-10-13",
        description="Python & SQL",
    )
    assert jobs[1].city == "Удалённо (Czechia, Slovakia, Poland …)"
    assert jobs[1].published == "2026-10-13"
    assert jobs[1].description == ""


def test_parse_jobicy():
    assert sources.parse_jobicy(JOBICY) == [Job(
        url="https://jobicy.com/jobs/1-python-dev", source="Jobicy", title="Python Developer", company="Gamma",
        city="Удалённо: Europe", published="2026-10-13", description="Django",
    )]


def test_parse_workingnomads_keeps_only_development():
    assert sources.parse_workingnomads(WORKINGNOMADS) == [Job(
        url="https://www.workingnomads.com/job/go/1/", source="Working Nomads", title="Backend Developer",
        company="Delta", city="Удалённо: Time zone: CET (+/- 3 hours)", published="2026-10-08",
        description="Python",
    )]


def test_dedupe_keeps_higher_priority_source():
    fetched = {
        "junior.guru": [make("u1", "junior.guru")],
        "Himalayas": [make("u2", "Himalayas", company=" acme ", title="python  dev"),
                      make("u3", "Himalayas", title="Other")],
    }
    result = sources.dedupe(fetched)
    assert [job.url for job in result["junior.guru"]] == ["u1"]
    assert [job.url for job in result["Himalayas"]] == ["u3"]


def test_fetch_all_isolates_source_errors(monkeypatch):
    def broken():
        raise RuntimeError("timeout")

    monkeypatch.setattr(sources, "SOURCES", [
        ("junior.guru", lambda: [make("u1", "junior.guru")]),
        ("Jobicy", broken),
    ])
    fetched, errors = sources.fetch_all()
    assert list(fetched) == ["junior.guru"]
    assert "timeout" in errors["Jobicy"]


def test_fetch_juniorguru_decodes_utf8_with_bom(monkeypatch):
    content = ("﻿" + JG_CSV).encode("utf-8")
    monkeypatch.setattr(sources.requests, "get", lambda *args, **kwargs: FakeResponse(content=content))
    assert sources.fetch_juniorguru()[0].title == "Junior Python vývojář"


def test_fetch_himalayas_pages_until_empty(monkeypatch):
    pages = {
        1: HIMALAYAS,
        2: {"jobs": [HIMALAYAS["jobs"][0] | {"guid": "https://himalayas.app/x"}]},
        3: {"jobs": []},
    }
    calls = []

    def fake_get(url, params=None, **kwargs):
        calls.append(params["page"])
        return FakeResponse(data=pages[params["page"]])

    monkeypatch.setattr(sources.requests, "get", fake_get)
    monkeypatch.setattr(sources.time, "sleep", lambda seconds: None)
    assert len(sources.fetch_himalayas()) == 3
    assert calls == [1, 2, 3]


def test_fetch_himalayas_respects_max_pages(monkeypatch):
    calls = []

    def fake_get(url, params=None, **kwargs):
        calls.append(params["page"])
        return FakeResponse(data=HIMALAYAS)

    monkeypatch.setattr(sources.requests, "get", fake_get)
    monkeypatch.setattr(sources.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(config, "HIMALAYAS_MAX_PAGES", 2)
    sources.fetch_himalayas()
    assert calls == [1, 2]
```

- [ ] **Step 6: Убедиться, что тесты падают**

Run: `.venv/Scripts/python -m pytest tests/test_sources.py -v`
Expected: ошибка сбора `ModuleNotFoundError: No module named 'job_finder.sources'`

- [ ] **Step 7: Написать `job_finder/sources.py`**

```python
"""Источники вакансий: четыре агрегатора с открытым API."""
import csv
import io
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

from job_finder import config

log = logging.getLogger(__name__)
csv.field_size_limit(10_000_000)  # на случай очень длинных описаний в CSV junior.guru
HEADERS = {"User-Agent": "job-finder/1.0 (personal desktop app)"}


@dataclass
class Job:
    url: str
    source: str
    title: str
    company: str
    city: str
    published: str  # YYYY-MM-DD
    description: str  # обычный текст


def html_to_text(html: str | None) -> str:
    return BeautifulSoup(html or "", "html.parser").get_text("\n", strip=True)


def parse_juniorguru(text: str) -> list[Job]:
    jobs = []
    for row in csv.DictReader(io.StringIO(text)):
        city = row.get("locations_0_name") or ("Удалённо" if row.get("remote") == "True" else "")
        jobs.append(Job(
            url=row["url"], source="junior.guru", title=row["title"], company=row["company_name"],
            city=city, published=row["first_seen_at"][:10],
            description=html_to_text(row.get("description_html")),
        ))
    return jobs


def parse_himalayas(data: dict) -> list[Job]:
    jobs = []
    for item in data.get("jobs") or []:
        countries = item.get("locationRestrictions") or []
        city = "Удалённо"
        if countries:
            city += f" ({', '.join(countries[:3])}{' …' if len(countries) > 3 else ''})"
        published = datetime.fromtimestamp(int(item["pubDate"]), timezone.utc).strftime("%Y-%m-%d")
        jobs.append(Job(
            url=item["guid"], source="Himalayas", title=item["title"], company=item["companyName"],
            city=city, published=published, description=html_to_text(item.get("description")),
        ))
    return jobs


def parse_jobicy(data: dict) -> list[Job]:
    return [
        Job(
            url=item["url"], source="Jobicy", title=item["jobTitle"], company=item["companyName"],
            city=f"Удалённо: {item['jobGeo']}" if item.get("jobGeo") else "Удалённо",
            published=item["pubDate"][:10], description=html_to_text(item.get("jobDescription")),
        )
        for item in data.get("jobs") or []
    ]


def parse_workingnomads(data: list) -> list[Job]:
    return [
        Job(
            url=item["url"], source="Working Nomads", title=item["title"], company=item["company_name"],
            city=f"Удалённо: {item['location']}" if item.get("location") else "Удалённо",
            published=item["pub_date"][:10], description=html_to_text(item.get("description")),
        )
        for item in data
        if item.get("category_name") == "Development"
    ]


def _get(url: str, params: dict | None = None) -> requests.Response:
    response = requests.get(url, params=params, headers=HEADERS, timeout=config.HTTP_TIMEOUT)
    response.raise_for_status()
    return response


def fetch_juniorguru() -> list[Job]:
    # Декодируем сами: так не зависим от заголовка ответа и убираем BOM
    return parse_juniorguru(_get(config.JUNIORGURU_URL).content.decode("utf-8-sig"))


def fetch_himalayas() -> list[Job]:
    jobs = []
    for page in range(1, config.HIMALAYAS_MAX_PAGES + 1):
        if page > 1:
            time.sleep(1)  # Himalayas ограничивает частоту запросов
        batch = parse_himalayas(_get(config.HIMALAYAS_URL, {**config.HIMALAYAS_PARAMS, "page": page}).json())
        if not batch:
            break
        jobs += batch
    return jobs


def fetch_jobicy() -> list[Job]:
    return parse_jobicy(_get(config.JOBICY_URL, config.JOBICY_PARAMS).json())


def fetch_workingnomads() -> list[Job]:
    return parse_workingnomads(_get(config.WORKINGNOMADS_URL).json())


# Порядок — приоритет при удалении дублей
SOURCES = [
    ("junior.guru", fetch_juniorguru),
    ("Himalayas", fetch_himalayas),
    ("Jobicy", fetch_jobicy),
    ("Working Nomads", fetch_workingnomads),
]


def _norm(text: str) -> str:
    return " ".join(text.lower().split())


def dedupe(fetched: dict[str, list[Job]]) -> dict[str, list[Job]]:
    """Убрать повторы по «компания + название»; остаётся запись источника, который раньше в словаре."""
    seen = set()
    result = {}
    for name, jobs in fetched.items():
        result[name] = []
        for job in jobs:
            key = (_norm(job.company), _norm(job.title))
            if key not in seen:
                seen.add(key)
                result[name].append(job)
    return result


def fetch_all() -> tuple[dict[str, list[Job]], dict[str, str]]:
    """Загрузить все источники: (вакансии по источникам без дублей, ошибки по источникам)."""
    fetched, errors = {}, {}
    for name, fetch in SOURCES:
        try:
            fetched[name] = fetch()
        except Exception as error:
            log.exception("Источник %s не загрузился", name)
            errors[name] = str(error)[:150]
    return dedupe(fetched), errors
```

- [ ] **Step 8: Убедиться, что тесты проходят**

Run: `.venv/Scripts/python -m pytest tests/test_sources.py -v`
Expected: `9 passed`

- [ ] **Step 9: Проверить на живых источниках**

Run: `PYTHONUTF8=1 .venv/Scripts/python -X utf8 -c "from job_finder import sources; f, e = sources.fetch_all(); print({k: len(v) for k, v in f.items()}, e)"`
Expected: примерно `{'junior.guru': 50, 'Himalayas': 200, 'Jobicy': 16, 'Working Nomads': 20} {}` (числа могут отличаться, ошибок нет). Если какой-то источник отвечает 403, заменить `HEADERS` на обычный браузерный User-Agent и повторить.

- [ ] **Step 10: Commit**

```bash
git add requirements.txt .gitignore job_finder/__init__.py job_finder/config.py job_finder/sources.py tests/test_sources.py
git commit -m "Add project skeleton and job sources" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: База SQLite

**Files:**
- Create: `job_finder/db.py`
- Test: `tests/test_db.py`

**Interfaces:**
- Consumes: `config.DB_PATH`; `sources.Job`.
- Produces:
  - `db.init() -> None` — создать таблицу.
  - `db.save_jobs(source: str, jobs: list[Job]) -> None` — записать свежую выборку источника, его пропавшие вакансии сделать неактивными.
  - `db.pending_jobs(cv_hash: str) -> list[Job]` — очередь на оценку, сначала новые.
  - `db.save_evaluation(url: str, evaluation: dict, cv_hash: str) -> None`.
  - `db.hide(url: str) -> None`.
  - `db.make_row(job: Job, evaluation: dict) -> dict` — строка для окна: ключи `url, source, title, company, city, published, score, evaluation`.
  - `db.list_jobs(cv_hash: str, min_score: int) -> list[dict]` — строки того же вида, лучшие сверху.

- [ ] **Step 1: Написать падающие тесты `tests/test_db.py`**

```python
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
    assert rows[0] == db.make_row(job("c"), evaluation(9))


def test_duplicate_url_in_one_batch():
    db.save_jobs("Himalayas", [job("a", source="Himalayas"), job("a", source="Himalayas")])
    assert urls(db.pending_jobs("h1")) == ["a"]
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `.venv/Scripts/python -m pytest tests/test_db.py -v`
Expected: ошибка сбора `ImportError: cannot import name 'db' from 'job_finder'`

- [ ] **Step 3: Написать `job_finder/db.py`**

```python
"""Хранение вакансий и оценок в одном файле SQLite."""
import json
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict

from job_finder import config
from job_finder.sources import Job

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    url         TEXT PRIMARY KEY,
    source      TEXT NOT NULL,
    title       TEXT NOT NULL,
    company     TEXT NOT NULL,
    city        TEXT NOT NULL,
    published   TEXT NOT NULL,      -- YYYY-MM-DD
    description TEXT NOT NULL,
    active      INTEGER NOT NULL DEFAULT 1,
    hidden      INTEGER NOT NULL DEFAULT 0,
    score       INTEGER,            -- NULL, пока не оценена
    evaluation  TEXT,               -- JSON-ответ модели
    cv_hash     TEXT                -- SHA-256 master_cv.md на момент оценки
)
"""

# Порядок совпадает с полями Job
JOB_FIELDS = "url, source, title, company, city, published, description"


@contextmanager
def _connect():
    # Своё короткое соединение на каждый вызов: базой пользуются и окно, и фоновый поток
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        with conn:  # коммит или откат транзакции
            yield conn
    finally:
        conn.close()


def init() -> None:
    with _connect() as conn:
        conn.execute(SCHEMA)


def save_jobs(source: str, jobs: list[Job]) -> None:
    """Записать свежую выборку источника; его вакансии, которых в ней нет, становятся неактивными."""
    with _connect() as conn:
        conn.execute("UPDATE jobs SET active = 0 WHERE source = ?", (source,))
        conn.executemany(
            f"""INSERT INTO jobs ({JOB_FIELDS})
                VALUES (:url, :source, :title, :company, :city, :published, :description)
                ON CONFLICT(url) DO UPDATE SET
                    source = excluded.source, title = excluded.title, company = excluded.company,
                    city = excluded.city, published = excluded.published,
                    description = excluded.description, active = 1""",
            [asdict(job) for job in jobs],
        )


def pending_jobs(cv_hash: str) -> list[Job]:
    """Активные нескрытые вакансии без оценки по текущему резюме, сначала самые новые."""
    with _connect() as conn:
        rows = conn.execute(
            f"""SELECT {JOB_FIELDS} FROM jobs
                WHERE active = 1 AND hidden = 0 AND (cv_hash IS NULL OR cv_hash != ?)
                ORDER BY published DESC""",
            (cv_hash,),
        ).fetchall()
    return [Job(**dict(row)) for row in rows]


def save_evaluation(url: str, evaluation: dict, cv_hash: str) -> None:
    with _connect() as conn:
        conn.execute(
            "UPDATE jobs SET score = ?, evaluation = ?, cv_hash = ? WHERE url = ?",
            (evaluation["score"], json.dumps(evaluation, ensure_ascii=False), cv_hash, url),
        )


def hide(url: str) -> None:
    with _connect() as conn:
        conn.execute("UPDATE jobs SET hidden = 1 WHERE url = ?", (url,))


def make_row(job: Job, evaluation: dict) -> dict:
    """Строка для окна: поля вакансии без описания, оценка и разбор модели."""
    row = asdict(job)
    del row["description"]
    return {**row, "score": evaluation["score"], "evaluation": evaluation}


def list_jobs(cv_hash: str, min_score: int) -> list[dict]:
    """Вакансии для окна: оценка по текущему резюме не ниже порога, лучшие сверху."""
    with _connect() as conn:
        rows = conn.execute(
            f"""SELECT {JOB_FIELDS}, evaluation FROM jobs
                WHERE active = 1 AND hidden = 0 AND cv_hash = ? AND score >= ?
                ORDER BY score DESC, published DESC""",
            (cv_hash, min_score),
        ).fetchall()
    return [make_row(Job(*tuple(row)[:7]), json.loads(row["evaluation"])) for row in rows]
```

- [ ] **Step 4: Убедиться, что тесты проходят**

Run: `.venv/Scripts/python -m pytest tests -v`
Expected: `16 passed`

- [ ] **Step 5: Commit**

```bash
git add job_finder/db.py tests/test_db.py
git commit -m "Add SQLite storage for jobs and evaluations" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Отсев по навыкам

**Files:**
- Create: `job_finder/skills.py`
- Test: `tests/test_skills.py`

**Interfaces:**
- Consumes: `sources.Job` (поля `title`, `description`).
- Produces: `skills.load_skills(cv_text: str) -> list[str]`; `skills.matches(job: Job, skills: list[str]) -> bool`.

- [ ] **Step 1: Написать падающие тесты `tests/test_skills.py`**

```python
from job_finder import skills
from job_finder.sources import Job

CV = """# Master CV

## Target
- Roles: Python backend intern

## Skills — level and evidence
- Python — main language
- SQL — JOINs
- SQLAlchemy 2.0 ORM — models
- Git, GitHub — version control
- requests, BeautifulSoup — web scraping
- Concepts — OOP, REST API design
- In progress, NOT to be presented as done: pytest, Docker Compose

## Projects
- Django — not a skill section
"""

EXPECTED = ["Python", "SQL", "SQLAlchemy", "Git", "GitHub", "requests", "BeautifulSoup"]


def job(title, description=""):
    return Job(url="u", source="s", title=title, company="c", city="", published="2026-10-01",
               description=description)


def test_load_skills():
    assert skills.load_skills(CV) == EXPECTED


def test_load_skills_crlf_and_bom():
    assert skills.load_skills("﻿" + CV.replace("\n", "\r\n")) == EXPECTED


def test_load_skills_without_section():
    assert skills.load_skills("# CV\n\n## Projects\n- Python — x\n") == []


def test_matches_whole_words_case_insensitive():
    skill_list = ["Git", "SQL", "Python"]
    assert skills.matches(job("Junior PYTHON developer"), skill_list)
    assert skills.matches(job("Analyst", "Znalost T-SQL"), skill_list)
    assert not skills.matches(job("DevOps", "GitLab CI, MySQL"), skill_list)


def test_matches_nothing_without_skills():
    assert not skills.matches(job("Python developer"), [])
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `.venv/Scripts/python -m pytest tests/test_skills.py -v`
Expected: ошибка сбора `ImportError: cannot import name 'skills' from 'job_finder'`

- [ ] **Step 3: Написать `job_finder/skills.py`**

```python
"""Отсев вакансий без ИИ: есть ли в вакансии хоть один навык из master_cv.md."""
import re

from job_finder.sources import Job


def load_skills(cv_text: str) -> list[str]:
    """Навыки из раздела «## Skills»: часть строки до « — », через запятую, первое слово элемента."""
    skills = []
    in_skills = False
    for line in cv_text.splitlines():
        if line.startswith("## "):
            in_skills = line.startswith("## Skills")
            continue
        if not in_skills or not line.startswith("- "):
            continue
        item = line[2:]
        if item.startswith(("Concepts", "In progress")):
            continue
        for part in item.split(" — ")[0].split(","):
            words = part.split()
            if words:
                skills.append(words[0])
    return skills


def matches(job: Job, skills: list[str]) -> bool:
    """Есть ли хоть один навык в названии или описании — целым словом, без учёта регистра."""
    text = f"{job.title}\n{job.description}"
    return any(re.search(rf"(?<!\w){re.escape(skill)}(?!\w)", text, re.IGNORECASE) for skill in skills)
```

- [ ] **Step 4: Убедиться, что тесты проходят**

Run: `.venv/Scripts/python -m pytest tests -v`
Expected: `21 passed`

- [ ] **Step 5: Проверить на настоящем резюме**

Run: `PYTHONUTF8=1 .venv/Scripts/python -X utf8 -c "from job_finder import config, skills; print(skills.load_skills(config.CV_PATH.read_text(encoding='utf-8')))"`
Expected: `['Python', 'SQL', 'FastAPI', 'Pydantic', 'SQLAlchemy', 'Alembic', 'PostgreSQL', 'Docker', 'Git', 'GitHub', 'requests', 'BeautifulSoup']`

- [ ] **Step 6: Commit**

```bash
git add job_finder/skills.py tests/test_skills.py
git commit -m "Add skills prefilter from master_cv.md" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Модель в LM Studio

**Files:**
- Create: `job_finder/llm.py`
- Test: `tests/test_llm.py`

**Interfaces:**
- Consumes: `config.LMS_EXE`, `LM_PORT`, `LM_URL`, `MODEL`, `MODEL_ID`, `CONTEXT_LENGTH`, `MAX_DESCRIPTION_CHARS`; `sources.Job`.
- Produces:
  - `llm.prepare() -> None` — поднять сервер и загрузить модель; при неудаче `RuntimeError` с понятным текстом.
  - `llm.evaluate(cv_text: str, job: Job) -> dict` — ключи `score` (int), `summary` (str), `have`, `missing`, `risks` (list[str]).
  - `llm.release(wait: bool = True) -> None` — выгрузить модель; не бросает исключений.

- [ ] **Step 1: Скачать модель (пользователь согласился на это скачивание, ~6,5 ГБ)**

Run (в фоне, загрузка может занять больше 10 минут): `"$USERPROFILE/.lmstudio/bin/lms.exe" get mistralai/ministral-3-8b -y`
Затем: `"$USERPROFILE/.lmstudio/bin/lms.exe" ls`
Expected: в списке LLM есть `mistralai/ministral-3-8b`. Если ключ модели в списке отличается, записать его в `MODEL` в `job_finder/config.py`.

- [ ] **Step 2: Написать падающий тест `tests/test_llm.py`**

```python
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
```

- [ ] **Step 3: Убедиться, что тест падает**

Run: `.venv/Scripts/python -m pytest tests/test_llm.py -v`
Expected: ошибка сбора `ImportError: cannot import name 'llm' from 'job_finder'`

- [ ] **Step 4: Написать `job_finder/llm.py`**

```python
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

RULES = """Ты помогаешь кандидату решить, стоит ли откликаться на вакансию. Ниже его резюме.
Оцени по шкале от 1 до 10, насколько кандидат подходит под вакансию.

Учитывай:
- уровень: кандидат ищет стажировку или junior-позицию, коммерческого опыта разработки у него нет;
- совпадение стека с навыками из резюме; навыки из пункта «In progress» он только изучает;
- языки: английский B2, чешский B1, русский родной;
- место: Прага (офис или гибрид) либо удалённо в Чехии или ЕС;
- разрешение на работу в Чехии кандидату не требуется.

Шкала:
9–10 — стажировка или junior, стек почти полностью совпадает, условия подходят;
7–8 — подходит с небольшими пробелами;
5–6 — стоит попробовать;
3–4 — заметное несоответствие по уровню или стеку;
1–2 — не подходит.

Ответь JSON-объектом:
- score — оценка от 1 до 10;
- summary — 1–2 предложения: почему такая оценка;
- have — требования вакансии, которые у кандидата есть;
- missing — требования вакансии, которых у кандидата нет;
- risks — что может отсечь кандидата: свободный чешский, много лет опыта, нужно гражданство или
  резидентство ЕС либо другой страны, офис вне Праги и т. п.; пустой список, если такого нет.
Все тексты пиши по-русски. Опирайся только на факты из резюме и текста вакансии.

Резюме кандидата:
"""


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
    result = json.loads(response.json()["choices"][0]["message"]["content"])
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
```

- [ ] **Step 5: Убедиться, что тесты проходят**

Run: `.venv/Scripts/python -m pytest tests -v`
Expected: `22 passed`

- [ ] **Step 6: Проверить модель на 5 реальных вакансиях**

Run:

```bash
PYTHONUTF8=1 .venv/Scripts/python -X utf8 - <<'EOF'
import subprocess
import time

from job_finder import config, llm, skills, sources

cv_text = config.CV_PATH.read_text(encoding="utf-8")
skill_list = skills.load_skills(cv_text)
jobs = [j for j in sources.fetch_juniorguru() + sources.fetch_jobicy() if skills.matches(j, skill_list)]
llm.prepare()
try:
    print(llm._lms("ps").stdout)
    print(subprocess.run(["nvidia-smi", "--query-gpu=memory.used,memory.total", "--format=csv"],
                         capture_output=True, text=True).stdout)
    for job in jobs[:3] + jobs[-2:]:
        start = time.monotonic()
        result = llm.evaluate(cv_text, job)
        print(f"{time.monotonic() - start:.1f} с | {job.source} | {job.title}\n{result}\n")
finally:
    llm.release()
EOF
"$USERPROFILE/.lmstudio/bin/lms.exe" ps
```

Expected:
- `lms ps` после `prepare` показывает `job-finder`; занятая видеопамять меньше 12 ГБ (модель целиком в GPU).
- Каждая оценка — в среднем не больше ~15 с (первая может быть дольше), без «размышлений»; все поля на русском; junior-вакансии с Python получают заметно больше баллов, чем senior.
- Последний `lms ps` после `release` пишет, что загруженных моделей нет.

Если `lms server start` зависает дольше 60 с или оценка занимает минуты, остановиться и сообщить пользователю, не меняя модель самостоятельно.

- [ ] **Step 7: Commit**

```bash
git add job_finder/llm.py tests/test_llm.py job_finder/config.py
git commit -m "Add LM Studio model calls" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Фоновое обновление и окно

**Files:**
- Create: `job_finder/worker.py`, `job_finder/window.py`, `job_finder/__main__.py`
- Test: `tests/test_window.py`

**Interfaces:**
- Consumes: `sources.fetch_all`, `db.init / save_jobs / pending_jobs / save_evaluation / hide / make_row / list_jobs`, `skills.load_skills / matches`, `llm.prepare / evaluate / release`, `config.CV_PATH / MIN_SCORE / LOG_PATH`.
- Produces:
  - `worker.read_cv() -> tuple[str, str] | None` — текст `master_cv.md` и его SHA-256 или `None`, если файла нет.
  - `worker.Worker(QObject)`: сигналы `status(str)`, `progress(int, int)`, `evaluated(object)` (строка вида `db.make_row`), `finished()`; метод `start()`; атрибут `model_loaded: bool`.
  - `window.MainWindow(QMainWindow)`: атрибуты `table`, `rows`, `current`; методы `on_evaluated(row)`, `hide_job()`, `open_job()`, `refresh()`.

- [ ] **Step 1: Написать `job_finder/worker.py`**

```python
"""Фоновое обновление: загрузка → отсев по навыкам → оценка моделью (раздел 3 спека)."""
import hashlib
import logging
import threading

from PySide6.QtCore import QObject, Signal

from job_finder import config, db, llm, skills, sources

log = logging.getLogger(__name__)


def read_cv() -> tuple[str, str] | None:
    """Текст master_cv.md и его SHA-256 или None, если файла нет."""
    if not config.CV_PATH.exists():
        return None
    text = config.CV_PATH.read_text(encoding="utf-8")
    return text, hashlib.sha256(text.encode("utf-8")).hexdigest()


def _join(summary: str, notes: list[str]) -> str:
    return "; ".join([summary, *notes])


class Worker(QObject):
    status = Signal(str)
    progress = Signal(int, int)  # оценено, всего
    evaluated = Signal(object)   # строка вида db.make_row
    finished = Signal()

    def __init__(self):
        super().__init__()
        self.model_loaded = False

    def start(self) -> None:
        # daemon: окно закрывается сразу, не дожидаясь текущего запроса к модели
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self) -> None:
        try:
            message = self._refresh()
            log.info(message)
            self.status.emit(message)
        except Exception:
            log.exception("Обновление упало")
            self.status.emit("Ошибка обновления, подробности в job_finder.log")
        finally:
            self.finished.emit()

    def _refresh(self) -> str:
        """Одно обновление. Возвращает итоговую строку состояния."""
        self.status.emit("Загружаю вакансии…")
        fetched, errors = sources.fetch_all()
        for name, jobs in fetched.items():
            db.save_jobs(name, jobs)
        log.info("Загружено: %s", {name: len(jobs) for name, jobs in fetched.items()})
        notes = [f"{name}: ошибка ({error})" for name, error in errors.items()]

        cv = read_cv()
        if cv is None:
            return _join("Нет файла master_cv.md, оценка не запущена", notes)
        cv_text, cv_hash = cv
        skill_list = skills.load_skills(cv_text)
        if not skill_list:
            return _join("В master_cv.md не найден раздел Skills, оценка не запущена", notes)
        todo = [job for job in db.pending_jobs(cv_hash) if skills.matches(job, skill_list)]
        log.info("К оценке: %d", len(todo))

        if todo:
            self.status.emit("Запускаю LM Studio…")
            self.model_loaded = True
            try:
                llm.prepare()
                failed = self._evaluate(todo, cv_text, cv_hash)
                if failed:
                    notes.append(f"не удалось оценить: {failed}")
            except Exception as error:
                log.exception("LM Studio недоступна")
                notes.append(f"LM Studio: {error}")
            finally:
                llm.release()
                self.model_loaded = False

        suitable = len(db.list_jobs(cv_hash, config.MIN_SCORE))
        return _join(f"Готово: {suitable} подходящих", notes)

    def _evaluate(self, todo: list[sources.Job], cv_text: str, cv_hash: str) -> int:
        """Оценить вакансии по одной; возвращает число неудачных оценок."""
        failed = 0
        self.progress.emit(0, len(todo))
        for done, job in enumerate(todo, 1):
            try:
                evaluation = llm.evaluate(cv_text, job)
            except Exception:
                log.exception("Не удалось оценить %s", job.url)
                failed += 1
            else:
                db.save_evaluation(job.url, evaluation, cv_hash)
                self.evaluated.emit(db.make_row(job, evaluation))
            self.progress.emit(done, len(todo))
        return failed
```

- [ ] **Step 2: Написать падающие тесты `tests/test_window.py`**

```python
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from job_finder import config, db, worker
from job_finder.window import MainWindow


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(app, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "jobs.db")
    monkeypatch.setattr(config, "CV_PATH", tmp_path / "master_cv.md")  # резюме нет → список пуст
    monkeypatch.setattr(worker.Worker, "start", lambda self: None)
    db.init()
    w = MainWindow()
    yield w
    w.deleteLater()


def row(url, score, published="2026-10-01"):
    return {"url": url, "source": "Jobicy", "title": f"Job {url}", "company": "ACME", "city": "Praha",
            "published": published, "score": score,
            "evaluation": {"score": score, "summary": "ok", "have": ["Python"], "missing": [], "risks": []}}


def titles(w):
    return [w.table.item(i, 1).text() for i in range(w.table.rowCount())]


def test_evaluated_rows_sorted_and_filtered(window):
    for r in [row("a", 6), row("b", 4), row("c", 9), row("d", 6, "2026-10-05")]:
        window.on_evaluated(r)
    assert titles(window) == ["Job c", "Job d", "Job a"]


def test_selection_kept_when_new_row_arrives(window):
    window.on_evaluated(row("a", 6))
    window.table.selectRow(0)
    window.on_evaluated(row("c", 9))
    assert window.current["url"] == "a"
    assert window.table.selectionModel().selectedRows()[0].row() == 1


def test_hide_removes_row(window, monkeypatch):
    hidden = []
    monkeypatch.setattr(db, "hide", hidden.append)
    window.on_evaluated(row("a", 6))
    window.on_evaluated(row("c", 9))
    window.table.selectRow(0)
    window.hide_job()
    assert hidden == ["c"]
    assert titles(window) == ["Job a"]
    assert window.current is None
```

- [ ] **Step 3: Убедиться, что тесты падают**

Run: `.venv/Scripts/python -m pytest tests/test_window.py -v`
Expected: ошибка сбора `ModuleNotFoundError: No module named 'job_finder.window'`

- [ ] **Step 4: Написать `job_finder/window.py`**

```python
"""Главное окно: таблица подходящих вакансий и детали оценки."""
from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView, QHBoxLayout, QHeaderView, QLabel, QMainWindow, QProgressBar,
    QPushButton, QScrollArea, QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from job_finder import config, db, llm
from job_finder.worker import Worker, read_cv

COLUMNS = ["Оценка", "Вакансия", "Компания", "Город", "Дата"]
SECTIONS = [("summary", "Почему"), ("have", "Есть"), ("missing", "Не хватает"), ("risks", "Может отсечь")]


def _label(bold: bool = False, point_size: int | None = None) -> QLabel:
    label = QLabel()
    label.setTextFormat(Qt.PlainText)  # только обычный текст, без HTML
    label.setWordWrap(True)
    label.setTextInteractionFlags(Qt.TextSelectableByMouse)
    font = label.font()
    font.setBold(bold)
    if point_size:
        font.setPointSize(point_size)
    label.setFont(font)
    return label


def _bullets(items: list[str]) -> str:
    return "\n".join(f"• {item}" for item in items) if items else "—"


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Подбор вакансий")
        self.resize(1200, 750)
        self.rows: list[dict] = []        # строки таблицы в порядке показа
        self.current: dict | None = None  # выбранная строка

        self.refresh_button = QPushButton("Обновить")
        self.refresh_button.clicked.connect(self.refresh)
        self.status_label = _label()
        self.progress = QProgressBar()
        self.progress.setMaximumWidth(250)
        self.progress.hide()
        top = QHBoxLayout()
        top.addWidget(self.refresh_button)
        top.addWidget(self.status_label, 1)
        top.addWidget(self.progress)

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().hide()
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.itemSelectionChanged.connect(self.on_select)

        splitter = QSplitter()
        splitter.addWidget(self.table)
        splitter.addWidget(self._build_details())
        splitter.setSizes([700, 500])

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.addLayout(top)
        layout.addWidget(splitter, 1)
        self.setCentralWidget(central)

        self.worker = Worker()
        self.worker.status.connect(self.status_label.setText)
        self.worker.progress.connect(self.on_progress)
        self.worker.evaluated.connect(self.on_evaluated)
        self.worker.finished.connect(self.on_finished)

        self.load_rows()
        QTimer.singleShot(0, self.refresh)  # обновление сразу после показа окна

    def _build_details(self) -> QWidget:
        self.d_title = _label(bold=True, point_size=13)
        self.d_meta = _label()
        self.d_score = _label(bold=True, point_size=12)
        self.d_texts = {}
        box = QVBoxLayout()
        for widget in (self.d_title, self.d_meta, self.d_score):
            box.addWidget(widget)
        for key, caption in SECTIONS:
            header = _label(bold=True)
            header.setText(caption)
            self.d_texts[key] = _label()
            box.addWidget(header)
            box.addWidget(self.d_texts[key])
        box.addStretch(1)
        self.details = QWidget()
        self.details.setLayout(box)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.details)

        self.open_button = QPushButton("Открыть вакансию")
        self.open_button.clicked.connect(self.open_job)
        self.hide_button = QPushButton("Скрыть")
        self.hide_button.clicked.connect(self.hide_job)
        buttons = QHBoxLayout()
        buttons.addWidget(self.open_button)
        buttons.addWidget(self.hide_button)
        buttons.addStretch(1)

        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.addWidget(scroll, 1)
        layout.addLayout(buttons)
        self.show_details(None)
        return panel

    def load_rows(self) -> None:
        """Перечитать из базы оценки по текущему резюме."""
        cv = read_cv()
        self.rows = db.list_jobs(cv[1], config.MIN_SCORE) if cv else []
        self.render()

    def render(self) -> None:
        """Перерисовать таблицу, сохранив выделение."""
        selected = self.current["url"] if self.current else None
        self.table.blockSignals(True)
        self.table.clearSelection()
        self.table.setRowCount(len(self.rows))
        for i, row in enumerate(self.rows):
            values = [str(row["score"]), row["title"], row["company"], row["city"], row["published"]]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 0:
                    item.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(i, column, item)
            if row["url"] == selected:
                self.table.selectRow(i)
        self.table.blockSignals(False)
        if selected and selected not in (row["url"] for row in self.rows):
            self.show_details(None)

    def on_select(self) -> None:
        indexes = self.table.selectionModel().selectedRows()
        self.show_details(self.rows[indexes[0].row()] if indexes else None)

    def show_details(self, row: dict | None) -> None:
        self.current = row
        self.details.setVisible(row is not None)
        self.open_button.setEnabled(row is not None)
        self.hide_button.setEnabled(row is not None)
        if row is None:
            return
        evaluation = row["evaluation"]
        self.d_title.setText(row["title"])
        self.d_meta.setText(f"{row['company']} · {row['city']} · {row['published']}\nИсточник: {row['source']}")
        self.d_score.setText(f"Оценка: {row['score']} из 10")
        self.d_texts["summary"].setText(evaluation.get("summary") or "—")
        for key in ("have", "missing", "risks"):
            self.d_texts[key].setText(_bullets(evaluation.get(key) or []))

    def refresh(self) -> None:
        self.refresh_button.setEnabled(False)
        self.load_rows()  # если резюме изменилось, старые оценки уходят из списка
        self.worker.start()

    def on_progress(self, done: int, total: int) -> None:
        self.progress.setMaximum(total)
        self.progress.setValue(done)
        self.progress.show()
        self.status_label.setText(f"Оценено {done} из {total}")

    def on_evaluated(self, row: dict) -> None:
        if row["score"] < config.MIN_SCORE:
            return
        self.rows.append(row)
        self.rows.sort(key=lambda r: (r["score"], r["published"]), reverse=True)
        self.render()

    def on_finished(self) -> None:
        self.progress.hide()
        self.refresh_button.setEnabled(True)

    def open_job(self) -> None:
        QDesktopServices.openUrl(QUrl(self.current["url"]))

    def hide_job(self) -> None:
        url = self.current["url"]
        db.hide(url)
        self.rows = [row for row in self.rows if row["url"] != url]
        self.show_details(None)
        self.render()

    def closeEvent(self, event) -> None:
        if self.worker.model_loaded:
            llm.release(wait=False)  # не ждём: окно должно закрыться сразу
        event.accept()
```

- [ ] **Step 5: Убедиться, что тесты проходят**

Run: `.venv/Scripts/python -m pytest tests -v`
Expected: `25 passed`

- [ ] **Step 6: Написать `job_finder/__main__.py`**

```python
"""Точка входа: python -m job_finder (ярлык запускает её через pythonw.exe)."""
import logging
import os
import sys

from PySide6.QtWidgets import QApplication

from job_finder import config, db
from job_finder.window import MainWindow


def main() -> None:
    logging.basicConfig(
        filename=config.LOG_PATH, encoding="utf-8", level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    # У pythonw нет консоли: необработанные исключения пишем в лог
    sys.excepthook = lambda *exc_info: logging.critical("Необработанное исключение", exc_info=exc_info)
    db.init()
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    code = app.exec()
    # Выходим сразу, не дожидаясь фонового потока с текущим запросом к модели
    os._exit(code)


if __name__ == "__main__":
    main()
```

- [ ] **Step 7: Запустить приложение и проверить закрытие посреди оценки**

Run (в фоне): `.venv/Scripts/python -m job_finder`
Через 2–3 минуты:
- `grep -E "Загружено|К оценке|ERROR|CRITICAL" job_finder.log` → есть строки «Загружено: {...}» и «К оценке: N» с N > 0, нет ERROR и CRITICAL (кроме ошибок отдельных источников, если они были);
- `PYTHONUTF8=1 .venv/Scripts/python -X utf8 -c "import sqlite3; print(sqlite3.connect('jobs.db').execute('SELECT COUNT(*) FROM jobs WHERE score IS NOT NULL').fetchone())"` → число больше 0 и растёт при повторном запуске команды.

Затем закрыть окно так, как это делает пользователь (одинарные кавычки — чтобы bash не подставил `$_`): `powershell -NoProfile -Command 'Get-Process python | Where-Object { $_.MainWindowTitle -eq "Подбор вакансий" } | ForEach-Object { $_.CloseMainWindow() }'`.
Через 10 с: `"$USERPROFILE/.lmstudio/bin/lms.exe" ps` → загруженных моделей нет; фоновый процесс `python -m job_finder` завершился.

- [ ] **Step 8: Commit**

```bash
git add job_finder/worker.py job_finder/window.py job_finder/__main__.py tests/test_window.py
git commit -m "Add main window and background refresh" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Установка, ярлык и проверка целиком

**Files:**
- Create: `install.ps1`

**Interfaces:**
- Consumes: `requirements.txt`, пакет `job_finder` (запуск `pythonw.exe -m job_finder`).
- Produces: ярлык «Подбор вакансий» на рабочем столе.

- [ ] **Step 1: Написать `install.ps1`**

```powershell
# Установка: виртуальное окружение, зависимости и ярлык «Подбор вакансий» на рабочем столе.
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"

if (-not (Test-Path $python)) {
    py -3.11 -m venv (Join-Path $root ".venv")
    if ($LASTEXITCODE -ne 0) { throw "Не удалось создать .venv (нужен Python 3.11)" }
}
& $python -m pip install -r (Join-Path $root "requirements.txt")
if ($LASTEXITCODE -ne 0) { throw "Не удалось поставить зависимости" }

$desktop = [Environment]::GetFolderPath("Desktop")
$shortcut = (New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $desktop "Подбор вакансий.lnk"))
$shortcut.TargetPath = Join-Path $root ".venv\Scripts\pythonw.exe"
$shortcut.Arguments = "-m job_finder"
$shortcut.WorkingDirectory = $root
$shortcut.Description = "Подбор вакансий"
$shortcut.Save()
Write-Output "Готово: ярлык «Подбор вакансий» на рабочем столе"
```

- [ ] **Step 2: Сохранить `install.ps1` в UTF-8 с BOM (иначе Windows PowerShell 5.1 испортит кириллицу)**

Run: `head -c 3 install.ps1 | od -An -tx1 | grep -q "ef bb bf" || { printf '\xef\xbb\xbf' | cat - install.ps1 > install.ps1.tmp && mv install.ps1.tmp install.ps1; }; head -c 3 install.ps1 | od -An -tx1`
Expected: ` ef bb bf`

- [ ] **Step 3: Запустить установку**

Run: `powershell -NoProfile -ExecutionPolicy Bypass -File install.ps1`
Expected: последняя строка `Готово: ярлык «Подбор вакансий» на рабочем столе`

- [ ] **Step 4: Проверить ярлык**

Run: `powershell -NoProfile -Command '$s = (New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path ([Environment]::GetFolderPath("Desktop")) "Подбор вакансий.lnk")); $s.TargetPath; $s.Arguments; $s.WorkingDirectory'`
Expected: путь к `...\job_finder_cv\.venv\Scripts\pythonw.exe`, `-m job_finder`, путь к корню проекта.

- [ ] **Step 5: Запустить приложение через ярлык (то же, что двойной клик) и дождаться первой полной оценки**

Run: `powershell -NoProfile -Command "Start-Process (Join-Path ([Environment]::GetFolderPath('Desktop')) 'Подбор вакансий.lnk')"`
Затем:
- `powershell -NoProfile -Command "Get-Process pythonw | Select-Object Id, MainWindowTitle"` → процесс `pythonw` с окном «Подбор вакансий» (у `pythonw` нет консоли);
- раз в несколько минут `tail -n 3 job_finder.log`, пока не появится строка «Готово: N подходящих» (первая полная оценка — около 30–40 минут).

- [ ] **Step 6: Попросить пользователя проверить окно**

Попросить пользователя посмотреть на открытое окно и подтвердить:
- список отсортирован по убыванию оценки, все оценки ≥ 5, колонки: Оценка, Вакансия, Компания, Город, Дата;
- по клику справа видны «Почему», «Есть», «Не хватает», «Может отсечь» и источник;
- «Открыть вакансию» открывает страницу вакансии в браузере;
- «Скрыть» убирает вакансию из списка;
- «Обновить» проходит быстро и не оценивает заново уже оценённое: в `job_finder.log` у последнего обновления «К оценке: 0» или небольшое число новых вакансий.

- [ ] **Step 7: Проверить повторную оценку после правки резюме и закрытие посреди оценки**

1. `cp master_cv.md master_cv.md.bak && printf '\n' >> master_cv.md` — изменить резюме, не меняя смысла.
2. Попросить пользователя нажать «Обновить» → в строке состояния «Оценено k из N», где N близко к числу всех вакансий, прошедших отсев; список сначала пустеет, потом заполняется заново.
3. Пока идёт оценка, попросить пользователя закрыть окно крестиком.
4. Через 10 с: `powershell -NoProfile -Command "Get-Process pythonw -ErrorAction SilentlyContinue"` → ничего; `"$USERPROFILE/.lmstudio/bin/lms.exe" ps` → загруженных моделей нет; `nvidia-smi --query-gpu=memory.used --format=csv` → видеопамять вернулась примерно к уровню без модели (~1,5 ГБ).
5. `mv master_cv.md.bak master_cv.md` — вернуть резюме. Убедиться, что `git status --short` не показывает `master_cv.md` и `.bak`.

- [ ] **Step 8: Commit**

```bash
git add install.ps1
git commit -m "Add installer with desktop shortcut" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```
