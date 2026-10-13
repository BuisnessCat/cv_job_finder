# Английский интерфейс — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** всё, что видит человек в приложении, — на английском; модель отвечает по-английски; в коде и
тестах не остаётся кириллицы.

**Architecture:** поведение не меняется — меняются только строки. Сначала фоновая часть (источники,
модель, строка состояния) и проверка, что английские правила оценивают так же, как русские; затем
окна; затем комментарии, тестовые данные и `install.ps1` под охраной теста «нет кириллицы»; затем
путеводитель `docs/guide/`; в конце — установка ярлыка и переоценка вживую.

**Tech Stack:** Python 3.11, PySide6, pytest, LM Studio (`lms`), SQLite.

**Spec:** `docs/superpowers/specs/2026-10-13-job-finder-design.md`, раздел 12 (таблица надписей —
обязательная), разделы 5 и 7 — поведение.

## Global Constraints

- Надписи — ровно как в таблице раздела 12 спека (регистр, «·», «—», «…», кавычки `"`).
- Правила оценки переводятся по смыслу, без изменения содержания; шкала не меняется.
- `docs/guide/`, спек и планы остаются по-русски; в `docs/guide/` меняются только цитаты надписей
  окна, описания английских строк (места, правила, `plural_days`) и ссылки на строки кода.
- В `job_finder/*.py`, `tests/*.py`, `install.ps1` — ни одного символа кириллицы (U+0400–U+04FF).
- `install.ps1` — только ASCII (Windows PowerShell 5.1 читает файл без BOM как ANSI).
- Тесты не трогают настоящие `master_cv.md` и `jobs.db`; оценка моделью — только на копии базы.
- Команда тестов: `.venv/Scripts/python -m pytest tests -q`.
- Коммит заканчивается строкой `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. Длинные английские надписи (кнопки отклика, «My applications · 12») не должны делать окно шире
   1200 px — тест в задаче 3.
2. Вакансии на чешском (junior.guru): модель всё равно отвечает по-английски — проверка в задаче 2
   (ни одного ответа с кириллицей, 3 ответа на чешские вакансии просмотреть глазами).
3. Строки базы с русскими местами («Удалённо», «Praha») до обновления: повторная загрузка
   переписывает место — тест в задаче 1.
4. Плашка «You already applied…» и подсказка после 14 дней собираются из данных и `STALE_DAYS` —
   точный текст проверяется тестом в задаче 3.
5. Заголовок окна «Job Finder» (по нему же пользователь узнаёт окно на панели задач) — тест в задаче 3.

---

### Task 1: Источники, модель и строка состояния

**Files:**
- Modify: `job_finder/sources.py` (места вакансий), `job_finder/llm.py` (`RULES`, сообщение
  пользователя, тексты ошибок), `job_finder/worker.py` (строка состояния)
- Test: `tests/test_sources.py`, `tests/test_llm.py`, `tests/test_worker.py`, `tests/test_db.py`

**Interfaces:**
- Consumes: —
- Produces: места `"Prague"`, `"Remote"`, `"Remote: <geo>"`, `"Remote (<страны> …)"`; `llm.RULES` на
  английском; строки состояния из таблицы спека («Loading jobs…», «Done: N matches out of M evaluated»…).

- [ ] **Step 1: Перевести ожидания в тестах источников**

В `tests/test_sources.py` заменить ожидаемые места (код разбора не трогать):
`"Praha"` → `"Prague"` в `test_parse_juniorguru` и `test_parse_juniorguru_keeps_only_prague_or_remote`
(только в ожидаемых `city`, не во входном CSV — там регион `Praha` остаётся как есть);
`"Удалённо"` → `"Remote"`; `"Удалённо (Czechia, Slovakia, Poland …)"` → `"Remote (Czechia, Slovakia, Poland …)"`;
`"Удалённо: Europe"` → `"Remote: Europe"`; `"Удалённо: Time zone: CET (+/- 3 hours)"` →
`"Remote: Time zone: CET (+/- 3 hours)"`; в тесте пустых полей — `("", "", "Remote", "")`,
`("Dev", "", "Remote", "")`, `("Ops", "", "Remote", "")`.

- [ ] **Step 2: Тест — повторная загрузка переписывает место**

В конец `tests/test_db.py`:

```python
def test_refetch_rewrites_city():
    # Rows saved before the English UI keep Russian place names until the next fetch rewrites them
    db.save_jobs("Jobicy", [Job(url="a", source="Jobicy", title="Job a", company="ACME", city="Удалённо",
                                published="2026-10-01", description="Python")])
    db.save_evaluation("a", evaluation(8), "h1")
    db.save_jobs("Jobicy", [Job(url="a", source="Jobicy", title="Job a", company="ACME", city="Remote",
                                published="2026-10-01", description="Python")])
    assert db.list_jobs("h1", 5)[0]["city"] == "Remote"
```

(Кириллица во входных данных этого теста временная: в задаче 4 `"Удалённо"` заменяется на
`"Удалённо"` — та же строка, записанная escape-кодами.)

- [ ] **Step 3: Перевести ожидания в тестах модели и фонового обновления**

`tests/test_llm.py`, `test_evaluate_sends_cv_and_truncated_vacancy`: во входной вакансии
`city="Prague"`; после проверки `user.count("x")` добавить:

```python
    assert user.startswith("Title: Python Dev\nCompany: ACME\nLocation: Prague\nSource: Jobicy\n\n")
    assert "Write all texts in English" in body["messages"][0]["content"]
```

и заменить `"Praha" in user` на `"Prague" in user`.

`tests/test_worker.py`: в `test_summary_counts_suitable_and_evaluated` ожидание
`"Done: 2 matches out of 3 evaluated"`; добавить тест:

```python
def test_missing_cv_skips_evaluation(setup, monkeypatch):
    config.CV_PATH.unlink()
    monkeypatch.setattr(llm, "evaluate", lambda cv_text, job: pytest.fail("must not evaluate"))
    assert worker.Worker()._refresh() == "No master_cv.md, evaluation skipped"
```

- [ ] **Step 4: Запустить — должны упасть**

Run: `.venv/Scripts/python -m pytest tests/test_sources.py tests/test_llm.py tests/test_worker.py tests/test_db.py -q`
Expected: FAIL — места `"Praha"/"Удалённо…"` вместо `"Prague"/"Remote…"`, `Title:` не найден,
`Готово: …` вместо `Done: …`; `test_refetch_rewrites_city` проходит сразу (поведение уже есть — это
закрепление, а не новая функция).

- [ ] **Step 5: Источники**

`job_finder/sources.py`: в `parse_juniorguru` — `city = "Prague"` при регионе `"Praha"` (проверка
`if "Praha" in regions` остаётся: это значение из данных), `city = "Remote"` для удалёнки; в
`parse_himalayas` — `"Remote"` вместо `"Удалённо"` (с теми же странами в скобках); в `parse_jobicy` и
`parse_workingnomads` — `f"Remote: {...}"` и `"Remote"`.

- [ ] **Step 6: Модель**

`job_finder/llm.py` — `RULES` целиком заменить на:

```python
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
```

В `evaluate()` сообщение пользователя:

```python
    vacancy = (
        f"Title: {job.title}\nCompany: {job.company}\nLocation: {job.city}\nSource: {job.source}\n\n"
        f"{job.description[:config.MAX_DESCRIPTION_CHARS]}"
    )
```

Тексты ошибок: `f"not found: {config.LMS_EXE}"`, `"server did not start within 30 s"`,
`f"model failed to load: {(result.stderr or result.stdout).strip()[-300:]}"`,
`f"model {config.MODEL_ID} was unloaded (got an answer from {data.get('model')}), evaluation stopped"`.

- [ ] **Step 7: Строка состояния**

`job_finder/worker.py`: `"Loading jobs…"`; `f"{name}: error ({error})"`;
`"No master_cv.md, evaluation skipped"`; `"No Skills section in master_cv.md, evaluation skipped"`;
`"Starting LM Studio…"`; `f"failed to evaluate: {failed}"`; `f"LM Studio: {error}"` (без изменений);
`f"Done: {suitable} matches out of {evaluated} evaluated"`; `"Update failed, see job_finder.log"`.

- [ ] **Step 8: Запустить — должны пройти**

Run: `.venv/Scripts/python -m pytest tests -q`
Expected: PASS всех тестов, кроме `tests/test_window.py`, где строки окна ещё русские: там могут
упасть только тесты, сравнивающие надписи окна (их переводит задача 3) — сверить список упавших:
ни одного вне `test_window.py`.

Ruling на случай расхождения: если в `test_window.py` что-то падает из-за `"Praha"` в `row()`, это
данные теста, а не надпись — оставить до задачи 3.

- [ ] **Step 9: Commit**

```bash
git add job_finder/sources.py job_finder/llm.py job_finder/worker.py tests/test_sources.py tests/test_llm.py tests/test_worker.py tests/test_db.py
git commit -m "Translate places, scoring rules and status messages to English"
```

---

### Task 2: Английские правила оценивают так же, как русские

**Files:**
- Create (вне репозитория, в scratchpad сессии): `scripts/compare_rules.py`
- Modify (только если сравнение не прошло): `job_finder/llm.py` — формулировки `RULES`, не шкала

**Interfaces:**
- Consumes: `llm.prepare()`, `llm.evaluate(cv_text, job)`, `llm.release()`, `worker.read_cv()` из задачи 1
- Produces: числа сравнения в журнале (`progress.md`)

- [ ] **Step 1: Скопировать базу и написать скрипт сравнения**

```bash
cp jobs.db "$SCRATCH/jobs-compare.db"
```

`$SCRATCH/scripts/compare_rules.py`:

```python
"""Old (Russian) vs new (English) rules on the same jobs from a DB copy. Argument: path to the copy."""
import random
import re
import sqlite3
import statistics
import sys

from job_finder import llm, worker
from job_finder.sources import Job

CYRILLIC = re.compile("[Ѐ-ӿ]")
PLACES = {"Praha": "Prague"}

conn = sqlite3.connect(sys.argv[1])
conn.row_factory = sqlite3.Row
rows = conn.execute("""SELECT url, source, title, company, city, published, description, score FROM jobs
                       WHERE active = 1 AND hidden = 0 AND status IS NULL AND score IS NOT NULL""").fetchall()
random.seed(1)
high = [r for r in rows if r["score"] >= 5]
low = [r for r in rows if r["score"] < 5]
sample = random.sample(high, min(20, len(high))) + random.sample(low, min(20, len(low)))
cv_text, _ = worker.read_cv()
llm.prepare()
pairs, cyrillic = [], []
try:
    for r in sample:
        city = PLACES.get(r["city"], r["city"].replace("Удалённо", "Remote"))
        job = Job(r["url"], r["source"], r["title"], r["company"], city, r["published"], r["description"])
        new = llm.evaluate(cv_text, job)
        pairs.append((r["score"], new["score"], r["source"], r["title"][:60]))
        if CYRILLIC.search(" ".join([new["summary"], *new["have"], *new["missing"], *new["risks"]])):
            cyrillic.append(r["title"])
        print(f"{r['score']:>2} -> {new['score']:>2}  [{r['source']}] {r['title'][:60]} | {new['summary'][:90]}",
              flush=True)
finally:
    llm.release()
old, new = [p[0] for p in pairs], [p[1] for p in pairs]
print(f"mean {statistics.mean(old):.2f} -> {statistics.mean(new):.2f}")
print(f">=5  {sum(s >= 5 for s in old)} -> {sum(s >= 5 for s in new)} of {len(pairs)}")
print("big moves (|diff| >= 3):", [p for p in pairs if abs(p[0] - p[1]) >= 3])
print("answers with Cyrillic:", cyrillic)
```

(Скрипт лежит вне репозитория, тест «нет кириллицы» его не касается.)

- [ ] **Step 2: Запустить сравнение**

Окно приложения в этот момент не должно оценивать (иначе оба процесса делят модель): если оно
открыто и идёт обновление — дождаться «Готово/Done» в строке состояния.

Run: `cd <корень проекта> && PYTHONIOENCODING=utf-8 .venv/Scripts/python "$SCRATCH/scripts/compare_rules.py" "$SCRATCH/jobs-compare.db" > "$SCRATCH/compare.txt" 2>&1` (в фоне, ~6–8 мин)
Expected: 40 строк `old -> new`, затем итоги.

- [ ] **Step 3: Оценить итоги**

Критерии «не сдвинулись заметно»: |Δ средней| ≤ 0,7; |Δ числа ≥ 5| ≤ 3 из 40; ответов с кириллицей — 0;
три ответа на вакансии junior.guru (чешские) — на английском. Записать в журнал строку
`Task 2: compare: mean A -> B, >=5 C -> D of 40, cyrillic 0, big moves: …`.

Если критерий не выполнен — поправить формулировку `RULES`, вызвавшую сдвиг (смотреть на
«big moves» и их summary), не меняя шкалу; повторить шаг 2; записать `Ruling:` с причиной правки.
Не больше двух итераций; если и после второй не сходится — остановиться и показать пользователю числа.

- [ ] **Step 4: Commit (только если `RULES` правились)**

```bash
git add job_finder/llm.py
git commit -m "Tune English scoring rules to match the previous scores"
```

---

### Task 3: Главное окно, окно «Резюме», второй запуск

**Files:**
- Modify: `job_finder/window.py`, `job_finder/cv_window.py`, `job_finder/__main__.py`
- Test: `tests/test_window.py`, `tests/test_cv_window.py`

**Interfaces:**
- Consumes: места `"Prague"/"Remote…"` из задачи 1 (только как данные в тестах)
- Produces: `plural_days(n: int) -> str` — `"1 day"` / `"N days"`; константы `COLUMNS`,
  `APPLIED_COLUMNS`, `LISTS`, `EMPTY_LIST`, `STATUS_TEXT` с английскими надписями.

- [ ] **Step 1: Перевести ожидания в тестах окна**

`tests/test_window.py`:
- в `row()` и `add_found()` — `"Prague"` вместо `"Praha"`;
- `"ЕСТЬ · 2"` → `"YOU HAVE · 2"`; `["Блокеров не найдено"]` → `["No blockers found"]`;
- `"Ждём ответа"` → `"Waiting"` (все места); `"Приняли"` → `"Accepted"`; `"Отказали"` → `"Rejected"`;
- `"Найденные · 1"` → `"Found · 1"`; `"Найденные · 2 (+1)"` → `"Found · 2 (+1)"`;
  `"Мои отклики · 1"` → `"My applications · 1"`; `"Мои отклики · 0"` → `"My applications · 0"`;
- `test_days_waiting_and_plural` целиком:

```python
def test_days_waiting_and_plural():
    assert days_waiting("2026-09-22", date(2026, 10, 13)) == 21
    assert [plural_days(n) for n in (0, 1, 2, 11, 21)] == ["0 days", "1 day", "2 days", "11 days", "21 days"]
```

- в `test_waiting_days_and_stale_highlight`: `"20 дней"` → `"20 days"`; последняя проверка —
  `assert window.d_stale.isHidden() and "days" not in window.d_status.text()`; после
  `assert "20 days" in …` добавить
  `assert window.d_stale.text() == f"No reply for over {config.STALE_DAYS} days — time to follow up or close it"`;
- в `test_repost_marked` вместо `"Вы уже подавались" in …`:

```python
    applied_at = date.today().isoformat()
    assert window.d_notice.text() == f'You already applied to "Python Dev" at ACME on {applied_at} — status: waiting'
```

Добавить тесты:

```python
def test_english_window_texts(window):
    assert window.windowTitle() == "Job Finder"
    assert window.refresh_button.text() == "Refresh" and window.cv_button.text() == "My CV"
    headers = lambda table: [table.horizontalHeaderItem(i).text() for i in range(table.columnCount())]
    assert headers(window.table) == ["Score", "Job", "Company", "Location", "Date"]
    assert headers(window.applied_table) == ["Applied", "Job", "Company", "Status", "Days waiting", "Score"]
    assert [b.text() for b in (window.open_button, window.apply_button, window.hide_button,
                               window.unapply_button)] == ["Open job", "I applied", "Hide", "Back to found"]
    assert window.badge_caption.text() == "of 10"


def test_application_card_fits_window_width(window):
    add_found("a", 8, title="Junior Python Backend Developer (Django, FastAPI, PostgreSQL)")
    for i in range(12):
        add_found(f"x{i}", 6)
        db.apply(f"x{i}")
    db.apply("a")
    window.load_rows()
    window.show_tab(1)
    window.applied_table.selectRow([r["url"] for r in window.applied].index("a"))
    window.show()
    assert window.applied_tab.text() == "My applications · 13"
    assert window.minimumSizeHint().width() <= 1200
```

`tests/test_cv_window.py`, `test_missing_cv_shows_message`: `"не найден"` → `"not found"`; добавить:

```python
def test_english_cv_window_texts(app, cv_path):
    cv_path.write_text(CV, encoding="utf-8")
    window = CvWindow()
    assert window.windowTitle() == "My CV — master_cv.md"
    assert window.open_button.text() == "Open in editor"
```

- [ ] **Step 2: Запустить — должны упасть**

Run: `.venv/Scripts/python -m pytest tests/test_window.py tests/test_cv_window.py -q`
Expected: FAIL на русских надписях; `test_application_card_fits_window_width` может пройти сразу (это
страж ширины, а не новая функция) — записать в журнал, прошёл ли он до перевода.

- [ ] **Step 3: Перевести окно**

`job_finder/window.py` — константы:

```python
COLUMNS = ["Score", "Job", "Company", "Location", "Date"]
APPLIED_COLUMNS = ["Applied", "Job", "Company", "Status", "Days waiting", "Score"]
LISTS = [("have", "YOU HAVE", "✓"), ("missing", "MISSING", "✕"), ("risks", "RISKS", "!")]
EMPTY_LIST = {"have": "—", "missing": "Nothing major"}
STATUS_TEXT = {"applied": "Waiting", "accepted": "Accepted", "rejected": "Rejected"}
```

```python
def plural_days(n: int) -> str:
    """"1 day", "3 days"."""
    return f"{n} day" if n == 1 else f"{n} days"
```

Надписи: заголовок `"Job Finder"`; `"Refresh"`; `"My CV"`; `"of 10"`; подсказка
`f"No reply for over {config.STALE_DAYS} days — time to follow up or close it"` (одной строкой
f-строки или двумя склеенными); поле заметок — placeholder `"Who you talked to, when the interview is…"`;
`_caption("NOTES")`; факты `("city", "Location"), ("published", "Published"), ("source", "Source")`;
`_caption("WHY THIS SCORE")`; кнопки `"Open job"`, `"I applied"`, `"Hide"`, `"Waiting"`,
`"Accepted"`, `"Rejected"`, `"Back to found"`; пустая карточка `"Select a job on the left"`;
`["No blockers found"]`; `f"Found · {len(self.rows)}"`; `f"My applications · {len(self.applied)}"`;
плашка `f"Applied {row['applied_at']} · {STATUS_TEXT[row['status']]}"`; прогресс
`f"Evaluated {done} of {total}"`; плашка «уже подавались»:

```python
            self.d_notice.setText(f'You already applied to "{previous["title"]}" at {previous["company"]}'
                                  f' on {previous["applied_at"]} — status: {STATUS_TEXT[previous["status"]].lower()}')
```

`job_finder/cv_window.py`: `"My CV — master_cv.md"`; `("File", …), ("Modified", …), ("Skills used for filtering", …)`;
`"Open in editor"`; `"Close"`; `"master_cv.md not found. Put it in the project folder and open this window again."`;
`"no Skills section found"`.

`job_finder/__main__.py`: `QMessageBox.information(None, "Job Finder", "Job Finder is already open.")`.

- [ ] **Step 4: Запустить — должны пройти**

Run: `.venv/Scripts/python -m pytest tests -q`
Expected: PASS всех тестов (70+).

- [ ] **Step 5: Commit**

```bash
git add job_finder/window.py job_finder/cv_window.py job_finder/__main__.py tests/test_window.py tests/test_cv_window.py
git commit -m "Translate the main window and the CV window to English"
```

---

### Task 4: Комментарии, docstring, лог, тестовые данные и install.ps1

**Files:**
- Create: `tests/test_english.py`
- Modify: все `job_finder/*.py` (комментарии, docstring, сообщения `log.*`), все `tests/*.py`
  (комментарии, тестовые данные), `install.ps1`

**Interfaces:**
- Consumes: английские строки из задач 1 и 3 (не меняются)
- Produces: —

- [ ] **Step 1: Тест «нет кириллицы»**

`tests/test_english.py`:

```python
"""The app is published in English: no Cyrillic in code, comments, tests or the installer."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CYRILLIC = re.compile("[Ѐ-ӿ]")  # escape codes, so this file passes its own check


def test_no_cyrillic_in_code():
    files = [*ROOT.glob("job_finder/*.py"), *ROOT.glob("tests/*.py"), ROOT / "install.ps1"]
    found = [f"{path.relative_to(ROOT)}:{number}: {line.strip()[:60]}"
             for path in files
             for number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1)
             if CYRILLIC.search(line)]
    assert found == []


def test_installer_is_ascii():
    assert (ROOT / "install.ps1").read_bytes().lstrip(b"\xef\xbb\xbf").isascii()
```

- [ ] **Step 2: Запустить — должен упасть**

Run: `.venv/Scripts/python -m pytest tests/test_english.py -q`
Expected: FAIL — список строк с кириллицей (комментарии, docstring, `log.*`, тестовые данные,
`install.ps1`).

- [ ] **Step 3: Перевести код пакета**

В каждом `job_finder/*.py` перевести комментарии, docstring и сообщения лога по смыслу. По
возможности строка в строку (то же число строк) — тогда ссылки `#Lx` в `docs/guide/` почти не
сдвигаются. Сообщения лога: `"Unhandled exception"`, `"Update crashed"`, `"Loaded: %s"`,
`"To evaluate: %d"`, `"LM Studio unavailable"`, `"Failed to evaluate %s"`, `"Source %s failed to load"`,
`"Failed to unload model"`. В `sources.py` комментарий про регион оставить по смыслу: «A region is more
reliable than a name: a Prague district (e.g. "Háje") has no "Praha" in its name».

- [ ] **Step 4: Перевести тесты**

Комментарии — по смыслу. Тестовые данные: `"Писал HR 30.09"` → `"Emailed HR on 30.09"`,
`"Собеседование в пятницу"` → `"Interview on Friday"`, `"Подходит"` → `"Good fit"`,
`"МОЁ РЕЗЮМЕ"` → `"MY CV"`, `"ответила qwen/qwen3.8-27b"` → `"got an answer from qwen/qwen3.8-27b"`,
`" другие правила"` → `" other rules"`. В `test_refetch_rewrites_city` старое русское место записать
escape-кодами: `city="Удалённо"`.

- [ ] **Step 5: install.ps1**

Полностью заменить (ASCII, без BOM):

```powershell
# Setup: virtual environment, dependencies and a "Job Finder" shortcut on the desktop.
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"

if (-not (Test-Path $python)) {
    py -3.11 -m venv (Join-Path $root ".venv")
    if ($LASTEXITCODE -ne 0) { throw "Could not create .venv (Python 3.11 is required)" }
}
& $python -m pip install -r (Join-Path $root "requirements.txt")
if ($LASTEXITCODE -ne 0) { throw "Could not install dependencies" }

$desktop = [Environment]::GetFolderPath("Desktop")
# The shortcut of the earlier Russian version; the name is spelled with char codes to keep this file ASCII
$oldName = -join ([char[]](0x41F,0x43E,0x434,0x431,0x43E,0x440,0x20,0x432,0x430,0x43A,0x430,0x43D,0x441,0x438,0x439)) + ".lnk"
Remove-Item (Join-Path $desktop $oldName) -ErrorAction SilentlyContinue
$shortcut = (New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $desktop "Job Finder.lnk"))
$shortcut.TargetPath = Join-Path $root ".venv\Scripts\pythonw.exe"
$shortcut.Arguments = "-m job_finder"
$shortcut.WorkingDirectory = $root
$shortcut.IconLocation = (Join-Path $root "job_finder\icon.ico") + ",0"
$shortcut.Description = "Job Finder"
$shortcut.Save()
Write-Output "Done: a Job Finder shortcut is on the desktop"
```

Проверка кодов имени: `python -c "print(''.join(map(chr,[0x41F,0x43E,0x434,0x431,0x43E,0x440,0x20,0x432,0x430,0x43A,0x430,0x43D,0x441,0x438,0x439])))"`
Expected: `Подбор вакансий`.

- [ ] **Step 6: Запустить — должны пройти**

Run: `.venv/Scripts/python -m pytest tests -q`
Expected: PASS всех тестов, включая `tests/test_english.py`.

- [ ] **Step 7: Commit**

```bash
git add job_finder tests install.ps1
git commit -m "Translate comments, test data and the installer to English"
```

---

### Task 5: Путеводитель docs/guide

**Files:**
- Modify: `docs/guide/*.md`
- Create (scratchpad): `scripts/check_doc_links.py`

**Interfaces:**
- Consumes: итоговые строки кода из задач 1–4
- Produces: —

- [ ] **Step 1: Цитаты надписей и описания**

В `docs/guide/*.md` заменить цитаты надписей окна по таблице раздела 12 спека («Обновить» →
«Refresh», «Резюме» → «My CV», «Ждём ответа» → «Waiting», «Подался» → «I applied», «Скрыть» → «Hide»,
«Вернуть в найденные» → «Back to found», «Открыть вакансию» → «Open job», «из 10» → «of 10»,
«ПОЧЕМУ ТАКАЯ ОЦЕНКА» → «WHY THIS SCORE», «ЗАМЕТКИ» → «NOTES», «Ничего существенного» → «Nothing major»,
«Ждём, дн.» → «Days waiting», «Оценено N из M» → «Evaluated N of M», «Готово: …» → «Done: …»,
«Подбор вакансий» → «Job Finder» и т. д. — найти все: `grep -n "«" docs/guide/*.md`). Места вакансий:
«Praha»/«Удалённо» → «Prague»/«Remote» там, где речь о выводе (регион `Praha` во входных данных
junior.guru остаётся). Описание `plural_days` — «1 day / N days» вместо склонения. В `05-llm.md` —
правила теперь на английском, ответы модели на английском, сообщение пользователя
`Title / Company / Location / Source`. В `README.md` путеводителя — одна фраза: интерфейс и код на
английском, путеводитель по-русски. Текст пояснений остаётся русским.

- [ ] **Step 2: Пересчитать ссылки на строки**

Код до перевода — `git show main:job_finder/<file>.py`. Ссылки вида `../../job_finder/x.py#L12` и
`../../tests/test_x.py#L34` пересчитать: для каждой найти, где та же строка (def, class, присваивание)
оказалась в новом файле. Скрипт проверки `$SCRATCH/scripts/check_doc_links.py`:

```python
"""Check docs/guide links: line in range, label number = anchor, target line not blank, named def is there."""
import re
import sys
from pathlib import Path

root = Path(sys.argv[1])
LINK = re.compile(r"\[([^\]]*)\]\(((?:\.\./)+)((?:job_finder|tests)/[\w.]+\.py)#L(\d+)(?:-L?(\d+))?\)")
problems = []
for doc in sorted((root / "docs" / "guide").glob("*.md")):
    for m in LINK.finditer(doc.read_text(encoding="utf-8")):
        label, path, start = m.group(1), m.group(3), int(m.group(4))
        lines = (root / path).read_text(encoding="utf-8").splitlines()
        if start > len(lines) or not lines[start - 1].strip():
            problems.append(f"{doc.name}: {path}#L{start} out of range or blank")
            continue
        numbers = re.findall(r":(\d+)", label)
        if numbers and int(numbers[0]) != start:
            problems.append(f"{doc.name}: label {label} != #L{start}")
        name = re.match(r"`?(\w+)", label)
        if name and not label.startswith(Path(path).name) and name.group(1) not in lines[start - 1]:
            problems.append(f"{doc.name}: {label} not on {path}#L{start}: {lines[start - 1].strip()[:60]}")
print("\n".join(problems) or "ok")
```

Run: `PYTHONIOENCODING=utf-8 .venv/Scripts/python "$SCRATCH/scripts/check_doc_links.py" .`
Expected: `ok` (каждую найденную проблему исправить вручную и запустить снова).

- [ ] **Step 3: Тесты не сломаны**

Run: `.venv/Scripts/python -m pytest tests -q`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add docs/guide
git commit -m "Update the code guide for the English interface"
```

---

### Task 6: Ярлык и переоценка вживую

**Files:** — (только установка и проверка)

**Interfaces:**
- Consumes: всё из задач 1–5
- Produces: ярлык «Job Finder» на рабочем столе, база с английскими оценками

- [ ] **Step 1: Закрыть старое окно**

Если приложение открыто (процесс `pythonw.exe` с `-m job_finder`), попросить пользователя закрыть
окно (закрытие выгружает модель и отмечает просмотренные).

- [ ] **Step 2: Ярлык**

Run: `powershell -ExecutionPolicy Bypass -File install.ps1`
Expected: `Done: a Job Finder shortcut is on the desktop`; на рабочем столе есть `Job Finder.lnk`,
нет `Подбор вакансий.lnk`.

- [ ] **Step 3: Запуск и переоценка**

Запустить ярлык (`start "" "<Desktop>/Job Finder.lnk"`). Обновление начинается само; ключ оценки
сменился, поэтому оцениваются все вакансии (~35 мин). Через 2–3 минуты проверить по базе, что новые
оценки пишутся по-английски:

```bash
.venv/Scripts/python -c "import sqlite3,json; c=sqlite3.connect('jobs.db'); [print(r[0], json.loads(r[1])['summary'][:100]) for r in c.execute('select score, evaluation from jobs where cv_hash is not null order by rowid desc limit 3')]"
```

Expected: английские `summary`; места в списке — `Prague` / `Remote…`.

- [ ] **Step 4: Скриншот окна**

Снять окно (найденные с выбранной вакансией) и показать пользователю — надписи на английском,
ничего не обрезано по ширине. Перед снимком несколько раз `processEvents`.
