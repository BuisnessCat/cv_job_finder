# Трей, автообновление, уведомления, старые вакансии и зарплата — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** раздел 16 спека: не оценивать вакансии старше 30 дней, зарплата в карточке, трей с автообновлением
раз в 3 часа и уведомление о новых вакансиях 7+.

**Architecture:** `worker` отсекает старые вакансии перед оценкой; `sources` разбирает зарплату в новое поле
`Job.salary`, `db` хранит его в колонке `salary`; `window` показывает строку «Salary», держит иконку в трее,
таймер автообновления и уведомление. Проверка «Windows занят» — маленькая функция на ctypes.

**Tech Stack:** Python 3.11, PySide6 (QSystemTrayIcon, QTimer), SQLite, pytest.

**Spec:** `docs/superpowers/specs/2026-10-13-job-finder-design.md`, раздел 16.

## Global Constraints
- `config.OLD_JOB_DAYS = 30`, `config.AUTO_REFRESH_HOURS = 3`, `config.NOTIFY_SCORE = 7`; отложить при «занят» — 15 минут.
- Надписи: «Salary», «Open Job Finder», «Refresh now», «Quit», «N new job(s) with a score of 7+» (1 → «1 new job…»),
  подсказка трея: «Job Finder keeps running in the tray and looks for new jobs every 3 hours. To close it,
  right-click the icon and choose Quit.»
- Ключ оценки и правила не меняются; сигналы Qt — к методам, не к `lambda` с `self`; без кириллицы в коде и тестах.
- Тесты: `.venv/Scripts/python -m pytest tests -q`, код выхода 0. Коммит с `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus
1. Окно спрятано в трей, а обновление ещё идёт — процесс не закрывается, модель выгружается в конце обновления.
2. «Quit» из трея во время обновления — тот же вопрос, что раньше при закрытии; «Cancel» оставляет всё как было.
3. Зарплата строкой/числом/с дробью или с одной границей — без падения.
4. Старая база без колонки `salary` — открывается, отклики и оценки на месте.
5. Уведомление не приходит, пока окно активно, и не приходит за переоценку уже виденных.

---

### Task 1: Старые вакансии и зарплата
**Files:** `job_finder/config.py`, `job_finder/worker.py`, `job_finder/sources.py`, `job_finder/db.py`,
`job_finder/window.py`; tests `test_worker.py`, `test_sources.py`, `test_db.py` (или где проверяется миграция), `test_window.py`.
**Interfaces:** `Job.salary: str = ""` (последнее поле); `sources.salary_text(low, high, currency, period) -> str`;
колонка `salary` в `JOB_FIELDS`; строка `self.facts["salary"]` (скрыта без зарплаты).
- [ ] Тесты: `test_old_jobs_are_not_scored`; `test_salary_text`; `test_parsers_read_salary`; `test_salary_column_added_to_old_db`;
  `test_card_shows_salary_only_when_known`. Run — FAIL. Реализация. Run — PASS, код 0.
- [ ] Commit `Skip scoring jobs older than 30 days; salary in the card`.

### Task 2: Трей и автообновление
**Files:** `job_finder/window.py`, новый `job_finder/busy.py` (`windows_busy() -> bool` через
`SHQueryUserNotificationState`: 2, 3, 4 — занят; не Windows или ошибка — не занят); `job_finder/__main__.py` при необходимости.
**Interfaces:** `MainWindow.tray_available` (staticmethod, тесты подменяют), `MainWindow.tray: QSystemTrayIcon | None`,
`auto_refresh()`, `quit_app()`, `show_window()`.
- [ ] Тесты: `test_close_hides_to_tray_and_marks_seen`; `test_close_without_tray_quits`; `test_quit_closes_for_real`;
  `test_auto_refresh_skips_busy_and_running`. Run — FAIL. Реализация. Run — PASS, код 0.
- [ ] Commit `Tray icon, close to tray, refresh every 3 hours`.

### Task 3: Уведомления и документация
**Files:** `job_finder/window.py`, `README.md`, `docs/how-it-works.ru.md`; tests `test_window.py`.
- [ ] Тесты: `test_notification_for_new_good_jobs_when_window_inactive` (7+ новые → сообщение; окно активно → нет;
  уже виденные → нет; 1 → «1 new job»). Run — FAIL. Реализация, README («What it does», «First start» — трей) и
  how-it-works (окно, частые вопросы). Run — PASS, код 0.
- [ ] Commit `Notify about new jobs scored 7+; docs`.

Затем — ревью свежим ревьюером, исправления; слияние и push — после проверки автором.
