# Свежесть и базовые удобства — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** в окне видно, насколько вакансия свежая, «освежённые» старые вакансии не выдают себя за новые,
есть фильтры и порядок над Found, описание в карточке, оставшееся время оценки, вопрос при закрытии,
отмена «Hide» и честная пометка «похоже, закрыли» в откликах.

**Architecture:** чистые функции дат и фильтрации — в новом модуле `job_finder/freshness.py` (без Qt и
базы, легко тестировать); база получает колонку `first_seen` и несколько маленьких функций; окно только
вызывает их. Оценки и ключ оценки не меняются.

**Tech Stack:** Python 3.11, PySide6, SQLite, pytest.

**Spec:** `docs/superpowers/specs/2026-10-13-job-finder-design.md`, раздел 14 (обязательный).

## Global Constraints

- Надписи — ровно как в разделе 14: «Posted», «today», «1 day ago», «N days ago», «—», «reposted»,
  «Search title, company or location», сегменты «7d», «14d», «30d», «All» (подсказки «Last 7 days»,
  «Last 14 days», «Last 30 days», «Any time»), сегменты «Best», «Newest», «N of M shown», «No jobs match the filters», «DESCRIPTION»,
  «Show description», «Collapse», «Evaluated N of M · ~K min left», «<1 min left», «A refresh is in
  progress. Close anyway? Jobs scored so far are saved.», «Close», «Keep open», «Hidden: <title>»,
  «Undo», «No longer listed on <source> — probably filled», «first seen … ago».
- `STALE_JOB_DAYS = 21`, `FULL_LIST_SOURCES = ("junior.guru", "Jobicy")` — в `config.py`; фильтр по
  умолчанию «30d», порядок по умолчанию «Best»; все элементы шапки — высотой 32 px; «reposted» — `published` позже
  `first_seen` больше чем на 2 дня; оценка времени — после 3 оценённых, минуты вверх; «Undo» — 10 с.
- Ничего не меняет ключ оценки и не запускает переоценку.
- В `job_finder/*.py`, `tests/*.py` — без кириллицы (`tests/test_english.py`).
- Команда тестов: `.venv/Scripts/python -m pytest tests -q`.
- Коммит заканчивается строкой `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Карточка: факт «Published» = `<published> (<возраст published>)`, а у «reposted» ещё
  `· first seen <возраст first_seen>` (колонка «Posted» в таблице — возраст **даты вакансии**, то есть
  более ранней из двух, плюс `· reposted`).

## Review Focus

1. Вакансия без `published` и без `first_seen` (старые строки, null из API): «—», проходит любой фильтр,
   в «Newest» в конце, ничего не падает — тест в задаче 2.
2. При включённом фильтре выбор строки открывает ту вакансию, что видна в этой строке, а не ту, что
   стоит на этом месте в полном списке — тест в задаче 3.
3. Поиск со спецсимволами («C++», «(remote)») — простая подстрока, не регулярное выражение — тест в
   задаче 2.
4. Обновление упало или закончилось — флаг «идёт обновление» снят, и закрытие окна не спрашивает — тест
   в задаче 4.
5. «Undo» для вакансии, которая после возврата не проходит фильтр или пропала из списка, — не падает;
   второе скрытие заменяет первую отмену — тест в задаче 4.

---

### Task 1: База — `first_seen`, описание, возврат скрытой, пометка «закрыли»

**Files:**
- Modify: `job_finder/config.py`, `job_finder/db.py`, `job_finder/worker.py`
- Test: `tests/test_db.py`, `tests/test_worker.py`

**Interfaces:**
- Produces:
  - `config.STALE_JOB_DAYS = 21`, `config.FULL_LIST_SOURCES = ("junior.guru", "Jobicy")`;
  - колонка `first_seen TEXT` (`YYYY-MM-DD`);
  - `db.save_jobs(source: str, jobs: list[Job], today: str | None = None) -> None` — новая строка получает
    `first_seen` = самый ранний `first_seen` среди строк с тем же `sources.same_job_key(company, title)`,
    иначе `today` (по умолчанию `date.today().isoformat()`); при обновлении строки `first_seen` не
    меняется;
  - `db.make_row(job: Job, evaluation: dict, first_seen: str = "") -> dict` — в строке есть ключ
    `"first_seen"`;
  - `db.list_jobs` и `db.list_applied` отдают `"first_seen"`; `db.list_applied` ещё `"closed": bool` —
    `active = 0` **и** `source in config.FULL_LIST_SOURCES` **и** нет активной строки с тем же
    `same_job_key`;
  - `db.first_seen(url: str) -> str`, `db.description(url: str) -> str`, `db.unhide(url: str) -> None`;
  - воркер отдаёт оценённую строку с `first_seen` (`db.make_row(job, evaluation, db.first_seen(job.url))`).

- [ ] **Step 1: Тесты базы** (в `tests/test_db.py`; хелперы `job()` и `evaluation()` там уже есть)

```python
def test_first_seen_is_set_once():
    db.save_jobs("Jobicy", [job("a")], today="2026-10-01")
    db.save_jobs("Jobicy", [job("a", published="2026-10-10")], today="2026-10-12")
    assert db.first_seen("a") == "2026-10-01"


def test_first_seen_inherited_from_same_company_and_title():
    db.save_jobs("Jobicy", [job("old")], today="2026-09-01")      # "Job old" at ACME
    repost = Job(url="new", source="Himalayas", title="Job old", company="acme ", city="Remote",
                 published="2026-10-10", description="")
    db.save_jobs("Himalayas", [repost], today="2026-10-12")
    assert db.first_seen("new") == "2026-09-01"


def test_list_rows_carry_first_seen_and_description_is_read_on_demand():
    db.save_jobs("Jobicy", [job("a")], today="2026-10-01")
    db.save_evaluation("a", evaluation(8), "h1")
    assert db.list_jobs("h1", 5)[0]["first_seen"] == "2026-10-01"
    assert db.description("a") == "Python"


def test_unhide_returns_job():
    db.save_jobs("Jobicy", [job("a")])
    db.save_evaluation("a", evaluation(8), "h1")
    db.hide("a")
    db.unhide("a")
    assert [r["url"] for r in db.list_jobs("h1", 5)] == ["a"]


def test_closed_mark_only_for_full_list_sources():
    jg = Job(url="jg", source="junior.guru", title="Dev", company="A", city="Prague", published="2026-10-01",
             description="")
    him = Job(url="him", source="Himalayas", title="Dev", company="B", city="Remote", published="2026-10-01",
              description="")
    db.save_jobs("junior.guru", [jg])
    db.save_jobs("Himalayas", [him])
    for url in ("jg", "him"):
        db.save_evaluation(url, evaluation(8), "h1")
        db.apply(url)
    db.save_jobs("junior.guru", [])
    db.save_jobs("Himalayas", [])
    closed = {r["url"]: r["closed"] for r in db.list_applied()}
    assert closed == {"jg": True, "him": False}


def test_closed_mark_skipped_when_listed_elsewhere():
    jg = Job(url="jg", source="junior.guru", title="Dev", company="A", city="Prague", published="2026-10-01",
             description="")
    db.save_jobs("junior.guru", [jg])
    db.save_evaluation("jg", evaluation(8), "h1")
    db.apply("jg")
    db.save_jobs("junior.guru", [])
    db.save_jobs("Jobicy", [Job(url="jb", source="Jobicy", title="dev", company="a", city="Remote",
                                published="2026-10-02", description="")])
    assert db.list_applied()[0]["closed"] is False
```

Дополнить `test_init_adds_columns_to_old_database` (или новый тест рядом): старая база без `first_seen`
после `db.init()` получает `first_seen == published` у имевшейся строки.

`tests/test_worker.py` — в `test_summary_counts_suitable_and_evaluated` (или новом тесте) проверить,
что строки из сигнала `evaluated` содержат `"first_seen"` (подписаться на сигнал списком).

- [ ] **Step 2: Запустить — должны упасть**

Run: `.venv/Scripts/python -m pytest tests/test_db.py tests/test_worker.py -q`
Expected: FAIL — нет `first_seen`, `description`, `unhide`, `closed`, параметра `today`.

- [ ] **Step 3: Реализация** — колонка в `SCHEMA` и миграция в `init()` по образцу `seen`
(`ALTER TABLE … ADD COLUMN first_seen TEXT`, затем `UPDATE jobs SET first_seen = COALESCE(NULLIF(published, ''), ?)`
с сегодняшней датой); в `save_jobs` перед upsert — словарь `same_job_key → min(first_seen)` по всей
таблице, `first_seen` в `INSERT`, но не в `DO UPDATE SET`; остальное — по Interfaces.

- [ ] **Step 4: Запустить — должны пройти**

Run: `.venv/Scripts/python -m pytest tests -q`
Expected: PASS.

- [ ] **Step 5: Commit** — `git commit -m "Remember when a job was first seen; description, unhide and closed marks"`

---

### Task 2: Чистые функции свежести

**Files:**
- Create: `job_finder/freshness.py`
- Test: `tests/test_freshness.py`

**Interfaces:**
- Consumes: строки окна (`dict` с ключами `title`, `company`, `city`, `published`, `first_seen`, `score`).
- Produces:
  - `job_date(published: str, first_seen: str) -> str` — более ранняя непустая из двух, иначе `""`;
  - `age_text(day: str, today: date) -> str` — «today» (0 дней и дата в будущем), «1 day ago»,
    «N days ago», `""` → «—»;
  - `age_days(day: str, today: date) -> int | None`;
  - `is_reposted(published: str, first_seen: str) -> bool` — обе даты есть и `published` позже
    `first_seen` больше чем на 2 дня;
  - `FRESHNESS = [("7d", "Last 7 days", 7), ("14d", "Last 14 days", 14), ("30d", "Last 30 days", 30),
    ("All", "Any time", None)]`, `ORDERS = ["Best", "Newest"]`;
  - `visible_rows(rows: list[dict], query: str, days: int | None, order: str, today: date) -> list[dict]`;
  - `time_left_text(elapsed: float, done: int, total: int) -> str` — `""` при `done < 3`, иначе
    «~K min left» (K вверх) или «<1 min left».

- [ ] **Step 1: Тесты**

```python
from datetime import date
from job_finder.freshness import age_text, is_reposted, job_date, time_left_text, visible_rows

TODAY = date(2026, 10, 17)


def r(url, score=7, published="2026-10-15", first_seen="2026-10-15", title=None, company="ACME", city="Prague"):
    return {"url": url, "score": score, "published": published, "first_seen": first_seen,
            "title": title or f"Job {url}", "company": company, "city": city}


def test_job_date_and_age():
    assert job_date("2026-10-15", "2026-09-10") == "2026-09-10"
    assert job_date("", "2026-09-10") == "2026-09-10" and job_date("", "") == ""
    assert [age_text(d, TODAY) for d in ("2026-10-17", "2026-10-16", "2026-10-12", "2026-10-20", "")] == [
        "today", "1 day ago", "5 days ago", "today", "—"]


def test_reposted_needs_more_than_two_days():
    assert is_reposted("2026-10-15", "2026-09-10")
    assert not is_reposted("2026-10-12", "2026-10-10")
    assert not is_reposted("", "2026-10-10") and not is_reposted("2026-10-10", "")


def test_search_is_plain_substring_over_title_company_location():
    rows = [r("a", title="C++ Developer"), r("b", company="Prague Labs (remote)"), r("c", city="Brno")]
    assert [x["url"] for x in visible_rows(rows, "c++", None, "Best", TODAY)] == ["a"]
    assert [x["url"] for x in visible_rows(rows, "(REMOTE)", None, "Best", TODAY)] == ["b"]
    assert [x["url"] for x in visible_rows(rows, "brno", None, "Best", TODAY)] == ["c"]


def test_freshness_uses_job_date_and_keeps_undated():
    rows = [r("fresh"), r("bumped", published="2026-10-16", first_seen="2026-09-01"),
            r("undated", published="", first_seen="")]
    assert [x["url"] for x in visible_rows(rows, "", 7, "Best", TODAY)] == ["fresh", "undated"]


def test_orders():
    rows = [r("old_best", score=9, published="2026-10-01", first_seen="2026-10-01"),
            r("new_ok", score=6, published="2026-10-16", first_seen="2026-10-16"),
            r("undated", score=8, published="", first_seen="")]
    assert [x["url"] for x in visible_rows(rows, "", None, "Best", TODAY)] == ["old_best", "undated", "new_ok"]
    assert [x["url"] for x in visible_rows(rows, "", None, "Newest", TODAY)] == ["new_ok", "old_best", "undated"]


def test_time_left():
    assert time_left_text(20.0, 2, 10) == ""
    assert time_left_text(30.0, 3, 213) == "~35 min left"      # 10 s per job, 210 left
    assert time_left_text(30.0, 3, 6) == "<1 min left"
```

- [ ] **Step 2: Запустить — должны упасть**

Run: `.venv/Scripts/python -m pytest tests/test_freshness.py -q`
Expected: FAIL — нет модуля `job_finder.freshness`.

- [ ] **Step 3: Реализация** — по Interfaces. «Best»: `(score ↓, дата вакансии ↓)`, «Newest»:
`(дата вакансии ↓, score ↓)`, пустая дата — меньше любой (в конце при «Newest»).

- [ ] **Step 4: Запустить — должны пройти**

Run: `.venv/Scripts/python -m pytest tests -q`
Expected: PASS.

- [ ] **Step 5: Commit** — `git commit -m "Add freshness helpers: job age, reposted, filters, time left"`

---

### Task 3: Панель над Found, колонка «Posted», карточка «Published»

**Files:**
- Modify: `job_finder/window.py`, `job_finder/style.py` (если нужен стиль панели)
- Test: `tests/test_window.py`

**Interfaces:**
- Consumes: `freshness.*` из задачи 2; `first_seen` в строках из задачи 1.
- Produces: в `MainWindow`: `found_card: QFrame` (рамка: шапка + таблица + строка счётчика),
  `search: QLineEdit`, `freshness_buttons: QButtonGroup` (id 0–3, по умолчанию 2), `order_buttons:
  QButtonGroup` (id 0–1, по умолчанию 0), `shown_label: QLabel`, `no_match: QLabel`, `visible: list[dict]`
  (строки в порядке таблицы); `COLUMNS = ["Score", "Job", "Company", "Location", "Posted"]`.

Расположение выбрано пользователем по скриншотам (прототип `proto_freshness2.py`, вариант 3): таблица
найденных — в рамке `QFrame#foundCard` вместе с шапкой фильтров (поле поиска, сегменты в стиле переключателя
вкладок) и строкой «N of M shown» под таблицей; рамка верхним и нижним краем совпадает с карточкой справа.
На вкладке «My applications» — прежняя таблица откликов без рамки.

- [ ] **Step 1: Тесты окна** (хелперы `add_found`, `row`, `titles` уже есть; у `row()` добавить ключ
`"first_seen"` = `published`)

- `test_posted_column_shows_age_and_reposted` — строка с `published` = сегодня → «today»; строка с
  `published` = сегодня и `first_seen` = 30 дней назад → «30 days ago · reposted»; заголовок колонки
  «Posted»; строка старше `STALE_JOB_DAYS` — у ячейки «Job» цвет `style.COLORS["muted"]`.
- `test_filters_and_order_change_visible_rows` — поиск по компании оставляет одну строку; сегмент «7d»
  прячет старую; «Newest» меняет порядок; `shown_label` = «1 of 3 shown» и скрыт без фильтров;
  при пустом результате `no_match` виден с текстом «No jobs match the filters», таблица скрыта.
- `test_selection_maps_to_visible_row` — при фильтре, оставившем 2-ю вакансию из 3, `selectRow(0)` →
  `window.current["url"]` — эта 2-я вакансия.
- `test_selection_cleared_when_filtered_out` — выбрана вакансия, поиск её прячет → карточка пустая.
- `test_new_evaluation_respects_filters` — фильтр «7d», `on_evaluated` со старой вакансией → в
  таблице её нет, в `window.rows` есть.
- `test_card_published_shows_site_date_and_first_seen` — у «reposted» вакансии факт «Published» =
  `"<published> (today) · first seen 30 days ago"` (даты — от `date.today()`).
- Обновить `test_english_window_texts`: колонка «Posted» вместо «Date».

- [ ] **Step 2: Запустить — должны упасть**

Run: `.venv/Scripts/python -m pytest tests/test_window.py -q`
Expected: FAIL — нет панели, `visible`, колонки «Posted».

- [ ] **Step 3: Реализация** — `render()` строит `self.visible = freshness.visible_rows(...)` и заполняет
таблицу им; `on_select` берёт `self.visible[i]`; «Found · N (+K)» — по `visible`; изменения поиска и
списков вызывают `render()`; `on_evaluated` больше не сортирует сам (порядок задаёт `visible_rows`).

- [ ] **Step 4: Запустить — должны пройти**

Run: `.venv/Scripts/python -m pytest tests -q`
Expected: PASS.

- [ ] **Step 5: Commit** — `git commit -m "Show job age, reposted jobs and filters above Found"`

---

### Task 4: Описание, оставшееся время, закрытие, «Undo», «похоже, закрыли»

**Files:**
- Modify: `job_finder/window.py`
- Test: `tests/test_window.py`

**Interfaces:**
- Consumes: `db.description`, `db.unhide`, `row["closed"]` из задачи 1; `freshness.time_left_text`.
- Produces: в `MainWindow`: `description_button: QPushButton`, `d_description: QLabel`,
  `refreshing: bool`, `clock` (атрибут класса, по умолчанию `time.monotonic`; тесты подменяют),
  `confirm_close() -> bool` (показывает вопрос; тесты подменяют), `undo_toast: QFrame` (плашка поверх
  окна, внизу по центру над списком), `undo_label: QLabel`, `undo_button: QPushButton` (стиль `primary`),
  `undo_timer: QTimer` (single shot, 10 000 мс), `undo() -> None`,
  `d_closed: QLabel`.

- [ ] **Step 1: Тесты окна**

- `test_description_collapsed_then_shown` — `d_description` скрыт, кнопка «Show description»; клик →
  виден, текст из базы, кнопка «Collapse»; выбор другой строки подставляет её описание.
- `test_progress_shows_time_left` — подменить `MainWindow.clock` на возрастающие значения;
  `on_progress(0, 213)`, затем `on_progress(3, 213)` через 30 «секунд» → статус
  «Evaluated 3 of 213 · ~35 min left»; при `done = 2` — без части про время.
- `test_close_during_refresh_asks` — `refreshing = True`, `confirm_close` → `False`: окно не закрыто
  (`closeEvent` игнорирует событие, `db.mark_all_seen` не вызван); → `True`: закрыто.
- `test_close_without_refresh_does_not_ask` — после `refresh()` и `on_finished()` `confirm_close` не
  вызывается.
- `test_undo_hide` — «Hide» → `undo_toast` виден, `undo_label` «Hidden: Job a»; `undo()` → вакансия снова в
  таблице и выделена; `undo_timer` по `timeout` прячет плашку; второе «Hide» до таймаута
  заменяет `undo` на вторую вакансию; `undo()` для вакансии, отфильтрованной поиском, не падает.
- `test_closed_application_marked` — отклик с `closed = True` (через `db.save_jobs("junior.guru", [])`
  после `apply`): в таблице откликов «⊘ » перед названием; в карточке `d_closed` виден с текстом
  «No longer listed on junior.guru — probably filled»; у отклика Himalayas — не виден.

- [ ] **Step 2: Запустить — должны упасть**

Run: `.venv/Scripts/python -m pytest tests/test_window.py -q`
Expected: FAIL — нет новых атрибутов.

- [ ] **Step 3: Реализация** — по Interfaces; `refreshing` ставится в `refresh()`, снимается в
`on_finished()` (воркер шлёт `finished` всегда); время начала прохода запоминается при `on_progress(0, …)`.

- [ ] **Step 4: Запустить — должны пройти**

Run: `.venv/Scripts/python -m pytest tests -q`
Expected: PASS.

- [ ] **Step 5: Commit** — `git commit -m "Add description, time left, close confirmation, undo and closed marks"`

---

### Task 5: Документация и проверка вживую

**Files:**
- Modify: `README.md` (раздел «What it does» — свежесть одним-двумя пунктами), `docs/how-it-works.ru.md`
  (разделы 6, 8, 9 — возраст, «reposted», фильтры, `first_seen`, `STALE_JOB_DAYS`), `docs/screenshots/found.png`

- [ ] **Step 1:** обновить тексты; число тестов в `docs/how-it-works.ru.md`.
- [ ] **Step 2:** перерисовать `docs/screenshots/found.png` (скрипт скриншотов из scratchpad, на копии
  базы, `QT_QPA_FONTDIR=C:/Windows/Fonts`) и посмотреть: панель, «Posted», ничего не обрезано.
- [ ] **Step 3:** Run: `.venv/Scripts/python -m pytest tests -q` → PASS.
- [ ] **Step 4: Commit** — `git commit -m "Document freshness features"`
