# Новые источники — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** раздел 17 спека: вакансии Úřad práce (офис в своём крае, с зарплатой), Remote OK и We Work Remotely.

**Architecture:** новый модуль `job_finder/uradprace.py` (загрузка с 304, потоковый разбор, выбор IT, край,
кэш выборки, вакансии края → `Job`); в `sources.py` — разбор Remote OK и RSS We Work Remotely, порядок
источников, «только удалёнка», «ещё ищется»; `config.py` — адреса, коды, кэш.

**Tech Stack:** Python 3.11 (json, xml.etree, email.utils), requests, pytest. Без новых зависимостей.

**Spec:** `docs/superpowers/specs/2026-10-13-job-finder-design.md`, раздел 17.

## Global Constraints
- Источник «Úřad práce» (так и в строке «Source»), «Remote OK», «We Work Remotely».
- IT: CZ-ISCO с префиксом `25`, `351`, `1330`. Края: Praha 19, Středočeský 27, Jihočeský 35, Plzeňský 43,
  Karlovarský 51, Ústecký 60, Liberecký 78, Královéhradecký 86, Pardubický 94, Vysočina 108,
  Jihomoravský 116, Olomoucký 124, Moravskoslezský 132, Zlínský 141 (проверено по PSČ); города → края:
  Praha 19, Brno 116, Ostrava 132, Plzeň 43, Olomouc 124, Liberec 78, České Budějovice 35, Hradec Králové 86,
  Pardubice 94, Zlín 141, Jihlava 108, Karlovy Vary 51, Ústí nad Labem 60.
- Кэш — `config.UP_CACHE = ROOT / "cache" / "uradprace.json"`, папка `cache/` в `.gitignore`.
- Тесты не ходят в сеть; без кириллицы в коде; код выхода 0; коммит с `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus
1. Повреждённый или обрезанный файл MPSV — ошибка источника, старая выборка не теряется.
2. Вакансия без работодателя (анонимная) или без описания — без падения.
3. RSS с пустым регионом, без двоеточия в заголовке, с непарсящейся датой — без падения.
4. Смена города без новой загрузки — вакансии другого края из кэша.
5. Память при разборе — без загрузки всего файла (проверка размером буфера в тесте не нужна, но код не должен читать файл целиком).

---

### Task 1: Úřad práce
**Files:** создать `job_finder/uradprace.py`, `tests/test_uradprace.py`; изменить `job_finder/config.py`, `.gitignore`.
**Interfaces:** `iter_items(chunks: Iterable[str]) -> Iterator[dict]`; `pick_it(items) -> list[dict]` (компактные
записи с краем); `load(session_get=requests.get) -> list[dict]` (304/кэш/ошибка); `jobs_for(records, city) -> list[Job]`;
`fetch(city) -> list[Job]`.
- [ ] Тесты: `test_iter_items_across_chunk_borders`; `test_pick_it_resolves_regions`; `test_jobs_for_city_fields_and_salary`;
  `test_load_uses_cache_on_304_and_on_network_error`; `test_broken_file_keeps_old_cache`. Run — FAIL. Реализация. Run — PASS.
- [ ] Commit `Úřad práce: IT vacancies in your region from the labour office open data`.

### Task 2: Remote OK, We Work Remotely и подключение источников
**Files:** `job_finder/sources.py`, `tests/test_sources.py`.
**Interfaces:** `parse_remoteok(data: list) -> list[Job]`; `parse_wwr(xml_text: str) -> list[Job]`; `fetch_remoteok()`,
`fetch_wwr()`; `REMOTE_ONLY` += оба; `FULL_LIST_SOURCES` += «Úřad práce»; `still_fetched` для «Úřad práce».
- [ ] Тесты: `test_parse_remoteok`; `test_parse_wwr`; `test_sources_order_and_remote_flags`;
  `test_still_fetched_uradprace`. Run — FAIL. Реализация. Run — PASS.
- [ ] Commit `Remote OK and We Work Remotely; all new sources in the refresh`.

### Task 3: Документация и живая проверка
- [ ] README («What it does» — список сайтов), how-it-works (таблица источников, кэш). Скрипт в scratchpad: один
  реальный `fetch_all` без оценки — сколько вакансий от каждого источника. Run tests — PASS.
- [ ] Commit `Docs for the new sources`.

Затем ревью свежим ревьюером, исправления; слияние и push — после проверки автором.
