# Доводка настроек — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** исправить семь отложенных мелочей из ревью настроек (утверждены автором в чате 2026-10-18).

**Architecture:** точечные правки в `settings.py` (поиск навыков в резюме, канонические имена), `settings_window.py`
(пороги, повторный выбор резюме, «Still needed»), `sources.py` + `window.py` (пометка «вероятно, закрыта», окно
«My CV»). Правила оценки не меняются — переоценки не будет.

**Tech Stack:** Python 3.11, PySide6, pytest.

**Spec:** `docs/superpowers/specs/2026-10-13-job-finder-design.md`, раздел 15 и 14 (пометка о закрытых);
поведение ниже — из сообщения, утверждённого автором.

## Global Constraints

- Ключ оценки и текст правил не меняются (`llm.render_rules` не трогаем).
- Поиск в вакансиях (`insights`, `skills.matches`) не меняется: новые правила распознавания — только для резюме.
- Надписи: «Replace your skills with the ones found in the new file?», «a language name», «language levels».
- Сигналы Qt — к методам, не к `lambda` с `self`; в `job_finder/*.py`, `tests/*.py` без кириллицы.
- Команда тестов: `.venv/Scripts/python -m pytest tests -q`; код выхода 0.
- Коммит заканчивается строкой `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. Повторный выбор того же файла резюме (навыки совпадают с найденными) — без вопроса.
2. Язык, введённый с пробелами или в другом регистре («  english »), — один язык `English`.
3. Резюме, где «C» стоит в списке языков («C, C++, Python»), — навык `C/C++` всё равно находится.
4. Отклик на junior.guru из удалёнки (`Remote`) при выключенной удалёнке — без пометки «закрыта».
5. Мастер (без сохранённых настроек) — пороги по умолчанию, а не пустые.

---

### Task 1: Форма — пороги, повторный выбор резюме, регистр, «Still needed»

**Files:** Modify `job_finder/settings.py`, `job_finder/settings_window.py`, `job_finder/insights.py` (комментарий);
Test `tests/test_settings.py`, `tests/test_settings_window.py`

**Interfaces:**
- Produces: `settings.skill_name(name) -> str` (имя из словаря без учёта регистра, иначе как введено),
  `settings.language_name(name) -> str` (из `LANGUAGES` без учёта регистра, иначе с заглавной буквы; пробелы по
  краям убраны); `SettingsForm.confirm_replace_skills() -> bool` (тесты подменяют);
  `SettingsForm.missing_text() -> str`.

- [ ] **Step 1: Тесты**
  - `test_canonical_skill_and_language_names` — `skill_name("python") == "Python"`, `skill_name("Kotlin MP") ==
    "Kotlin MP"`, `language_name("  english ") == "English"`, `language_name("vietnamese") == "Vietnamese"`.
  - `test_save_keeps_hidden_thresholds` — настройки с `min_score=7, stale_days=10, stale_job_days=30`, добавить
    навык, Save → пороги те же; мастер без настроек → 5/14/21.
  - `test_picking_a_cv_again_asks_before_replacing_skills` — навыки `["Python", "SQL"]`, главный `SQL`; новый
    файл с Python и Docker: «Нет» → навыки и главный те же; «Да» → `["Python", "Docker"]`, главный `Python`;
    тот же файл, где найденное совпадает с навыками, — вопроса нет.
  - `test_typed_names_match_known_ones` — «+ Add skill» `python` при пустом списке → плашка `Python`; языки
    `english B2` и `English C1` → `{"English": "C1"}`.
  - `test_still_needed_names_the_language_problem` — пустая новая строка → «Still needed: a language name»;
    имя есть, уровня нет → «Still needed: language levels».
- [ ] **Step 2: Run** `.venv/Scripts/python -m pytest tests -q` — Expected: FAIL на новых тестах.
- [ ] **Step 3: Реализация** по Interfaces; `values()` строится как `replace(сохранённые, …)`.
- [ ] **Step 4: Run** — Expected: PASS, код 0.
- [ ] **Step 5: Commit** — `git commit -m "Settings form: keep thresholds, ask before replacing skills, known names"`

### Task 2: Навыки из резюме без ложных срабатываний

**Files:** Modify `job_finder/settings.py`; Test `tests/test_settings.py`

**Interfaces:** `detect_skills` и `guess_main_skill` для `Go`, `C/C++`, `R`, `Spring`, `Mobile`, `REST API` берут
свои шаблоны: Go — `Go`/`Golang` с заглавной; C и R — заглавная буква перед `,` `/` `)` или `C++`; Spring — не
перед годом; Mobile — не как подпись телефона («Mobile:»); REST API — `REST`/`RESTful`/`REST API`/`API(s)`, не
слово «rest».

- [ ] **Step 1: Тест** `test_detect_skills_ignores_everyday_words` — текст «Mobile: +420 123. Spring 2024 exams,
  grade C. I like to go deeper. The rest is history.» → `[]`; «Go, C, C++, R, Spring Boot, mobile apps, REST
  APIs» → `["C/C++", "Go", "R", "Spring", "Mobile", "REST API"]` (порядок словаря); `guess_main_skill(["Go",
  "Python"], "go go go. Python")` → `"Python"`.
- [ ] **Step 2: Run** — FAIL. **Step 3:** реализация. **Step 4: Run** — PASS, код 0.
- [ ] **Step 5: Commit** — `git commit -m "Skills from a CV: no false Go, C, Spring, Mobile, REST"`

### Task 3: Пометка «вероятно, закрыта» и окно «My CV»

**Files:** Modify `job_finder/sources.py`, `job_finder/window.py`; Test `tests/test_sources.py`,
`tests/test_window.py`

**Interfaces:** `sources.still_fetched(source: str, city: str, s: Settings) -> bool` — удалённые сайты: только
при `s.remote`; junior.guru: город отклика — выбранный (как его пишет `parse_juniorguru`) или `Remote` при
`s.remote`; остальное — `True`. `MainWindow.load_rows` гасит `closed`, если `still_fetched` ложно (без настроек
не трогает). `open_settings` после Save перечитывает открытое окно «My CV».

- [ ] **Step 1: Тесты** — `test_still_fetched_follows_settings`; `test_closed_mark_only_for_jobs_still_searched`
  (отклик junior.guru из Prague: город Brno → без «⊘», Praha → с «⊘»; Jobicy при выключенной удалёнке → без);
  `test_settings_save_reloads_open_cv_window`.
- [ ] **Step 2: Run** — FAIL. **Step 3:** реализация. **Step 4: Run** — PASS, код 0.
- [ ] **Step 5: Commit** — `git commit -m "No false 'probably filled' after a city change; My CV follows Settings"`

Затем — финальное ревью свежим ревьюером, исправления, слияние в `main` и push (автор согласовал в чате).
