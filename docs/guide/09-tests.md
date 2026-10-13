# 9. Тесты

[← Окно и оформление](08-window-and-style.md) · [Оглавление](README.md) · [Дальше: рецепты и ограничения →](10-howto-and-limits.md)

Папка: [tests/](../../tests/). 41 тест, проходят примерно за 1,5 секунды.

## Как запускать

Из корня проекта:

```bash
.venv/Scripts/python.exe -m pytest
```

Полезные варианты:

```bash
.venv/Scripts/python.exe -m pytest -v
```

```bash
.venv/Scripts/python.exe -m pytest tests/test_db.py
```

```bash
.venv/Scripts/python.exe -m pytest -k dedupe
```

`-v` печатает имя каждого теста, путь к файлу запускает только его, `-k слово` — только тесты,
в имени которых есть это слово.

## Принципы

Тесты не трогают ничего настоящего:

- **Нет сети.** HTTP-запросы подменяются (`monkeypatch.setattr(sources.requests, "get", fake_get)`),
  вместо ответов сайтов — образцы прямо в коде тестов.
- **Нет LM Studio.** Подменяются `requests.post`, `subprocess.run`, `llm.prepare`, `llm.release`,
  `llm.evaluate`.
- **Нет настоящих файлов.** `config.DB_PATH` и `config.CV_PATH` указывают во временную папку.
- **Нет экрана.** Тесты окна работают с `QT_QPA_PLATFORM=offscreen` — Qt рисует «в никуда».

> **Справка: фикстуры pytest.**
> - `tmp_path` — новая пустая временная папка для каждого теста.
> - `monkeypatch` — временная подмена: `monkeypatch.setattr(config, "DB_PATH", …)`. После теста
>   всё возвращается как было — автоматически.
> - `@pytest.fixture` — своя подготовка; тест получает её, указав имя в параметрах.
>   `autouse=True` — применяется ко всем тестам файла без указания.
>   `scope="session"` — создаётся один раз на весь запуск (так сделано для `QApplication`: он
>   может быть только один на процесс).
> - `yield` в фикстуре — всё до него выполняется перед тестом, после — после теста.

> **Осторожно с `monkeypatch.undo()`.** Он откатывает **все** подмены теста, в том числе
> `config.CV_PATH`. После этого запись в `config.CV_PATH` пойдёт в настоящий `master_cv.md`.
> Поэтому в [test_key_changes_with_cv_and_rules](../../tests/test_worker.py#L48) правила возвращаются
> вручную через `setattr`, а не через `undo()`.

## test_sources.py — разбор источников (10 тестов)

Образцы ответов: CSV junior.guru, JSON Himalayas, Jobicy, Working Nomads ([строки 4-33](../../tests/test_sources.py#L4-L33)).

| Тест | Проверяет |
|---|---|
| `test_parse_juniorguru` | CSV → `Job`: HTML → текст, город «Praha»; «Удалённо» при `remote=True` |
| `test_parse_juniorguru_keeps_only_prague_or_remote` | остаются только Прага (в том числе второй в списке, район Háje) и удалёнка; Брно и вакансия без мест отсеяны |
| `test_parse_himalayas` | `guid` как `url`, дата из секунд Unix (и числом, и строкой), «Удалённо (3 страны …)», `None` в описании |
| `test_parse_jobicy` | поля Jobicy, «Удалённо: Europe», дата из ISO |
| `test_parse_workingnomads_keeps_only_development` | остаются только вакансии категории Development |
| `test_dedupe_keeps_higher_priority_source` | дубль по «компания + название» (с разным регистром и пробелами) остаётся у источника выше в списке |
| `test_fetch_all_isolates_source_errors` | упавший источник не роняет остальные, его ошибка в `errors` |
| `test_fetch_juniorguru_decodes_utf8_with_bom` | CSV с BOM читается, чешские буквы целы |
| `test_fetch_himalayas_pages_until_empty` | постраничная загрузка останавливается на пустой странице |
| `test_fetch_himalayas_respects_max_pages` | не больше `HIMALAYAS_MAX_PAGES` страниц |
| `test_parsers_tolerate_null_fields` | `null` в любых полях не роняет разбор и удаление дублей |

## test_skills.py — отсев по навыкам (5 тестов)

| Тест | Проверяет |
|---|---|
| `test_load_skills` | из образца резюме получаются ровно 7 навыков; `Concepts`, `In progress` и другие разделы пропущены |
| `test_load_skills_crlf_and_bom` | то же для файла с переводами строк Windows и BOM |
| `test_load_skills_without_section` | нет раздела Skills → пустой список |
| `test_matches_whole_words_case_insensitive` | `PYTHON` совпадает, `T-SQL` совпадает с `SQL`, `GitLab` и `MySQL` — нет |
| `test_matches_nothing_without_skills` | пустой список навыков ничего не пропускает |

## test_llm.py — модель (3 теста)

| Тест | Проверяет |
|---|---|
| `test_evaluate_sends_cv_and_truncated_vacancy` | адрес запроса, `model`, `json_schema`; резюме в конце системного сообщения; в сообщении пользователя название, компания, город; описание обрезано ровно до `MAX_DESCRIPTION_CHARS`; `score` из `"7"` стал `7` |
| `test_evaluate_rejects_answer_from_another_model` | ответ от другой модели → `ModelLost` с её именем |
| `test_prepare_starts_server_without_capturing_output` | `lms server start` вызывается с выводом в `DEVNULL` (иначе зависание, см. `prepare()` в [разделе 5](05-llm.md)), затем `lms ps --json` |

## test_db.py — база (8 тестов)

Фикстура `tmp_db` с `autouse=True` даёт каждому тесту свою пустую базу во временной папке.

| Тест | Проверяет |
|---|---|
| `test_pending_contains_new_jobs_newest_first` | новые вакансии в очереди, сначала свежие |
| `test_resave_keeps_evaluation_and_hidden` | повторный `save_jobs` не сбрасывает оценку и `hidden` |
| `test_jobs_missing_from_source_are_deactivated` | пропавшая из источника вакансия исчезает из списка, вакансии **другого** источника не трогаются |
| `test_cv_change_puts_jobs_back_in_queue` | с новым ключом вакансия снова в очереди и пропадает из списка |
| `test_hidden_job_not_in_queue_or_list` | скрытая — ни в очереди, ни в списке |
| `test_list_filters_by_threshold_and_sorts` | порог и порядок «оценка ↓, дата ↓»; строка совпадает с `make_row` |
| `test_duplicate_url_in_one_batch` | два одинаковых `url` в одной выдаче не ломают upsert |
| `test_count_evaluated_counts_current_key_only` | считаются только оценки с текущим ключом и только нескрытые |

## test_worker.py — фоновое обновление (3 теста)

Фикстура `setup`: временные база и резюме (`## Skills / - Python`), три вакансии вместо сети,
пустой `prepare`, `release` записывает свои вызовы. `_refresh()` вызывается напрямую, без потока.

| Тест | Проверяет |
|---|---|
| `test_model_lost_stops_evaluation` | после `ModelLost` оценка останавливается на первой же вакансии, сообщение содержит имя чужой модели, `release` вызван, ничего не сохранено |
| `test_summary_counts_suitable_and_evaluated` | итог «Готово: 2 подходящих из 3 оценённых» |
| `test_key_changes_with_cv_and_rules` | ключ меняется при смене правил и при смене резюме, возвращается при возврате правил |

## test_window.py — окно (8 тестов)

Фикстура `window`: временная база, резюме нет (значит, список изначально пуст), `Worker.start`
заменён пустышкой — обновление не запускается. Строки подаются через `on_evaluated(...)`, как будто
их прислал `Worker`.

| Тест | Проверяет |
|---|---|
| `test_evaluated_rows_sorted_and_filtered` | ниже порога не показывается, порядок «оценка ↓, дата ↓» |
| `test_selection_kept_when_new_row_arrives` | новая строка выше выбранной не сбивает выделение |
| `test_hide_removes_row` | «Скрыть» вызывает `db.hide` с нужным `url`, убирает строку, сбрасывает выбор |
| `test_score_colored_by_band` | цвет оценки в таблице и цвет плашки в карточке |
| `test_switching_rows_replaces_list_items` | при смене вакансии строки списков заменяются сразу, старых не остаётся; заголовок «ЕСТЬ · 2» |
| `test_no_risks_shows_no_blockers` | пустые риски → «Блокеров не найдено» |
| `test_empty_state_until_row_selected` | пока ничего не выбрано — пустая страница; после «Скрыть» — снова она |
| `test_icon_file_has_small_and_large_sizes` | в `icon.ico` есть размеры 16×16 (окно) и 256×256 (ярлык) |
| `test_finished_reloads_rows_from_db` | после обновления таблица перечитывается из базы: строка, которой в базе нет, исчезает |

## test_main.py и test_style.py (по 1 тесту)

| Тест | Проверяет |
|---|---|
| `test_second_instance_cannot_take_lock` | вторая блокировка не берётся, пока держится первая; после `unlock` — берётся |
| `test_score_colors_by_band` | три разных цвета; 8 — как 9 (зелёный), 6 — как 5 (янтарный) |

## Что тестами не покрыто

- Ветки `prepare()`: сервер не поднялся за 30 с, модель не загрузилась, модель уже загружена.
- Сообщения `worker` при отсутствии резюме и раздела Skills.
- `release()`, `open_job()`, `closeEvent()`.
- Настоящие API сайтов: если сайт поменяет формат, тесты этого не заметят (образцы зашиты в код).
  Заметно станет по ошибке источника в строке состояния.

[← Окно и оформление](08-window-and-style.md) · [Оглавление](README.md) · [Дальше: рецепты и ограничения →](10-howto-and-limits.md)
