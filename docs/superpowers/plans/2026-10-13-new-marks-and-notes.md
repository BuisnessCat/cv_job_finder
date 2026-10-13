# Новые вакансии, заметки и «дней без ответа» — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Помечать вакансии, появившиеся с прошлого закрытия окна; дать откликам заметки, колонку «Ждём, дн.» с подсветкой после 14 дней и кнопки только других статусов.

**Architecture:** В `jobs` две новые колонки: `seen` (0 — новая) и `notes`. `init()` добавляет их в старую базу и отмечает имевшиеся вакансии просмотренными; закрытие окна отмечает просмотренными все. Окно держит множество непросмотренных `url` (перечитывается при загрузке и при каждой свежей оценке), считает дни ожидания чистыми функциями и сохраняет заметку с задержкой 0,5 с, а также при смене строки и закрытии.

**Tech Stack:** Python 3.11, PySide6, sqlite3, pytest.

**Spec:** `docs/superpowers/specs/2026-10-13-job-finder-design.md` (§1 п. 5–6, §6 «Новые вакансии», §7 «Сколько ждём», «Заметки», «Новые», «Закрытие окна», §11)

## Global Constraints

- Все команды — в Bash (Git Bash) из корня проекта; Python — `.venv/Scripts/python`.
- Работа — на ветке `new-marks-and-notes` от `main` (в основной папке проекта, как раньше).
- Интерфейс только на русском; у `QLabel` — `Qt.PlainText`; заметки — `QPlainTextEdit` (обычный текст).
- `STALE_DAYS = 14` в `config.py`; подсветка, когда дней **больше** 14.
- Пометка новой вакансии: `"• "` перед названием и жирный шрифт; на переключателе `«Найденные · N (+K)»`, без `(+0)`.
- Кнопки статусов в карточке отклика — только те из «Ждём ответа», «Приняли», «Отказали», что отличаются от текущего.
- Тесты не трогают настоящие `jobs.db` и `master_cv.md`.
- Каждое сообщение коммита заканчивается строкой `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **Настоящая `jobs.db` без `notes`/`seen`** → колонки добавляются, все имевшиеся вакансии просмотрены (список не «засвечивается»), новые строки — непросмотренные. Тест: `test_init_marks_existing_rows_seen` (задача 1) и ручная проверка с резервной копией (задача 3).
2. **Заметку набрали и сразу закрыли окно / переключились на другую строку / сменили статус — раньше, чем сработала задержка** → текст сохранён. Тесты: `test_notes_saved_on_row_switch`, `test_close_saves_notes_and_marks_seen` (задача 2).
3. **Вакансия пришла во время обновления (после загрузки списка)** → помечена «•». Тест: `test_job_arriving_during_refresh_is_marked` (задача 2).
4. **Отклик ждал > 14 дней, потом отмечен «Отказали»** → янтарная плашка и подсказка пропадают. Тест: в `test_waiting_days_and_stale_highlight` (задача 2).
5. **У решённых откликов (приняли / отказали)** в колонке «Ждём, дн.» стоит «—» без подсветки. Тест: в `test_waiting_days_and_stale_highlight` (задача 2).

---

### Task 1: База и порог

**Files:**
- Modify: `job_finder/db.py`, `job_finder/config.py`
- Test: `tests/test_db.py`

**Interfaces:**
- Consumes: —
- Produces:
  - `config.STALE_DAYS = 14`.
  - Колонки `notes TEXT`, `seen INTEGER NOT NULL DEFAULT 0`.
  - `db.mark_all_seen() -> None`, `db.unseen_urls() -> set[str]`, `db.set_notes(url: str, notes: str) -> None`.
  - `db.list_applied()` — у каждой строки ключ `notes` (строка, пустая, если заметки нет).

- [ ] **Step 0: Ветка**

Run: `git switch -c new-marks-and-notes`
Expected: `Switched to a new branch 'new-marks-and-notes'`

- [ ] **Step 1: Написать падающие тесты в `tests/test_db.py` (дописать в конец)**

```python
def test_new_rows_are_unseen_until_marked():
    db.save_jobs("Jobicy", [job("a"), job("b")])
    assert db.unseen_urls() == {"a", "b"}
    db.mark_all_seen()
    assert db.unseen_urls() == set()
    db.save_jobs("Jobicy", [job("a"), job("c")])  # «a» уже была — остаётся просмотренной
    assert db.unseen_urls() == {"c"}


def test_init_marks_existing_rows_seen(tmp_path, monkeypatch):
    old = tmp_path / "old.db"
    conn = sqlite3.connect(old)
    conn.execute("""CREATE TABLE jobs (url TEXT PRIMARY KEY, source TEXT NOT NULL, title TEXT NOT NULL,
        company TEXT NOT NULL, city TEXT NOT NULL, published TEXT NOT NULL, description TEXT NOT NULL,
        active INTEGER NOT NULL DEFAULT 1, hidden INTEGER NOT NULL DEFAULT 0, score INTEGER, evaluation TEXT,
        cv_hash TEXT, status TEXT, applied_at TEXT)""")
    conn.execute("INSERT INTO jobs (url, source, title, company, city, published, description, score, evaluation,"
                 " cv_hash) VALUES ('a', 'Jobicy', 'Job a', 'ACME', 'Praha', '2026-10-01', 'Python', 8, ?, 'h1')",
                 (json.dumps(evaluation(8)),))
    conn.commit()
    conn.close()
    monkeypatch.setattr(config, "DB_PATH", old)
    db.init()
    assert db.unseen_urls() == set()  # имевшиеся вакансии не «засвечиваются» новыми
    assert [row["url"] for row in db.list_jobs("h1", 5)] == ["a"]
    db.save_jobs("Jobicy", [job("a"), job("b")])
    assert db.unseen_urls() == {"b"}


def test_notes_saved_and_listed():
    db.save_jobs("Jobicy", [job("a")])
    db.save_evaluation("a", evaluation(8), "h1")
    db.apply("a")
    assert db.list_applied()[0]["notes"] == ""
    db.set_notes("a", "Писал HR 30.09")
    assert db.list_applied()[0]["notes"] == "Писал HR 30.09"
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `.venv/Scripts/python -m pytest tests/test_db.py -q`
Expected: 3 FAILED — `AttributeError: module 'job_finder.db' has no attribute 'unseen_urls'` / `'set_notes'`.

- [ ] **Step 3: `config.py` — порог**

После `MIN_SCORE = 5` добавить:

```python

# Отклик без ответа дольше этого числа дней подсвечивается: пора напомнить о себе или закрыть
STALE_DAYS = 14
```

- [ ] **Step 4: `db.py` — колонки, дополнение старой базы, функции**

В `SCHEMA` заменить строку `applied_at` и добавить две колонки:

```python
    applied_at  TEXT,               -- дата отклика YYYY-MM-DD
    notes       TEXT,               -- заметка к отклику
    seen        INTEGER NOT NULL DEFAULT 0  -- 0 — появилась после прошлого закрытия окна (новая)
```

Заменить `init()`:

```python
def init() -> None:
    with _connect() as conn:
        conn.execute(SCHEMA)
        # База, созданная до новых колонок: добавить недостающие, вакансии и оценки сохраняются
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(jobs)")}
        for column in ("status", "applied_at", "notes"):
            if column not in columns:
                conn.execute(f"ALTER TABLE jobs ADD COLUMN {column} TEXT")
        if "seen" not in columns:
            conn.execute("ALTER TABLE jobs ADD COLUMN seen INTEGER NOT NULL DEFAULT 0")
            conn.execute("UPDATE jobs SET seen = 1")  # имевшиеся вакансии — уже просмотренные, не новые
```

После `unapply()` добавить:

```python
def set_notes(url: str, notes: str) -> None:
    """Заметка к отклику: с кем общались, когда собеседование."""
    with _connect() as conn:
        conn.execute("UPDATE jobs SET notes = ? WHERE url = ?", (notes, url))


def mark_all_seen() -> None:
    """Отметить все вакансии просмотренными (при закрытии окна): новыми станут только пришедшие потом."""
    with _connect() as conn:
        conn.execute("UPDATE jobs SET seen = 1 WHERE seen = 0")


def unseen_urls() -> set[str]:
    """url вакансий, появившихся после прошлого закрытия окна."""
    with _connect() as conn:
        return {row["url"] for row in conn.execute("SELECT url FROM jobs WHERE seen = 0")}
```

В `list_applied()` заменить запрос и сборку строки:

```python
        rows = conn.execute(
            f"""SELECT {JOB_FIELDS}, evaluation, status, applied_at, notes FROM jobs
                WHERE status IS NOT NULL
                ORDER BY applied_at DESC, title""",
        ).fetchall()
    return [
        {**make_row(Job(*tuple(row)[:7]), json.loads(row["evaluation"])),
         "status": row["status"], "applied_at": row["applied_at"], "notes": row["notes"] or ""}
        for row in rows
    ]
```

- [ ] **Step 5: Убедиться, что тесты проходят**

Run: `.venv/Scripts/python -m pytest tests -q`
Expected: `60 passed`

- [ ] **Step 6: Commit**

```bash
git add job_finder/db.py job_finder/config.py tests/test_db.py
git commit -m "Store seen marks and application notes" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Окно — пометка новых, «Ждём, дн.», заметки, кнопки статусов

**Files:**
- Modify: `job_finder/window.py`, `job_finder/style.py`
- Test: `tests/test_window.py`

**Interfaces:**
- Consumes: `db.unseen_urls / mark_all_seen / set_notes / list_applied (ключ notes)`, `config.STALE_DAYS`, `style.COLORS["notice_bg"/"notice_text"]`.
- Produces: в `window` — `days_waiting(applied_at: str, today: date) -> int`, `plural_days(n: int) -> str`, `NEW_MARK = "• "`; в `MainWindow` — `new_urls: set[str]`, `waiting_button`, `status_buttons: dict[str, QPushButton]`, `d_stale`, `notes_box`, `notes` (`QPlainTextEdit`), `notes_timer`, `save_notes()`.

- [ ] **Step 1: Поправить существующие тесты под пометку «новое»**

В `tests/test_window.py`:

1. Импорты вверху файла: сразу после `import os` добавить `import sqlite3` и `from datetime import date, timedelta`; строку `from job_finder.window import MainWindow` заменить на `from job_finder.window import MainWindow, days_waiting, plural_days`.
2. Заменить помощник `add_found` — по умолчанию вакансия уже просмотрена, `new=True` оставляет её новой:

```python
def add_found(url, score, title=None, company="ACME", new=False):
    """Найденная вакансия в базе, оценённая по временному резюме из фикстуры; new=False — уже просмотрена."""
    if not config.CV_PATH.exists():
        config.CV_PATH.write_text("## Skills\n- Python — x\n", encoding="utf-8")  # временное резюме
    # Свой источник у каждой вакансии: save_jobs выключает вакансии источника, которых нет в выборке
    job = Job(url=url, source=f"src-{url}", title=title or f"Job {url}", company=company, city="Praha",
              published="2026-10-01", description="")
    db.save_jobs(job.source, [job])
    db.save_evaluation(url, row(url, score)["evaluation"], worker.read_cv()[1])
    if not new:
        with sqlite3.connect(config.DB_PATH) as conn:
            conn.execute("UPDATE jobs SET seen = 1 WHERE url = ?", (url,))
```

3. В `test_finished_reloads_rows_from_db` после `db.save_evaluation("a", …)` добавить `db.mark_all_seen()` (тест про перечитывание, а не про пометку).

- [ ] **Step 2: Написать падающие тесты (дописать в конец `tests/test_window.py`)**

```python
def set_applied_at(url, days_ago):
    with sqlite3.connect(config.DB_PATH) as conn:
        conn.execute("UPDATE jobs SET applied_at = ? WHERE url = ?",
                     ((date.today() - timedelta(days=days_ago)).isoformat(), url))


def test_days_waiting_and_plural():
    assert days_waiting("2026-09-22", date(2026, 10, 13)) == 21
    assert [plural_days(n) for n in (0, 1, 2, 5, 11, 12, 21, 22, 25, 101, 111)] == [
        "0 дней", "1 день", "2 дня", "5 дней", "11 дней", "12 дней", "21 день", "22 дня", "25 дней",
        "101 день", "111 дней"]


def test_new_rows_marked_and_counted(window):
    add_found("a", 8, new=True)
    add_found("b", 7)
    window.load_rows()
    assert titles(window) == ["• Job a", "Job b"]
    assert window.table.item(0, 1).font().bold() and not window.table.item(1, 1).font().bold()
    assert window.found_tab.text() == "Найденные · 2 (+1)"


def test_job_arriving_during_refresh_is_marked(window):
    window.load_rows()
    add_found("x", 9, new=True)  # фоновое обновление записало новую вакансию уже после загрузки списка
    window.on_evaluated(row("x", 9))
    assert titles(window) == ["• Job x"]


def test_status_buttons_show_only_other_statuses(window):
    add_found("a", 8)
    window.load_rows()
    window.table.selectRow(0)
    window.apply_button.click()
    window.show_tab(1)
    window.applied_table.selectRow(0)
    visible = lambda: {s for s, b in window.status_buttons.items() if not b.isHidden()}
    assert visible() == {"accepted", "rejected"}
    window.reject_button.click()
    assert visible() == {"applied", "accepted"}
    window.waiting_button.click()
    assert window.applied_table.item(0, 3).text() == "Ждём ответа"
    assert visible() == {"accepted", "rejected"}


def test_waiting_days_and_stale_highlight(window):
    add_found("old", 8)
    add_found("fresh", 7)
    add_found("done", 6)
    for url in ("old", "fresh", "done"):
        db.apply(url)
    set_applied_at("old", 20)
    set_applied_at("fresh", 3)
    set_applied_at("done", 30)
    db.set_status("done", "rejected")
    window.load_rows()
    cells = {window.applied_table.item(i, 1).text(): window.applied_table.item(i, 4)
             for i in range(window.applied_table.rowCount())}
    assert cells["Job old"].text() == "20"
    assert cells["Job old"].foreground().color().name() == style.COLORS["notice_text"]
    assert cells["Job fresh"].text() == "3"
    assert cells["Job fresh"].foreground().color().name() != style.COLORS["notice_text"]
    assert cells["Job done"].text() == "—"
    window.show_tab(1)
    old_row = [r["url"] for r in window.applied].index("old")
    window.applied_table.selectRow(old_row)
    assert "20 дней" in window.d_status.text() and not window.d_stale.isHidden()
    window.reject_button.click()  # итог пришёл — подсказка больше не нужна
    assert window.d_stale.isHidden() and "дн" not in window.d_status.text()


def test_notes_saved_on_row_switch(window):
    add_found("a", 8)
    add_found("b", 7)
    for url in ("a", "b"):
        db.apply(url)
    window.load_rows()
    window.show_tab(1)
    index = {r["url"]: i for i, r in enumerate(window.applied)}
    window.applied_table.selectRow(index["a"])
    assert not window.notes_box.isHidden()
    window.notes.setPlainText("Писал HR 30.09")
    window.applied_table.selectRow(index["b"])  # раньше, чем сработала задержка сохранения
    assert {r["url"]: r["notes"] for r in db.list_applied()}["a"] == "Писал HR 30.09"
    assert window.notes.toPlainText() == ""
    window.applied_table.selectRow(index["a"])
    assert window.notes.toPlainText() == "Писал HR 30.09"


def test_close_saves_notes_and_marks_seen(window):
    add_found("a", 8)
    add_found("n", 7, new=True)
    db.apply("a")
    window.load_rows()
    window.show_tab(1)
    window.applied_table.selectRow(0)
    window.notes.setPlainText("Собеседование в пятницу")
    window.show()
    window.close()
    assert db.list_applied()[0]["notes"] == "Собеседование в пятницу"
    assert db.unseen_urls() == set()
```

- [ ] **Step 3: Убедиться, что новые тесты падают, а старые — нет**

Run: `.venv/Scripts/python -m pytest tests/test_window.py -q`
Expected: ошибка сбора `ImportError: cannot import name 'days_waiting' from 'job_finder.window'` — новых функций ещё нет.

- [ ] **Step 4: `style.py` — стиль поля заметок и подсказки**

В `STYLESHEET` после правила `QLabel#notice …` добавить:

```
QLabel#staleHint {{ color: {notice_text}; margin-top: 6px; }}
QPlainTextEdit#notes {{ background: {alt}; border: 1px solid {border}; border-radius: 6px; padding: 6px;
                       selection-background-color: {accent_soft}; }}
```

- [ ] **Step 5: `window.py` — изменения**

1. Импорты: добавить `from datetime import date`; в список `QtWidgets` — `QPlainTextEdit`.
2. Константы:

```python
APPLIED_COLUMNS = ["Отклик", "Вакансия", "Компания", "Статус", "Ждём, дн.", "Оценка"]
NEW_MARK = "• "  # перед названием вакансии, появившейся после прошлого закрытия окна
```

3. После `_fill_table` добавить чистые функции:

```python
def days_waiting(applied_at: str, today: date) -> int:
    """Сколько дней прошло с отклика."""
    return (today - date.fromisoformat(applied_at)).days


def plural_days(n: int) -> str:
    """«1 день», «3 дня», «11 дней»."""
    if n % 10 == 1 and n % 100 != 11:
        word = "день"
    elif n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        word = "дня"
    else:
        word = "дней"
    return f"{n} {word}"
```

4. В `__init__`: после `self.applied_by_key …` добавить `self.new_urls: set[str] = set()  # непросмотренные: появились после прошлого закрытия окна`; таблицу откликов создавать как `_make_table(APPLIED_COLUMNS, 5)`.

5. В `_build_details()` после создания `self.d_notice` добавить:

```python
        self.d_stale = _label("staleHint")  # «Больше N дней без ответа…» — под плашкой отклика
        self.d_stale.setText(f"Больше {config.STALE_DAYS} дней без ответа — пора напомнить о себе"
                             " или закрыть отклик")
        self.notes = QPlainTextEdit()  # заметка к отклику, сохраняется сама
        self.notes.setObjectName("notes")
        self.notes.setFixedHeight(70)
        self.notes.setPlaceholderText("С кем общались, когда собеседование…")
        self.notes_url: str | None = None  # отклик, к которому относится текст в поле
        self.notes_timer = QTimer(self)  # сохранить через 0,5 с после последнего нажатия клавиши
        self.notes_timer.setSingleShot(True)
        self.notes_timer.setInterval(500)
        self.notes_timer.timeout.connect(self.save_notes)
        self.notes.textChanged.connect(self.notes_timer.start)
        self.notes_box = QWidget()
        notes_layout = QVBoxLayout(self.notes_box)
        notes_layout.setContentsMargins(0, 14, 0, 0)
        notes_layout.setSpacing(8)
        notes_layout.addWidget(_caption("ЗАМЕТКИ"))
        notes_layout.addWidget(self.notes)
```

и в компоновке `box` заменить строки после `box.addWidget(self.d_status, 0, Qt.AlignLeft)`:

```python
        box.addWidget(self.d_status, 0, Qt.AlignLeft)  # отступ сверху — в стиле плашки, у скрытой его нет
        box.addWidget(self.d_stale)
        box.addWidget(self.notes_box)
        box.addWidget(self.d_notice)
```

Кнопки: после `self.hide_button …` и перед `self.accept_button` добавить `self.waiting_button = QPushButton("Ждём ответа")` с `clicked → lambda: self.set_status("applied")`; заменить наборы:

```python
        self.status_buttons = {"applied": self.waiting_button, "accepted": self.accept_button,
                               "rejected": self.reject_button}
        self.found_buttons = (self.apply_button, self.hide_button)
        self.applied_buttons = (self.waiting_button, self.accept_button, self.reject_button, self.unapply_button)
```

и рядом со скрытием кнопок отклика при создании добавить `self.d_stale.hide()` и `self.notes_box.hide()`.

6. `load_rows()`: перед `self.render()` добавить `self.new_urls = db.unseen_urls()`.

7. `render()` — заменить `values` и подпись переключателя:

```python
        def values(row):
            title = (REPOST_MARK if self._previous_application(row) else "") + row["title"]
            title_item = QTableWidgetItem(title)
            if row["url"] in self.new_urls:
                title_item.setText(NEW_MARK + title)
                font = title_item.font()
                font.setBold(True)
                title_item.setFont(font)
            return [_score_item(row["score"]), title_item, row["company"], row["city"], row["published"]]

        _fill_table(self.table, self.rows, values, selected)
        new = sum(1 for row in self.rows if row["url"] in self.new_urls)
        self.found_tab.setText(f"Найденные · {len(self.rows)}" + (f" (+{new})" if new else ""))
```

8. `render_applied()` — заменить `values`:

```python
        today = date.today()

        def values(row):
            status = QTableWidgetItem(STATUS_TEXT[row["status"]])
            status.setForeground(QColor(style.STATUS_COLORS[row["status"]][1]))
            waiting = QTableWidgetItem("—")
            if row["status"] == "applied":
                days = days_waiting(row["applied_at"], today)
                waiting.setText(str(days))
                if days > config.STALE_DAYS:
                    waiting.setForeground(QColor(style.COLORS["notice_text"]))
            return [row["applied_at"], row["title"], row["company"], status, waiting, _score_item(row["score"])]
```

9. `show_details(row)`: первой строкой добавить `self.save_notes()  # не потерять заметку прошлого отклика`; заменить блок «отклик или найденная» (от `is_application = "status" in row` до конца метода):

```python
        is_application = "status" in row
        self.d_status.setVisible(is_application)
        self.notes_box.setVisible(is_application)
        stale = False
        if is_application:
            text = f"Отклик {row['applied_at']} · {STATUS_TEXT[row['status']]}"
            pill_background, pill_color = style.STATUS_COLORS[row["status"]]
            if row["status"] == "applied":
                days = days_waiting(row["applied_at"], date.today())
                text += f" · {plural_days(days)}"
                stale = days > config.STALE_DAYS
                if stale:
                    pill_background, pill_color = style.COLORS["notice_bg"], style.COLORS["notice_text"]
            self.d_status.setText(text)
            self.d_status.setStyleSheet(f"background: {pill_background}; color: {pill_color};"
                                        " border-radius: 6px; padding: 6px 12px; font-weight: 600; margin-top: 12px;")
            self.notes_url = row["url"]
            self.notes.blockSignals(True)  # подстановка текста — не правка, таймер сохранения не нужен
            self.notes.setPlainText(row["notes"])
            self.notes.blockSignals(False)
        else:
            self.notes_url = None
        self.d_stale.setVisible(stale)
        previous = None if is_application else self._previous_application(row)
        self.d_notice.setVisible(previous is not None)
        if previous:
            self.d_notice.setText(f"Вы уже подавались на «{previous['title']}» в {previous['company']}"
                                  f" {previous['applied_at']} — статус: {STATUS_TEXT[previous['status']].lower()}")
        for button in self.found_buttons:
            button.setVisible(not is_application)
        self.unapply_button.setVisible(is_application)
        for status, button in self.status_buttons.items():
            button.setVisible(is_application and status != row["status"])
```

И в ветке `if row is None:` перед `return` ничего не меняется (`save_notes()` уже вызван первой строкой; `notes_url` сбросить): заменить на

```python
        if row is None:
            self.notes_url = None
            return
```

10. `on_evaluated(row)`: перед `self.render()` добавить `self.new_urls = db.unseen_urls()  # вакансия могла появиться в базе уже после загрузки списка`.

11. Новый метод (после `unapply_job`):

```python
    def save_notes(self) -> None:
        """Записать заметку отклика, открытого в карточке, если текст менялся."""
        self.notes_timer.stop()
        if self.notes_url is None:
            return
        row = next((r for r in self.applied if r["url"] == self.notes_url), None)
        text = self.notes.toPlainText()
        if row is None or row["notes"] == text:
            return
        db.set_notes(self.notes_url, text)
        row["notes"] = text
```

12. `closeEvent`: в начало добавить

```python
        self.save_notes()
        db.mark_all_seen()  # при следующем запуске новыми будут только вакансии, пришедшие после этого
```

- [ ] **Step 6: Убедиться, что тесты проходят**

Run: `.venv/Scripts/python -m pytest tests -q`
Expected: `67 passed`

- [ ] **Step 7: Скриншот на копии базы**

Скопировать `jobs.db` во временную папку, указать её в `config.DB_PATH`, выполнить `db.init()`, отметить пару вакансий непросмотренными и пару откликов с разной давностью, снять `grab()` найденных и откликов (как в предыдущих планах). Expected: «•» и «(+N)» видны, колонка «Ждём, дн.» не обрезана, янтарная плашка и поле заметок на месте, таблица и карточка на одном уровне.

- [ ] **Step 8: Commit**

```bash
git add job_finder/window.py job_finder/style.py tests/test_window.py
git commit -m "Mark new jobs and add notes and waiting days to applications" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Документация и проверка вживую

**Files:**
- Modify: `docs/guide/01-overview.md`, `02-startup-and-config.md`, `06-db.md`, `08-window-and-style.md`, `09-tests.md`, `README.md`

**Interfaces:**
- Consumes: всё из задач 1–2.
- Produces: актуальная `docs/guide`; проверенная работа на настоящей базе.

- [ ] **Step 1: Пересчитать ссылки на строки**

Версии `db.py`, `config.py`, `window.py`, `style.py` из коммита перед задачей 1 → скрипт пересчёта ссылок; ссылки со сменившейся целью поправить вручную; затем проверить все ссылки (`start ≤ длина файла`, число в тексте = якорю).

- [ ] **Step 2: Дописать содержание**

- `01-overview.md`: в список возможностей — пометка новых; в жизненный цикл — `seen` (новая → просмотрена при закрытии окна); заметки и «Ждём, дн.» у откликов.
- `02-startup-and-config.md`: `STALE_DAYS`.
- `06-db.md`: колонки `notes`, `seen` в таблице колонок и схеме; дополнение старой базы (`seen` → `UPDATE jobs SET seen = 1`); функции `set_notes`, `mark_all_seen`, `unseen_urls`; ключ `notes` в `list_applied`.
- `08-window-and-style.md`: `NEW_MARK`, `days_waiting`, `plural_days`; `new_urls` в состоянии окна; колонка «Ждём, дн.»; `d_stale`, `notes_box`/`notes`/`notes_timer`, `save_notes`; кнопки статусов (`status_buttons`); `closeEvent` (заметка + `mark_all_seen`); стили `staleHint`, `notes`.
- `09-tests.md`: число тестов (67) и новые тесты.
- `README.md`: число строк изменённых модулей, число тестов.

- [ ] **Step 3: Резервная копия настоящей базы**

Run: `cp jobs.db jobs.db-before-notes && ls -la jobs.db jobs.db-before-notes`
Expected: два файла одного размера (`*.db-*` в `.gitignore`).

- [ ] **Step 4: Запуск с ярлыка и проверка дополнения базы**

Закрыть окно, запустить ярлык, дождаться «Готово» в логе, затем:

```bash
PYTHONUTF8=1 .venv/Scripts/python -X utf8 -c "import sqlite3; c = sqlite3.connect('jobs.db'); print([r[1] for r in c.execute('PRAGMA table_info(jobs)')][-2:], c.execute('SELECT COUNT(*) FROM jobs WHERE score IS NOT NULL').fetchone()[0], c.execute('SELECT COUNT(*) FROM jobs WHERE seen = 0').fetchone()[0])"
```

Expected: `['notes', 'seen']`, то же число оценённых, что в копии; непросмотренных — только вакансии, пришедшие в этом обновлении (0 или несколько).

- [ ] **Step 5: Попросить пользователя проверить вживую**

Новые вакансии отмечены «•» и «(+N)» (если пришли); заметка к отклику сохраняется и видна после перезапуска; у отклика видны кнопки только других статусов; «Ждём, дн.» показывает дни.

- [ ] **Step 6: Commit**

```bash
git add docs/guide
git commit -m "Document new-job marks, notes and waiting days in the code guide" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```
