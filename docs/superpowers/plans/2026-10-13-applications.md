# Мои отклики — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Кнопка «Подался» переносит найденную вакансию во вкладку «Мои отклики», где можно отметить итог (приняли / отказали) или вернуть её в найденные; перепубликованные вакансии помечаются «↻ / Вы уже подавались».

**Architecture:** В таблице `jobs` две новые колонки — `status` и `applied_at`; `init()` добавляет их в старую базу. `db.py` получает `apply`, `set_status`, `unapply`, `list_applied`, а найденные и очередь на оценку исключают отклики. В окне — переключатель «Найденные · N | Мои отклики · M» в верхней полосе, вторая таблица в `QStackedWidget` слева и общая карточка справа, у которой кнопки и плашки зависят от того, отклик это или найденная вакансия.

**Tech Stack:** Python 3.11, PySide6, sqlite3, pytest.

**Spec:** `docs/superpowers/specs/2026-10-13-job-finder-design.md` (§1 п. 5, §3 п. 3, §6, §7 «Отклики» и «Уже подавались», §11)

## Global Constraints

- Все команды — в Bash (Git Bash) из корня проекта; Python — `.venv/Scripts/python`.
- Интерфейс только на русском; у всех `QLabel` — `Qt.PlainText`, без HTML.
- Статусы: `'applied'` — «Ждём ответа», `'accepted'` — «Приняли», `'rejected'` — «Отказали»; цвета: синий, зелёный, красный.
- Отклик показывается во вкладке всегда — независимо от `active`, `hidden` и `cv_hash` — и не попадает в очередь на оценку.
- Ключ «та же вакансия» — компания и название без учёта регистра и лишних пробелов, тот же, что при удалении дублей.
- Тесты не трогают настоящие `jobs.db` и `master_cv.md` (только временные пути через `monkeypatch`).
- Каждое сообщение коммита заканчивается строкой `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **Настоящая `jobs.db` создана до откликов** → при первом запуске колонки добавляются, все вакансии и оценки на месте. Тест: `test_init_adds_columns_to_old_database` (задача 1) и ручная проверка с резервной копией (задача 3).
2. **Во время обновления приходит новая найденная вакансия, а в карточке открыт отклик** → карточка остаётся на отклике. Тест: `test_new_found_row_keeps_application_selected` (задача 2).
3. **Переход с отклика или перепубликованной вакансии на обычную найденную** → плашка статуса и жёлтая плашка пропадают, видны кнопки найденной вакансии. Тест: `test_card_extras_reset_between_rows` (задача 2).
4. **«Вернуть в найденные» для вакансии, которая уже пропала с сайта** → исчезает из обоих списков без ошибки. Тест: `test_unapply_gone_job_leaves_both_lists` (задача 1).
5. **Числа на переключателе** после «Подался», смены статуса и возврата совпадают с числом строк. Тесты: проверки текста кнопок в `test_apply_moves_row_to_applications` и `test_status_buttons_and_return` (задача 2).

---

### Task 1: База и ключ «та же вакансия»

**Files:**
- Modify: `job_finder/db.py`, `job_finder/sources.py`
- Test: `tests/test_db.py`, `tests/test_sources.py`

**Interfaces:**
- Consumes: —
- Produces:
  - `sources.same_job_key(company: str, title: str) -> tuple[str, str]`.
  - `db.STATUSES = ("applied", "accepted", "rejected")`.
  - `db.apply(url: str) -> None` — `status='applied'`, `applied_at` = сегодня (`YYYY-MM-DD`).
  - `db.set_status(url: str, status: str) -> None` — дату не меняет.
  - `db.unapply(url: str) -> None` — `status` и `applied_at` → NULL.
  - `db.list_applied() -> list[dict]` — строки вида `db.make_row` плюс ключи `status`, `applied_at`; новые сверху.
  - `list_jobs`, `pending_jobs`, `count_evaluated` исключают вакансии с откликом.

- [ ] **Step 1: Написать падающие тесты в `tests/test_db.py` (дописать в конец)**

```python
def test_apply_moves_job_out_of_found_list():
    db.save_jobs("Jobicy", [job("a"), job("b")])
    db.save_evaluation("a", evaluation(8), "h1")
    db.save_evaluation("b", evaluation(7), "h1")
    db.apply("a")
    assert [row["url"] for row in db.list_jobs("h1", 5)] == ["b"]
    applied = db.list_applied()
    assert [(row["url"], row["status"], row["applied_at"]) for row in applied] == [
        ("a", "applied", date.today().isoformat())]
    assert applied[0]["evaluation"]["score"] == 8
    assert db.count_evaluated("h1") == 1
    assert urls(db.pending_jobs("h2")) == ["b"]  # отклик не оценивается заново даже после смены ключа


def test_application_survives_deactivation_and_new_key():
    db.save_jobs("Jobicy", [job("a"), job("b")])
    db.save_evaluation("a", evaluation(8), "h1")
    db.apply("a")
    db.save_jobs("Jobicy", [job("b")])  # «a» пропала с сайта
    assert [row["url"] for row in db.list_applied()] == ["a"]


def test_set_status_and_unapply():
    db.save_jobs("Jobicy", [job("a")])
    db.save_evaluation("a", evaluation(8), "h1")
    db.apply("a")
    db.set_status("a", "accepted")
    applied = db.list_applied()
    assert (applied[0]["status"], applied[0]["applied_at"]) == ("accepted", date.today().isoformat())
    db.unapply("a")
    assert db.list_applied() == []
    assert [row["url"] for row in db.list_jobs("h1", 5)] == ["a"]


def test_unapply_gone_job_leaves_both_lists():
    db.save_jobs("Jobicy", [job("a")])
    db.save_evaluation("a", evaluation(8), "h1")
    db.apply("a")
    db.save_jobs("Jobicy", [])  # вакансия пропала с сайта
    db.unapply("a")
    assert db.list_applied() == []
    assert db.list_jobs("h1", 5) == []


def test_init_adds_columns_to_old_database(tmp_path, monkeypatch):
    old = tmp_path / "old.db"
    conn = sqlite3.connect(old)
    conn.execute("""CREATE TABLE jobs (url TEXT PRIMARY KEY, source TEXT NOT NULL, title TEXT NOT NULL,
        company TEXT NOT NULL, city TEXT NOT NULL, published TEXT NOT NULL, description TEXT NOT NULL,
        active INTEGER NOT NULL DEFAULT 1, hidden INTEGER NOT NULL DEFAULT 0, score INTEGER, evaluation TEXT,
        cv_hash TEXT)""")
    conn.execute("INSERT INTO jobs VALUES ('a', 'Jobicy', 'Job a', 'ACME', 'Praha', '2026-10-01', 'Python',"
                 " 1, 0, 8, ?, 'h1')", (json.dumps(evaluation(8)),))
    conn.commit()
    conn.close()
    monkeypatch.setattr(config, "DB_PATH", old)
    db.init()
    assert [row["url"] for row in db.list_jobs("h1", 5)] == ["a"]  # данные сохранились
    db.apply("a")
    assert db.list_applied()[0]["status"] == "applied"
```

И в начало файла добавить импорты (после `import pytest`):

```python
import json
import sqlite3
from datetime import date
```

- [ ] **Step 2: Написать падающий тест в `tests/test_sources.py` (дописать в конец)**

```python
def test_same_job_key_ignores_case_and_spaces():
    assert sources.same_job_key(" ACME ", "Python  Dev") == sources.same_job_key("acme", "python dev")
```

- [ ] **Step 3: Убедиться, что тесты падают**

Run: `.venv/Scripts/python -m pytest tests/test_db.py tests/test_sources.py -q`
Expected: 6 FAILED — `AttributeError: module 'job_finder.db' has no attribute 'apply'` / `... 'job_finder.sources' has no attribute 'same_job_key'`; в `test_init_adds_columns_to_old_database` — `no such column: status` или `AttributeError`.

- [ ] **Step 4: `sources.py` — общий ключ «та же вакансия»**

Заменить функцию `dedupe` и добавить перед ней `same_job_key`:

```python
def same_job_key(company: str, title: str) -> tuple[str, str]:
    """Ключ «та же вакансия»: компания и название без учёта регистра и лишних пробелов."""
    return _norm(company), _norm(title)


def dedupe(fetched: dict[str, list[Job]]) -> dict[str, list[Job]]:
    """Убрать повторы по «компания + название»; остаётся запись источника, который раньше в словаре."""
    seen = set()
    result = {}
    for name, jobs in fetched.items():
        result[name] = []
        for job in jobs:
            key = same_job_key(job.company, job.title)
            if key not in seen:
                seen.add(key)
                result[name].append(job)
    return result
```

- [ ] **Step 5: `db.py` — схема, дополнение старой базы, отклики**

В `SCHEMA` заменить последнюю колонку и добавить две новые:

```python
    cv_hash     TEXT,               -- ключ оценки: SHA-256 резюме, модели и правил
    status      TEXT,               -- отклик: NULL, 'applied', 'accepted', 'rejected'
    applied_at  TEXT                -- дата отклика YYYY-MM-DD
```

После `JOB_FIELDS` добавить:

```python
STATUSES = ("applied", "accepted", "rejected")  # ждём ответа, приняли, отказали
```

Добавить импорт `from datetime import date` и заменить `init()`:

```python
def init() -> None:
    with _connect() as conn:
        conn.execute(SCHEMA)
        # База, созданная до появления откликов: добавить новые колонки, вакансии и оценки сохраняются
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(jobs)")}
        for column in ("status", "applied_at"):
            if column not in columns:
                conn.execute(f"ALTER TABLE jobs ADD COLUMN {column} TEXT")
```

В трёх запросах добавить условие `AND status IS NULL`:
- `pending_jobs`: `WHERE active = 1 AND hidden = 0 AND status IS NULL AND (cv_hash IS NULL OR cv_hash != ?)`, докстринг — «Активные нескрытые вакансии без отклика и без оценки по текущему ключу, сначала самые новые.»
- `count_evaluated`: `WHERE active = 1 AND hidden = 0 AND status IS NULL AND cv_hash = ?`
- `list_jobs`: `WHERE active = 1 AND hidden = 0 AND status IS NULL AND cv_hash = ? AND score >= ?`

После `hide()` добавить:

```python
def apply(url: str) -> None:
    """«Подался»: вакансия уходит из найденных в отклики со статусом «ждём ответа» и сегодняшней датой."""
    with _connect() as conn:
        conn.execute("UPDATE jobs SET status = 'applied', applied_at = ? WHERE url = ?",
                     (date.today().isoformat(), url))


def set_status(url: str, status: str) -> None:
    """Итог отклика: один из STATUSES; дата отклика не меняется."""
    with _connect() as conn:
        conn.execute("UPDATE jobs SET status = ? WHERE url = ?", (status, url))


def unapply(url: str) -> None:
    """«Вернуть в найденные»: убрать статус и дату отклика."""
    with _connect() as conn:
        conn.execute("UPDATE jobs SET status = NULL, applied_at = NULL WHERE url = ?", (url,))
```

В конец файла добавить:

```python
def list_applied() -> list[dict]:
    """Отклики для вкладки «Мои отклики»: все, новые сверху, независимо от active, hidden и ключа оценки."""
    with _connect() as conn:
        rows = conn.execute(
            f"""SELECT {JOB_FIELDS}, evaluation, status, applied_at FROM jobs
                WHERE status IS NOT NULL
                ORDER BY applied_at DESC, title""",
        ).fetchall()
    return [
        {**make_row(Job(*tuple(row)[:7]), json.loads(row["evaluation"])),
         "status": row["status"], "applied_at": row["applied_at"]}
        for row in rows
    ]
```

- [ ] **Step 6: Убедиться, что тесты проходят**

Run: `.venv/Scripts/python -m pytest tests -q`
Expected: `52 passed`

- [ ] **Step 7: Commit**

```bash
git add job_finder/db.py job_finder/sources.py tests/test_db.py tests/test_sources.py
git commit -m "Store job applications in the database" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Окно — переключатель, вкладка откликов, кнопки и пометки

**Files:**
- Modify: `job_finder/window.py` (заменить целиком), `job_finder/style.py`
- Test: `tests/test_window.py`

**Interfaces:**
- Consumes: `db.apply / set_status / unapply / list_applied / list_jobs / hide`, `sources.same_job_key`, `style.score_colors`, `read_cv`.
- Produces: в `MainWindow` — `found_tab`, `applied_tab` (кнопки переключателя), `applied_table`, `applied: list[dict]`, `show_tab(index)`, `apply_button`, `accept_button`, `reject_button`, `unapply_button`, `d_status`, `d_notice`; `style.STATUS_COLORS: dict[str, tuple[str, str]]`.

- [ ] **Step 1: Написать падающие тесты в `tests/test_window.py` (дописать в конец)**

```python
def add_found(url, score, title=None, company="ACME"):
    """Найденная вакансия в базе, оценённая по временному резюме из фикстуры."""
    if not config.CV_PATH.exists():
        config.CV_PATH.write_text("## Skills\n- Python — x\n", encoding="utf-8")  # временное резюме
    # Свой источник у каждой вакансии: save_jobs выключает вакансии источника, которых нет в выборке
    job = Job(url=url, source=f"src-{url}", title=title or f"Job {url}", company=company, city="Praha",
              published="2026-10-01", description="")
    db.save_jobs(job.source, [job])
    db.save_evaluation(url, row(url, score)["evaluation"], worker.read_cv()[1])


def applied_titles(w):
    return [w.applied_table.item(i, 1).text() for i in range(w.applied_table.rowCount())]


def test_apply_moves_row_to_applications(window):
    add_found("a", 8)
    add_found("b", 7)
    window.load_rows()
    window.table.selectRow(0)
    window.apply_button.click()
    assert titles(window) == ["Job b"]
    assert applied_titles(window) == ["Job a"]
    assert window.applied_table.item(0, 3).text() == "Ждём ответа"
    assert window.found_tab.text() == "Найденные · 1"
    assert window.applied_tab.text() == "Мои отклики · 1"


def test_status_buttons_and_return(window):
    add_found("a", 8)
    window.load_rows()
    window.table.selectRow(0)
    window.apply_button.click()
    window.show_tab(1)
    window.applied_table.selectRow(0)
    assert not window.accept_button.isHidden() and window.apply_button.isHidden()
    window.accept_button.click()
    assert window.applied_table.item(0, 3).text() == "Приняли"
    assert "Приняли" in window.d_status.text()  # карточка осталась на этом отклике и обновилась
    window.reject_button.click()
    assert window.applied_table.item(0, 3).text() == "Отказали"
    window.unapply_button.click()
    assert applied_titles(window) == []
    assert titles(window) == ["Job a"]
    assert window.applied_tab.text() == "Мои отклики · 0"


def test_repost_marked(window):
    add_found("old", 8, title="Python Dev", company="ACME")
    window.load_rows()
    window.table.selectRow(0)
    window.apply_button.click()
    add_found("new", 7, title="python  dev", company=" acme ")  # та же вакансия с новой ссылкой
    window.load_rows()
    assert titles(window) == ["↻ python  dev"]
    window.table.selectRow(0)
    assert not window.d_notice.isHidden()
    assert "Вы уже подавались" in window.d_notice.text()


def test_card_extras_reset_between_rows(window):
    add_found("old", 8, title="Python Dev")
    add_found("plain", 6, title="Other")
    window.load_rows()
    window.table.selectRow(0)
    window.apply_button.click()
    add_found("new", 7, title="Python Dev")
    window.load_rows()
    window.table.selectRow(0)  # перепубликованная — с жёлтой плашкой
    assert not window.d_notice.isHidden()
    window.table.selectRow(1)  # обычная найденная
    assert window.d_notice.isHidden() and window.d_status.isHidden()
    assert not window.apply_button.isHidden() and window.accept_button.isHidden()


def test_new_found_row_keeps_application_selected(window):
    add_found("a", 8)
    window.load_rows()
    window.table.selectRow(0)
    window.apply_button.click()
    window.show_tab(1)
    window.applied_table.selectRow(0)
    window.on_evaluated(row("fresh", 9))  # фоновое обновление прислало новую найденную вакансию
    assert window.current["url"] == "a"
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `.venv/Scripts/python -m pytest tests/test_window.py -q`
Expected: 5 FAILED — `AttributeError: 'MainWindow' object has no attribute 'apply_button'` (или `applied_table` / `show_tab`).

- [ ] **Step 3: `style.py` — цвета статусов, плашки и переключатель**

В `COLORS` после `"link"` добавить:

```python
    "notice_bg": "#3a2f12",    # жёлтая плашка «Вы уже подавались»
    "notice_text": "#fcd34d",
```

После `LIST_COLORS` добавить:

```python
# Цвета статуса отклика: (фон плашки, цвет текста) — ждём ответа, приняли, отказали
STATUS_COLORS = {"applied": ("#0c4a6e", "#7dd3fc"), "accepted": ("#14532d", "#4ade80"),
                 "rejected": ("#7f1d1d", "#fca5a5")}
```

В `STYLESHEET` после правил `QPushButton#primary…` добавить:

```
QPushButton#segmentLeft, QPushButton#segmentRight {{ background: {panel}; color: {muted}; font-weight: 600;
                                                     border: 1px solid {border}; padding: 6px 14px; }}
QPushButton#segmentLeft {{ border-radius: 0; border-top-left-radius: 6px; border-bottom-left-radius: 6px; }}
QPushButton#segmentRight {{ border-radius: 0; border-top-right-radius: 6px; border-bottom-right-radius: 6px;
                           border-left: none; }}
QPushButton#segmentLeft:checked, QPushButton#segmentRight:checked {{ background: {accent_soft}; color: {text}; }}
QLabel#notice {{ background: {notice_bg}; color: {notice_text}; border-radius: 6px; padding: 8px 12px;
                margin-top: 12px; }}
```

(Жирный шрифт у обоих состояний переключателя — чтобы ширина кнопки не менялась и текст не обрезался.)

- [ ] **Step 4: Заменить `job_finder/window.py` целиком**

```python
"""Главное окно: найденные вакансии и отклики, карточка с разбором выбранной."""
from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView, QButtonGroup, QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel, QMainWindow,
    QProgressBar, QPushButton, QScrollArea, QSplitter, QStackedWidget, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from job_finder import config, db, llm, sources, style
from job_finder.worker import Worker, read_cv

COLUMNS = ["Оценка", "Вакансия", "Компания", "Город", "Дата"]
APPLIED_COLUMNS = ["Отклик", "Вакансия", "Компания", "Статус", "Оценка"]
LISTS = [("have", "ЕСТЬ", "✓"), ("missing", "НЕ ХВАТАЕТ", "✕"), ("risks", "МОЖЕТ ОТСЕЧЬ", "!")]
EMPTY_LIST = {"have": "—", "missing": "Ничего существенного"}
STATUS_TEXT = {"applied": "Ждём ответа", "accepted": "Приняли", "rejected": "Отказали"}
REPOST_MARK = "↻ "  # перед названием найденной вакансии, на которую уже был отклик


def _label(name: str = "") -> QLabel:
    """Подпись с обычным текстом; name — имя для стилей из style.py."""
    label = QLabel()
    label.setObjectName(name)
    label.setTextFormat(Qt.PlainText)  # только обычный текст, без HTML
    label.setWordWrap(True)
    label.setTextInteractionFlags(Qt.TextSelectableByMouse)
    return label


def _caption(text: str) -> QLabel:
    label = _label("section")
    label.setText(text)
    return label


def _make_table(columns: list[str], center: int) -> QTableWidget:
    """Таблица в общем стиле: выбор строки целиком, без сетки; колонка center (оценка) — по центру."""
    table = QTableWidget(0, len(columns))
    table.setHorizontalHeaderLabels(columns)
    table.setSelectionBehavior(QAbstractItemView.SelectRows)
    table.setSelectionMode(QAbstractItemView.SingleSelection)
    table.setEditTriggers(QAbstractItemView.NoEditTriggers)
    table.verticalHeader().hide()
    table.verticalHeader().setDefaultSectionSize(34)
    table.setShowGrid(False)
    table.setAlternatingRowColors(True)
    header = table.horizontalHeader()
    header.setSectionResizeMode(QHeaderView.ResizeToContents)
    header.setSectionResizeMode(1, QHeaderView.Stretch)
    # Заголовки — по тому же краю, что и текст в ячейках
    header.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    table.horizontalHeaderItem(center).setTextAlignment(Qt.AlignCenter)
    return table


def _score_item(score: int) -> QTableWidgetItem:
    """Ячейка оценки: по центру, жирная, цветом по оценке."""
    item = QTableWidgetItem(str(score))
    item.setTextAlignment(Qt.AlignCenter)
    item.setForeground(QColor(style.score_colors(score)[1]))
    font = item.font()
    font.setBold(True)
    item.setFont(font)
    return item


def _fill_table(table: QTableWidget, rows: list[dict], values, selected_url: str | None) -> None:
    """Заполнить таблицу: values(row) — ячейки строки (текст или готовые QTableWidgetItem); выделение по url."""
    table.blockSignals(True)
    table.clearSelection()
    table.setRowCount(len(rows))
    for i, row in enumerate(rows):
        for column, value in enumerate(values(row)):
            table.setItem(i, column, value if isinstance(value, QTableWidgetItem) else QTableWidgetItem(value))
        if row["url"] == selected_url:
            table.selectRow(i)
    table.blockSignals(False)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Подбор вакансий")
        self.resize(1200, 750)
        self.rows: list[dict] = []        # найденные вакансии в порядке показа
        self.applied: list[dict] = []     # отклики, новые сверху
        self.applied_by_key: dict[tuple[str, str], dict] = {}  # последний отклик по «компания + название»
        self.current: dict | None = None  # выбранная строка: найденная вакансия или отклик (есть ключ status)

        self.refresh_button = QPushButton("Обновить")
        self.refresh_button.setObjectName("primary")
        self.refresh_button.clicked.connect(self.refresh)
        self.found_tab = QPushButton()
        self.found_tab.setObjectName("segmentLeft")
        self.applied_tab = QPushButton()
        self.applied_tab.setObjectName("segmentRight")
        self.tabs = QButtonGroup(self)  # переключатель «Найденные | Мои отклики»: нажата ровно одна кнопка
        for index, button in enumerate((self.found_tab, self.applied_tab)):
            button.setCheckable(True)
            self.tabs.addButton(button, index)
        self.found_tab.setChecked(True)
        self.tabs.idClicked.connect(self.show_tab)
        tabs = QHBoxLayout()
        tabs.setSpacing(0)
        tabs.addWidget(self.found_tab)
        tabs.addWidget(self.applied_tab)
        self.status_label = _label()
        self.progress = QProgressBar()
        self.progress.setMaximumWidth(250)
        self.progress.hide()
        self.cv_button = QPushButton("Резюме")
        self.cv_button.clicked.connect(self.show_cv)
        self.cv_window = None  # окно «Резюме» создаётся при первом нажатии
        top = QHBoxLayout()
        top.addWidget(self.refresh_button)
        top.addSpacing(style.GAP)
        top.addLayout(tabs)
        top.addSpacing(style.GAP)
        top.addWidget(self.status_label, 1)
        top.addWidget(self.progress)
        top.addWidget(self.cv_button)

        self.table = _make_table(COLUMNS, 0)
        self.table.itemSelectionChanged.connect(self.on_select)
        self.applied_table = _make_table(APPLIED_COLUMNS, 4)
        self.applied_table.itemSelectionChanged.connect(self.on_select_applied)
        self.lists = QStackedWidget()  # 0 — найденные, 1 — отклики
        self.lists.addWidget(self.table)
        self.lists.addWidget(self.applied_table)

        splitter = QSplitter()
        splitter.setHandleWidth(style.GAP)
        splitter.addWidget(self.lists)
        splitter.addWidget(self._build_details())
        splitter.setSizes([700, 500])

        central = QWidget()
        central.setObjectName("central")
        layout = QVBoxLayout(central)
        layout.setContentsMargins(style.GAP, style.GAP, style.GAP, style.GAP)
        layout.setSpacing(style.GAP)
        layout.addLayout(top)
        layout.addWidget(splitter, 1)
        self.setCentralWidget(central)
        self.setStyleSheet(style.STYLESHEET)

        self.worker = Worker()
        self.worker.status.connect(self.status_label.setText)
        self.worker.progress.connect(self.on_progress)
        self.worker.evaluated.connect(self.on_evaluated)
        self.worker.finished.connect(self.on_finished)

        self.load_rows()
        QTimer.singleShot(0, self.refresh)  # обновление сразу после показа окна

    def _build_details(self) -> QWidget:
        """Карточка деталей: шапка с оценкой, плашки отклика, факты, «почему», списки; кнопки — внизу."""
        self.d_title = _label("title")
        self.d_company = _label("company")
        self.badge = QFrame()
        self.badge.setObjectName("badge")
        self.badge.setFixedSize(64, 64)
        self.badge_number = QLabel(alignment=Qt.AlignCenter)
        self.badge_caption = QLabel("из 10", alignment=Qt.AlignCenter)
        badge_box = QVBoxLayout(self.badge)
        badge_box.setContentsMargins(0, 8, 0, 8)
        badge_box.setSpacing(0)
        badge_box.addWidget(self.badge_number)
        badge_box.addWidget(self.badge_caption)

        names = QVBoxLayout()
        names.setSpacing(4)
        names.addWidget(self.d_title)
        names.addWidget(self.d_company)
        head = QHBoxLayout()
        head.setSpacing(16)
        head.addLayout(names, 1)
        head.addWidget(self.badge, 0, Qt.AlignTop)

        self.d_status = _label()  # плашка «Отклик ГГГГ-ММ-ДД · статус» — только у откликов
        self.d_status.setWordWrap(False)
        self.d_notice = _label("notice")  # «Вы уже подавались…» — только у перепубликованных вакансий

        facts = QGridLayout()
        facts.setHorizontalSpacing(16)
        facts.setVerticalSpacing(6)
        facts.setColumnStretch(1, 1)
        self.facts = {}
        for i, (key, caption) in enumerate([("city", "Город"), ("published", "Опубликовано"),
                                            ("source", "Источник")]):
            name = _label("metaKey")
            name.setText(caption)
            self.facts[key] = _label()
            facts.addWidget(name, i, 0)
            facts.addWidget(self.facts[key], i, 1)

        divider = QFrame()
        divider.setObjectName("divider")
        self.d_summary = _label()

        box = QVBoxLayout()
        box.setContentsMargins(20, 18, 20, 18)
        box.setSpacing(0)
        box.addLayout(head)
        box.addWidget(self.d_status, 0, Qt.AlignLeft)  # отступ сверху — в стиле плашки, у скрытой его нет
        box.addWidget(self.d_notice)
        box.addSpacing(14)
        box.addLayout(facts)
        box.addSpacing(16)
        box.addWidget(divider)
        box.addSpacing(16)
        box.addWidget(_caption("ПОЧЕМУ ТАКАЯ ОЦЕНКА"))
        box.addSpacing(8)
        box.addWidget(self.d_summary)
        self.detail_lists: dict[str, tuple[QLabel, str, QVBoxLayout]] = {}
        for key, caption, _ in LISTS:
            header = _caption(caption)
            rows = QVBoxLayout()
            rows.setSpacing(6)
            box.addSpacing(18)
            box.addWidget(header)
            box.addSpacing(8)
            box.addLayout(rows)
            self.detail_lists[key] = (header, caption, rows)
        box.addStretch(1)

        details = QWidget()
        details.setObjectName("details")
        details.setLayout(box)
        scroll = QScrollArea()
        scroll.setObjectName("detailsScroll")
        scroll.setWidgetResizable(True)
        scroll.setWidget(details)

        self.open_button = QPushButton("Открыть вакансию")
        self.open_button.setObjectName("primary")
        self.open_button.clicked.connect(self.open_job)
        self.apply_button = QPushButton("Подался")
        self.apply_button.clicked.connect(self.apply_job)
        self.hide_button = QPushButton("Скрыть")
        self.hide_button.clicked.connect(self.hide_job)
        self.accept_button = QPushButton("Приняли")
        self.accept_button.clicked.connect(lambda: self.set_status("accepted"))
        self.reject_button = QPushButton("Отказали")
        self.reject_button.clicked.connect(lambda: self.set_status("rejected"))
        self.unapply_button = QPushButton("Вернуть в найденные")
        self.unapply_button.clicked.connect(self.unapply_job)
        self.found_buttons = (self.apply_button, self.hide_button)
        self.applied_buttons = (self.accept_button, self.reject_button, self.unapply_button)
        footer = QWidget()
        footer.setObjectName("footer")
        buttons = QHBoxLayout(footer)
        buttons.setContentsMargins(20, 12, 20, 12)
        buttons.addWidget(self.open_button)
        for button in self.found_buttons + self.applied_buttons:
            buttons.addWidget(button)
        buttons.addStretch(1)

        details_page = QWidget()
        details_page.setObjectName("detailsPage")
        page_box = QVBoxLayout(details_page)
        page_box.setContentsMargins(0, 0, 0, 0)
        page_box.setSpacing(0)
        page_box.addWidget(scroll, 1)
        page_box.addWidget(footer)

        empty_page = QWidget()
        empty_page.setObjectName("emptyPage")
        empty = QLabel("Выберите вакансию в списке слева", alignment=Qt.AlignCenter)
        empty.setObjectName("empty")
        QVBoxLayout(empty_page).addWidget(empty)

        self.pages = QStackedWidget()  # 0 — ничего не выбрано, 1 — разбор вакансии
        self.pages.addWidget(empty_page)
        self.pages.addWidget(details_page)
        card = QFrame()
        card.setObjectName("card")
        card_box = QVBoxLayout(card)
        card_box.setContentsMargins(1, 1, 1, 1)  # не закрывать рамку карточки
        card_box.addWidget(self.pages)
        self.show_details(None)
        return card

    def _fill_list(self, key: str, mark: str, items: list[str]) -> None:
        """Заполнить список «есть / не хватает / может отсечь» строками с цветным значком."""
        header, caption, rows = self.detail_lists[key]
        header.setText(f"{caption} · {len(items)}" if items else caption)
        while rows.count():
            line = rows.takeAt(0).layout()
            while line.count():
                line.takeAt(0).widget().setParent(None)  # убрать из окна сразу, а не после deleteLater
        color = style.LIST_COLORS[key]
        if not items and key == "risks":
            items, mark, color = ["Блокеров не найдено"], "✓", style.LIST_COLORS["have"]
        elif not items:
            items, mark = [EMPTY_LIST[key]], ""
        for text in items:
            marker = QLabel(mark)
            marker.setFixedWidth(14)
            marker.setStyleSheet(f"color: {color}; font-weight: 700;")
            label = _label("" if mark else "muted")
            label.setText(text)
            line = QHBoxLayout()
            line.setSpacing(8)
            line.addWidget(marker, 0, Qt.AlignTop)
            line.addWidget(label, 1)
            rows.addLayout(line)

    def _previous_application(self, row: dict) -> dict | None:
        """Отклик на вакансию с той же компанией и названием (перепубликованная вакансия) или None."""
        return self.applied_by_key.get(sources.same_job_key(row["company"], row["title"]))

    def load_rows(self) -> None:
        """Перечитать из базы найденные (оценки по текущему резюме) и отклики."""
        cv = read_cv()
        self.rows = db.list_jobs(cv[1], config.MIN_SCORE) if cv else []
        self.applied = db.list_applied()
        # reversed: при нескольких откликах с одним ключом остаётся самый новый
        self.applied_by_key = {sources.same_job_key(r["company"], r["title"]): r for r in reversed(self.applied)}
        self.render()
        self.render_applied()

    def render(self) -> None:
        """Перерисовать найденные, сохранив выделение; отклик в карточке не трогать."""
        selected = self.current["url"] if self.current and "status" not in self.current else None

        def values(row):
            mark = REPOST_MARK if self._previous_application(row) else ""
            return [_score_item(row["score"]), mark + row["title"], row["company"], row["city"], row["published"]]

        _fill_table(self.table, self.rows, values, selected)
        self.found_tab.setText(f"Найденные · {len(self.rows)}")
        if selected and selected not in (row["url"] for row in self.rows):
            self.show_details(None)

    def render_applied(self) -> None:
        """Перерисовать отклики, сохранив выделение; найденную вакансию в карточке не трогать."""
        selected = self.current["url"] if self.current and "status" in self.current else None

        def values(row):
            status = QTableWidgetItem(STATUS_TEXT[row["status"]])
            status.setForeground(QColor(style.STATUS_COLORS[row["status"]][1]))
            return [row["applied_at"], row["title"], row["company"], status, _score_item(row["score"])]

        _fill_table(self.applied_table, self.applied, values, selected)
        self.applied_tab.setText(f"Мои отклики · {len(self.applied)}")
        if selected and selected not in (row["url"] for row in self.applied):
            self.show_details(None)

    def show_tab(self, index: int) -> None:
        """Переключить список слева: 0 — найденные, 1 — мои отклики."""
        self.lists.setCurrentIndex(index)
        self.tabs.button(index).setChecked(True)
        for table in (self.table, self.applied_table):
            table.clearSelection()
        self.show_details(None)

    def on_select(self) -> None:
        indexes = self.table.selectionModel().selectedRows()
        self.show_details(self.rows[indexes[0].row()] if indexes else None)

    def on_select_applied(self) -> None:
        indexes = self.applied_table.selectionModel().selectedRows()
        self.show_details(self.applied[indexes[0].row()] if indexes else None)

    def show_details(self, row: dict | None) -> None:
        self.current = row
        self.pages.setCurrentIndex(0 if row is None else 1)
        if row is None:
            return
        evaluation = row["evaluation"]
        background, color = style.score_colors(row["score"])
        self.d_title.setText(row["title"])
        self.d_company.setText(row["company"])
        for key, label in self.facts.items():
            label.setText(row[key])
        self.badge.setStyleSheet(f"QFrame#badge {{ background: {background}; border-radius: 10px; }}")
        self.badge_number.setText(str(row["score"]))
        self.badge_number.setStyleSheet(f"background: transparent; color: {color}; font-size: 20pt;"
                                        " font-weight: 700;")
        self.badge_caption.setStyleSheet(f"background: transparent; color: {color}; font-size: 8pt;")
        self.d_summary.setText(evaluation.get("summary") or "—")
        self.d_summary.setStyleSheet(f"background: {style.COLORS['alt']}; border-left: 3px solid {color};"
                                     " border-radius: 4px; padding: 10px 12px;")
        for key, _, mark in LISTS:
            self._fill_list(key, mark, evaluation.get(key) or [])

        is_application = "status" in row
        self.d_status.setVisible(is_application)
        if is_application:
            status_background, status_color = style.STATUS_COLORS[row["status"]]
            self.d_status.setText(f"Отклик {row['applied_at']} · {STATUS_TEXT[row['status']]}")
            self.d_status.setStyleSheet(f"background: {status_background}; color: {status_color};"
                                        " border-radius: 6px; padding: 6px 12px; font-weight: 600; margin-top: 12px;")
        previous = None if is_application else self._previous_application(row)
        self.d_notice.setVisible(previous is not None)
        if previous:
            self.d_notice.setText(f"Вы уже подавались на «{previous['title']}» в {previous['company']}"
                                  f" {previous['applied_at']} — статус: {STATUS_TEXT[previous['status']].lower()}")
        for button in self.found_buttons:
            button.setVisible(not is_application)
        for button in self.applied_buttons:
            button.setVisible(is_application)

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
        self.load_rows()  # убрать вакансии, которые пропали из источника или отсеяны по месту

    def show_cv(self) -> None:
        """Показать окно «Резюме» с актуальной версией файла; окно одно на всё приложение."""
        # Импорт здесь, а не наверху: cv_window сам берёт _label из этого модуля
        from job_finder.cv_window import CvWindow
        if self.cv_window is None:
            self.cv_window = CvWindow(self)
        self.cv_window.reload()
        self.cv_window.show()
        self.cv_window.raise_()
        self.cv_window.activateWindow()

    def open_job(self) -> None:
        QDesktopServices.openUrl(QUrl(self.current["url"]))

    def hide_job(self) -> None:
        url = self.current["url"]
        db.hide(url)
        self.rows = [row for row in self.rows if row["url"] != url]
        self.show_details(None)
        self.render()

    def apply_job(self) -> None:
        """«Подался»: вакансия уходит из найденных во вкладку «Мои отклики»."""
        db.apply(self.current["url"])
        self.show_details(None)
        self.load_rows()

    def set_status(self, status: str) -> None:
        """Отметить итог отклика; карточка остаётся на этом отклике и показывает новый статус."""
        url = self.current["url"]
        db.set_status(url, status)
        self.load_rows()
        self.show_details(next(row for row in self.applied if row["url"] == url))

    def unapply_job(self) -> None:
        """«Вернуть в найденные» — на случай, если «Подался» нажали по ошибке."""
        db.unapply(self.current["url"])
        self.show_details(None)
        self.load_rows()

    def closeEvent(self, event) -> None:
        if self.worker.model_loaded:
            llm.release(wait=False)  # не ждём: окно должно закрыться сразу
        event.accept()
```

Внимание: словарь списков карточки переименован `self.lists` → `self.detail_lists` (имя `self.lists` теперь у `QStackedWidget` слева). В `tests/test_window.py` заменить обращения `w.lists[key]` / `window.lists[...]` на `w.detail_lists[key]` / `window.detail_lists[...]` (функция `list_texts` и `test_switching_rows_replaces_list_items`).

- [ ] **Step 5: Убедиться, что тесты проходят**

Run: `.venv/Scripts/python -m pytest tests -q`
Expected: `57 passed`

- [ ] **Step 6: Проверить внешний вид скриншотом**

Run (одноразово, вне проекта; снимок настоящего окна, данные не меняются):

```bash
PYTHONUTF8=1 .venv/Scripts/python -X utf8 - "$TMPDIR/applications.png" <<'EOF'
import sys
from PySide6.QtWidgets import QApplication
from job_finder import style, worker
from job_finder.window import MainWindow
worker.Worker.start = lambda self: None
app = QApplication([])
style.apply_app_theme(app)
w = MainWindow()
w.show()
for _ in range(5):
    app.processEvents()
w.grab().save(sys.argv[1])
print("ok")
EOF
```

Expected: переключатель «Найденные · N | Мои отклики · 0» в верхней полосе, текст на кнопках не обрезан, таблица и карточка начинаются на одном уровне.

- [ ] **Step 7: Commit**

```bash
git add job_finder/window.py job_finder/style.py tests/test_window.py
git commit -m "Add the applications tab to the window" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Документация и проверка вживую

**Files:**
- Modify: `docs/guide/01-overview.md`, `docs/guide/03-sources.md`, `docs/guide/06-db.md`, `docs/guide/08-window-and-style.md`, `docs/guide/09-tests.md`, `docs/guide/README.md`

**Interfaces:**
- Consumes: всё из задач 1–2.
- Produces: актуальная `docs/guide`; проверенная работа на настоящей базе.

- [ ] **Step 1: Пересчитать ссылки на строки в `docs/guide`**

Взять версии `job_finder/db.py`, `sources.py`, `window.py`, `style.py` из коммита перед задачей 1 (`git show <база>:job_finder/<файл>.py`) и прогнать скрипт пересчёта ссылок (сопоставление строк через `difflib`, переписывает `#Lx` и номер в тексте ссылки, печатает ссылки, у которых сменилась целевая строка). Ссылки из списка «сменилась целевая строка» поправить вручную по смыслу.

- [ ] **Step 2: Дописать содержание**

- `01-overview.md`: в список «что делает приложение» — пункт про отклики (кнопка «Подался», вкладка «Мои отклики», итог).
- `03-sources.md`: в раздел про `dedupe` — функция `same_job_key` (общий ключ «та же вакансия», им же пользуется окно для пометки «↻»).
- `06-db.md`: колонки `status` и `applied_at` в схеме; дополнение старой базы в `init()` (`PRAGMA table_info` + `ALTER TABLE … ADD COLUMN`); условие `status IS NULL` в `pending_jobs`, `count_evaluated`, `list_jobs`; новые функции `apply`, `set_status`, `unapply`, `list_applied` со ссылками на строки.
- `08-window-and-style.md`: переключатель в верхней полосе (`QButtonGroup`, `show_tab`), две таблицы в `QStackedWidget`, помощники `_make_table`, `_score_item`, `_fill_table`, `render_applied`, `on_select_applied`, плашки `d_status` и `d_notice`, кнопки найденной вакансии и отклика, действия `apply_job`, `set_status`, `unapply_job`; в `style.py` — `STATUS_COLORS`, цвета `notice_*`, правила `segmentLeft/Right` и `notice`; переименование `lists` → `detail_lists`.
- `09-tests.md`: число тестов (57), новые тесты в `test_db.py`, `test_sources.py`, `test_window.py`.
- `README.md`: число строк изменённых модулей (`wc -l job_finder/*.py`) и число тестов.

- [ ] **Step 3: Резервная копия настоящей базы**

Run: `cp jobs.db jobs.db-before-applications && ls -la jobs.db jobs.db-before-applications`
Expected: два файла одного размера (`*.db-*` уже в `.gitignore`).

- [ ] **Step 4: Запустить приложение с ярлыка и проверить дополнение базы**

Run: закрыть открытое окно (`CloseMainWindow` по заголовку «Подбор вакансий»), запустить ярлык, дождаться в `job_finder.log` строки «Готово», затем:

```bash
PYTHONUTF8=1 .venv/Scripts/python -X utf8 -c "import sqlite3; c = sqlite3.connect('jobs.db'); print([r[1] for r in c.execute('PRAGMA table_info(jobs)')][-2:], c.execute('SELECT COUNT(*) FROM jobs WHERE score IS NOT NULL').fetchone()[0])"
```

Expected: `['status', 'applied_at']` и то же число оценённых вакансий, что в резервной копии (то же выражение с `jobs.db-before-applications`).

- [ ] **Step 5: Попросить пользователя проверить вживую**

Попросить: нажать «Подался» на любой вакансии → она пропала из найденных, появилась во вкладке «Мои отклики» со статусом «Ждём ответа»; отметить «Приняли» или «Отказали»; «Вернуть в найденные»; числа на переключателе меняются. После проверки — убедиться в базе, что отметки сохранились (`SELECT title, status, applied_at FROM jobs WHERE status IS NOT NULL`).

- [ ] **Step 6: Commit**

```bash
git add docs/guide
git commit -m "Document the applications tab in the code guide" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```
