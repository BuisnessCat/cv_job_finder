# Переделка настроек после проверки — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** вместо ключевых слов — главный навык из списка; языки списком; пять уровней с выбором нескольких;
без разрешения на работу и раздела Advanced; окно Settings — меню слева (вариант B); падение pytest при
выходе (код 139) исправлено.

**Architecture:** продолжение ветки `settings` (задачи 1–5 плана `2026-10-17-settings.md` уже в коммитах,
этот план заменяет его задачу 6). Меняются поля `Settings` и всё, что их читает: правила (`llm`), поиск
(`sources`), окна (`settings_window`, кнопка в `window`). Форма собирается из трёх страниц (`cv`, `search`,
`languages`); мастер показывает их шагами, Settings — по пункту меню слева.

**Tech Stack:** Python 3.11, PySide6, SQLite, pypdf, pytest.

**Spec:** `docs/superpowers/specs/2026-10-13-job-finder-design.md`, раздел 15 (переписан 2026-10-17, 15.9 —
что изменилось).

## Global Constraints

- Поля и значения по умолчанию — ровно как в таблице 15.1: `cv_path`, `skills`, `main_skill`, `city`,
  `remote`, `levels` (`intern, junior, mid, senior, lead`, по умолчанию `["junior"]`), `languages`
  (имя → уровень из `A1, A2, B1, B2, C1, C2, Native`; по умолчанию `{"English": ""}`), `min_score`,
  `stale_days`, `stale_job_days` (5, 14, 21; в окне не показываются).
- Обязательные: резюме (читается), хотя бы один навык, главный навык из навыков, хотя бы один уровень,
  хотя бы один язык и у каждого языка имя и уровень.
- Влияют на оценку: резюме, город, удалёнка, уровни, языки. Не влияют: навыки, главный навык, пороги.
- Надписи: «Welcome to Job Finder», «Your CV», «What you're looking for», «Languages», «Main skill»,
  «+ Add skill», «+ Add language», «Remote is fine», «Level», «Intern», «Junior», «Mid», «Senior», «Lead»,
  «Back», «Next», «Start search», «Settings», «Save», «Cancel», «Still needed: …»,
  «All jobs will be scored again (about N min). Save?».
- Сигналы Qt подключаются к методам, а не к `lambda`, которая держит `self` (иначе окно живёт до выхода из
  Python и процесс падает с кодом 139).
- В коде нет значений автора; в `job_finder/*.py`, `tests/*.py` — без кириллицы; тесты не трогают
  настоящие `jobs.db` и `master_cv.md`.
- Команда тестов: `.venv/Scripts/python -m pytest tests -q`; набор завершается с кодом 0.
- Коммит заканчивается строкой `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. Главный навык с «/» в названии (`C#/.NET`, `C/C++`) или введённый вручную: Himalayas получает
   осмысленный запрос — тест в задаче 1.
2. Настройки, сохранённые в старом виде (есть `keywords`, `english`, `level`): приложение не падает,
   при запуске открывается мастер с резюме, навыками, городом — тест в задаче 2.
3. Убрали все навыки или главный навык: главный навык выбирается заново или становится «не хватает» —
   тест в задаче 2.
4. Один и тот же язык добавлен дважды: сохраняется один (последний уровень), без падения — тест в задаче 2.
5. Резюме, которое перестало читаться после настройки: в Settings видна ошибка, «Save» недоступна, но
   «Cancel» работает — тест в задаче 2.

---

### Задача 1: Модель настроек, правила и поиск

**Files:**
- Modify: `job_finder/settings.py`, `job_finder/llm.py`, `job_finder/sources.py`, `job_finder/config.py`,
  `job_finder/window.py` (только `_search_changed`)
- Test: `tests/test_settings.py`, `tests/test_llm.py`, `tests/test_sources.py`, `tests/helpers.py`

**Interfaces:**
- Produces (`settings.py`): `LEVELS`, `LANGUAGE_LEVELS`, `LANGUAGES` (подсказки для выпадающего списка:
  English, Czech, Slovak, German, Polish, Russian, Ukrainian, French, Spanish, Italian),
  `PROGRAMMING_LANGUAGES` (группа «Languages» словаря: Python … R), `Settings` с полями из 15.1,
  `SCORING_FIELDS = ("cv_path", "city", "remote", "levels", "languages")`, `missing(s)` в порядке
  `cv_path, skills, main_skill, levels, languages`, `guess_main_skill(skills, cv_text) -> str`,
  `initial(cv) -> Settings` (резюме, навыки, догадка главного навыка); `load()` молча отбрасывает
  неизвестные старые поля.
- Produces (`llm.py`): `render_rules(s)` — уровни и языки из 15.5, без разрешения на работу.
- Produces (`sources.py`): `fetch_himalayas(main_skill: str, levels: list[str])` — один запрос, до
  `HIMALAYAS_MAX_PAGES`; `config.HIMALAYAS_SENIORITY: dict[str, list[str]]` из 15.5;
  `config.HIMALAYAS_QUERY = {"C#/.NET": "C#", "C/C++": "C++"}` (остальные навыки — как написаны).
- Produces (`window.py`): `_search_changed` смотрит на `main_skill` и `skills` вместо `keywords`.

- [ ] **Step 1: Тесты**
  - `test_missing_lists_required_fields_in_order` — `missing(Settings()) == ["cv_path", "skills",
    "main_skill", "languages"]` (уровень `junior` по умолчанию есть); главный навык не из навыков →
    `main_skill`; `levels=[]` → `levels`; `languages={"English": "B2", "Czech": ""}` → `languages`.
  - `test_old_settings_load_without_errors` — в таблицу записан JSON со старыми `keywords`, `english`,
    `czech`, `needs_permit`, `level` → `load()` возвращает `Settings` с резюме, навыками и городом,
    `missing` содержит `main_skill` и `languages`.
  - `test_guess_main_skill` — `["Docker", "Python", "Java"]` и текст, где Java встречается чаще Python →
    `"Java"`; без языков программирования → первый навык; пустые навыки → `""`.
  - `test_scoring_changed_only_for_scoring_fields` — навыки, главный навык, `min_score` → нет; город,
    уровни, языки → да.
  - `test_rules_follow_settings` — `levels=["intern", "junior"]` → «internship or junior»; языки
    `{"English": "C1", "Russian": "Native"}` → «English C1» и «Russian native» в тексте; нет слова
    `permit`; `levels=["senior"]` → блокер senior (lead/principal или 10+ лет) и роли ниже — слабое
    совпадение; правила кончаются на «Candidate's CV:\n».
  - `test_fingerprint_ignores_skills_and_main_skill`.
  - `test_himalayas_searches_main_skill_with_level_seniority` — `fetch_himalayas("C#/.NET", ["intern",
    "junior"])` запрашивает `q=C#`, `seniority=Entry-level,Mid-level` (без повторов, по порядку), до 10
    страниц, остановка на пустой странице.
  - `helpers.use_settings` — заполненные настройки нового вида: навыки `["Python"]`, главный `Python`,
    `languages={"English": "B2"}`.
- [ ] **Step 2: Запустить — должны упасть.** Run: `.venv/Scripts/python -m pytest tests -q --ignore=tests/test_settings_window.py`. Expected: FAIL на новых тестах.
- [ ] **Step 3: Реализация** по Interfaces и 15.5. Уровни — словарь слов по каждому уровню; при
  нескольких: названия через «or», блокер и полосы «выше уровня» — по самому высокому, «заметно ниже» —
  по самому низкому (для mid и выше), «можно выучить на работе» — если выбран intern или junior.
- [ ] **Step 4: Запустить — должны пройти.** Та же команда. Expected: PASS (`test_settings_window.py`
  переписывается в задаче 2, до неё не запускается).
- [ ] **Step 5: Commit** — `git commit -m "Settings: main skill, several levels, a list of languages"`

### Задача 2: Окна — плашки, уровни, языки, меню слева; падение при выходе

**Files:**
- Modify: `job_finder/settings_window.py`, `job_finder/cv_window.py`, `job_finder/style.py`
- Create (по желанию исполнителя): `job_finder/flow_layout.py` — раскладка плашек с переносом
- Test: `tests/test_settings_window.py` (переписать), `tests/test_cv_window.py`

**Interfaces:**
- Consumes: всё из задачи 1.
- Produces: `SettingsForm` — `set_values(s)`, `values() -> Settings`, `missing() -> list[str]`,
  `set_cv(path)`, `page(name) -> QWidget` для `"cv" | "search" | "languages"`; поля: `cv_button`,
  `cv_input`, `cv_error`, `skill_input` (Enter добавляет), `skill_chips() -> list[str]`,
  `remove_skill(name)`, `main_skill_box`, `city_box`, `remote_check`, `level_buttons` (несколько сразу,
  последняя не выключается), `add_language_button`, `language_rows` (имя — редактируемый выпадающий
  список с `LANGUAGES`, уровень — список с подсказкой «Level», кнопка ×).
  `Wizard` — как сейчас (`step`, `step_label`, `bar`, `back_button`, `next_button`, `values()`), шаги
  Welcome / Your CV / What you're looking for / Languages; на последнем шаге, если в базе есть оценки, —
  серая строка, что всё будет оценено заново.
  `SettingsDialog` — `nav` (меню слева), `pages`, `missing_label` («Still needed: …»), `save_button`,
  `cancel_button`, `confirm_rescore(jobs) -> bool`.
  `first_run(cv) -> bool` — мастер, если настроек нет или `missing` не пуст; заполнен сохранённым.

- [ ] **Step 1: Тесты** (`tests/test_settings_window.py`)
  - `test_wizard_next_waits_for_required_fields` — шаг Your CV: без файла «Next» недоступна; `set_cv` →
    плашки `["Python", "Docker"]`, главный навык `Python`, «Next» доступна.
  - `test_chips_add_remove_and_main_skill` — Enter в `skill_input` добавляет плашку (повтор без учёта
    регистра не добавляется); убрать главный → главный — догадка из оставшихся; убрать все → «Next»
    недоступна.
  - `test_levels_several_and_never_none` — включить Intern при Junior → `levels == ["intern", "junior"]`;
    выключить обе по очереди → последняя остаётся включённой.
  - `test_languages_rows` — по умолчанию строка English без уровня, «Start search» недоступна; выбрать
    уровень → доступна; «+ Add language» → новая строка; × убирает; два раза English → в `values()` один.
  - `test_wizard_finishes_with_values` — пройти все шаги → `values()` равен ожидаемому `Settings`.
  - `test_first_run_shows_wizard_only_for_missing_settings` — без настроек и с неполными (старый JSON) —
    мастер; закрыт → ничего не сохранено, `False`; с полными — мастер не показывается.
  - `test_settings_still_needed_and_save` — убрать уровень языка → «Save» недоступна, `missing_label`
    называет языки; `test_settings_cancel_changes_nothing`; `test_rescore_question_only_for_scoring_fields`
    (навыки — без вопроса; город — вопрос, «Cancel» не сохраняет, «Save» сохраняет).
  - `test_settings_flag_a_moved_cv` — резюме удалено → ошибка видна, «Save» недоступна, «Cancel» закрывает.
  - `test_windows_are_freed_when_closed` — `Wizard`, `SettingsDialog`, `CvWindow`: после `del` слабая
    ссылка пуста без `gc.collect()`.
- [ ] **Step 2: Запустить — должны упасть.** Run: `.venv/Scripts/python -m pytest tests -q`. Expected: FAIL.
- [ ] **Step 3: Реализация** — вид по варианту B (15.4) и мастер B (15.2); стили плашек, меню и строк
  языков — в `style.py`. В `cv_window.py` кнопку «Open in editor» подключить к методу.
- [ ] **Step 4: Запустить — должны пройти, код выхода 0.** Run: `.venv/Scripts/python -m pytest tests -q; echo $?`. Expected: PASS и `0`.
- [ ] **Step 5: Скриншоты** мастера (шаги 2–4) и окна Settings (три раздела) в настоящем окне — показать
  автору.
- [ ] **Step 6: Commit** — `git commit -m "Settings window with a side menu, skill chips, levels and languages"`

### Задача 3: Проверка правил на 40 вакансиях

Только когда видеокарта свободна (нет игры, `nvidia-smi`). Скрипт `compare_neutral_rules.py` из
scratchpad с новыми настройками автора (`levels=["junior"]`, `languages={"English": "B2", "Czech": "B1"}`)
на копии базы. Критерии из 15.5. Не прошло — правится формулировка, повтор. Без коммита; итог — в журнал.

### Задача 4: Документация и уборка

**Files:**
- Modify: `README.md`, `docs/how-it-works.ru.md`, `job_finder/config.py`, `job_finder/skills.py`,
  `tests/test_skills.py`, `docs/screenshots/` (новый `settings.png`)

- [ ] **Step 1:** README — «Running it yourself»: при первом запуске мастер (резюме любым файлом, главный
  навык, уровни, языки), потом всё в Settings; скриншот окна Settings. how-it-works — простыми словами про
  настройки, мастер и почему нет ключевых слов; таблица ошибок без `master_cv.md`.
- [ ] **Step 2:** убрать неиспользуемое: `config.MIN_SCORE`, `STALE_DAYS`, `STALE_JOB_DAYS`,
  `skills.skill_lines`/`load_skills` и их тесты; `config.CV_PATH` остаётся (мастер ищет старое резюме).
- [ ] **Step 3:** Run: `.venv/Scripts/python -m pytest tests -q; echo $?`. Expected: PASS и `0`; поиск
  `grep -rn "keywords\|needs_permit\|MIN_SCORE" job_finder tests` пуст.
- [ ] **Step 4: Commit** — `git commit -m "Docs for the settings; remove unused config"`

### Задача 5: Переход автора

С автором и при свободной видеокарте: запуск → мастер открывается со старыми резюме, навыками, городом →
автор выбирает главный навык, уровни, языки → «Start search» → полная переоценка. Проверить: Himalayas
снова около 200 вакансий, оценки разумные. Затем финальное ревью ветки, исправления, слияние в `main` и
push — только с согласия автора.
