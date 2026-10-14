# 8. Окно и оформление — window.py, cv_window.py, style.py

[← Фоновое обновление](07-worker.md) · [Оглавление](README.md) · [Дальше: тесты →](09-tests.md)

Файлы: [job_finder/window.py](../../job_finder/window.py) (571 строка),
[job_finder/cv_window.py](../../job_finder/cv_window.py) (67 строк),
[job_finder/style.py](../../job_finder/style.py) (101 строка).

## Справка: минимум про виджеты Qt

| Понятие | Что это |
|---|---|
| **Виджет** (`QWidget`) | любой элемент окна: кнопка, подпись, таблица, контейнер. Виджеты вкладываются друг в друга. |
| **Компоновка** (layout) | раскладывает дочерние виджеты: `QHBoxLayout` — в строку, `QVBoxLayout` — в столбик, `QGridLayout` — сеткой. Размеры считает сама при изменении окна. |
| **Растяжение** (stretch) | `addWidget(w, 1)` или `addStretch(1)`: кто забирает свободное место. Элемент с 1 растягивается, с 0 — занимает минимум. |
| `QMainWindow` | главное окно; основное содержимое ставится через `setCentralWidget`. |
| `QSplitter` | два виджета рядом с перетаскиваемой границей между ними. |
| `QStackedWidget` | «стопка страниц»: видна одна, переключение — `setCurrentIndex`. |
| `QScrollArea` | прокрутка для содержимого, которое не помещается. |
| `objectName` | имя виджета, по которому к нему цепляются стили (`QLabel#title { … }`). |
| **Стили** (stylesheet) | CSS-подобный текст, задающий цвета, рамки, отступы. Здесь он весь в `style.py`. |

## Дерево виджетов

```
MainWindow (QMainWindow, «Job Finder», 1200×750)
└─ central (QWidget#central, QVBoxLayout, поля и промежутки по GAP = 12 px)
   ├─ top (QHBoxLayout)
   │   ├─ refresh_button   QPushButton#primary «Refresh»
   │   ├─ found_tab │ applied_tab │ insights_tab   «Found · N | My applications · M | Insights» (QButtonGroup tabs)
   │   ├─ status_label     QLabel — строка состояния (растягивается)
   │   ├─ progress         QProgressBar ≤ 250 px, скрыт, пока нет оценки
   │   └─ cv_button        «My CV» — открывает окно резюме (cv_window.py)
   └─ views (QStackedWidget): [1] — страница Insights (раздел 11), [0] — splitter:
      splitter (QSplitter, начальные ширины 700 : 500)
       ├─ lists            QStackedWidget
       │   ├─ [0] table          найденные: Score | Job | Company | Location | Date
       │   └─ [1] applied_table  отклики:   Applied | Job | Company | Status | Days waiting | Score
       └─ card             QFrame#card — рамка карточки
           └─ pages        QStackedWidget
               ├─ [0] empty_page   «Select a job on the left»
               └─ [1] details_page
                   ├─ scroll (QScrollArea#detailsScroll)
                   │   └─ details (QWidget#details, QVBoxLayout box)
                   │       ├─ head:   d_title, d_company  │  badge 64×64 (число + «of 10»)
                   │       ├─ d_status   плашка «Applied ГГГГ-ММ-ДД · статус · N days» (только у откликов)
                   │       ├─ d_stale    янтарная подсказка «No reply for over 14 days…» (если ждём дольше)
                   │       ├─ notes_box  «NOTES» + поле notes (только у откликов)
                   │       ├─ d_notice   жёлтая «You already applied…» (только у перепубликованных)
                   │       ├─ facts:  Location / Published / Source (сетка 2 колонки)
                   │       ├─ divider (линия 1 px)
                   │       ├─ «WHY THIS SCORE» + d_summary
                   │       ├─ «YOU HAVE · N»      + строки ✓
                   │       ├─ «MISSING · N»       + строки ✕
                   │       └─ «RISKS · N»         + строки !
                   └─ footer (QWidget#footer): «Open job» (primary) и
                      у найденной — «I applied», «Hide»; у отклика — кнопки других статусов
                      («Waiting» / «Accepted» / «Rejected») и «Back to found»
```

Кнопки вынесены из прокрутки в `footer`, поэтому они всегда видны, даже при длинном разборе.
Переключатель стоит в верхней полосе, а не вкладками над таблицей, — так таблица и карточка
начинаются на одном уровне.

## Константы модуля — [строки 15-21](../../job_finder/window.py#L15-L21)

```python
COLUMNS = ["Score", "Job", "Company", "Location", "Date"]
APPLIED_COLUMNS = ["Applied", "Job", "Company", "Status", "Days waiting", "Score"]
LISTS = [("have", "YOU HAVE", "✓"), ("missing", "MISSING", "✕"), ("risks", "RISKS", "!")]
EMPTY_LIST = {"have": "—", "missing": "Nothing major"}
STATUS_TEXT = {"applied": "Waiting", "accepted": "Accepted", "rejected": "Rejected"}
REPOST_MARK = "↻ "
NEW_MARK = "• "
```

`LISTS` описывает три списка карточки: ключ в ответе модели, подпись, значок. По нему и строятся
виджеты, и заполняются — добавить четвёртый список можно одной строкой здесь (плюс поле в `SCHEMA`
и цвет в `style.LIST_COLORS`). `STATUS_TEXT` — подписи статусов отклика из базы (`db.STATUSES`).

## Помощники модуля — [строки 25-92](../../job_finder/window.py#L25-L92)

`_label(name)` ([25](../../job_finder/window.py#L25)) создаёт подпись с общими настройками:

- `setObjectName(name)` — чтобы к ней применился нужный стиль (`title`, `company`, `muted`…);
- `setTextFormat(Qt.PlainText)` — **только обычный текст**. По умолчанию `QLabel` сам решает,
  не HTML ли это, и может отрисовать теги. Тексты к нам приходят с чужих сайтов и от модели;
  обычный текст гарантирует, что никакой `<a href>` или `<img>` в них не сработает;
- `setWordWrap(True)` — перенос длинных строк;
- `TextSelectableByMouse` — текст можно выделить и скопировать.

`_caption(text)` ([35](../../job_finder/window.py#L35)) — подпись заголовка раздела (`YOU HAVE`,
`WHY THIS SCORE`…) со стилем `section`.

`_make_table(columns, center)` ([41](../../job_finder/window.py#L41)) — таблица в общем стиле; обе
таблицы (найденные и отклики) создаются ею, поэтому выглядят одинаково:

| Настройка | Эффект |
|---|---|
| `SelectRows`, `SingleSelection` | выделяется строка целиком и только одна |
| `NoEditTriggers` | ячейки нельзя редактировать |
| `verticalHeader().hide()` | без номеров строк слева |
| `setDefaultSectionSize(34)` | высота строки 34 px |
| `setShowGrid(False)`, `setAlternatingRowColors(True)` | без сетки, строки через одну подкрашены |
| `ResizeToContents` + колонка 1 `Stretch` | колонки по ширине содержимого, «Job» забирает остальное |
| `setDefaultAlignment(AlignLeft…)`, заголовок `center` по центру | заголовки выровнены так же, как текст в ячейках; колонка оценки — по центру |

`_score_item(score)` ([61](../../job_finder/window.py#L61)) — ячейка оценки: по центру, жирная,
цветом своей полосы (`style.score_colors(score)[1]`).

`_fill_table(table, rows, values, selected_url)` ([72](../../job_finder/window.py#L72)) — заполнить
таблицу. `values(row)` возвращает ячейки строки: текст или готовый `QTableWidgetItem` (так передаются
цветные ячейки оценки и статуса). Выделение восстанавливается по `url` — подробнее в `render()`.

`days_waiting(applied_at, today)` ([85](../../job_finder/window.py#L85)) — сколько дней прошло с
отклика; `plural_days(n)` ([90](../../job_finder/window.py#L90)) — «1 day», «3 days», «11 days»
(«day» только у единицы). Обе функции чистые:
«сегодня» передаётся явно, поэтому тесты проверяют их на фиксированной дате.

## Состояние окна — [строки 129-133](../../job_finder/window.py#L129-L133)

| Поле | Что это |
|---|---|
| `self.rows: list[dict]` | найденные вакансии **в порядке показа** (словари формы `db.make_row`). Таблица найденных всегда перерисовывается из этого списка: строка `i` — это `self.rows[i]`. |
| `self.applied: list[dict]` | отклики, новые сверху: те же словари плюс ключи `status` и `applied_at` (`db.list_applied`) |
| `self.applied_by_key` | отклик по ключу «компания + название» (`sources.same_job_key`) — для пометки «↻» |
| `self.new_urls: set[str]` | `url` непросмотренных вакансий (`db.unseen_urls()`) — для пометки «•» |
| `self.current: dict \| None` | выбранная строка — найденная вакансия или отклик (у отклика есть ключ `status`) — или `None` |

## `__init__` — [строка 125](../../job_finder/window.py#L125)

1. **Верхняя полоса** ([135-169](../../job_finder/window.py#L135-L169)): «Refresh» (`clicked → refresh`),
   переключатель, строка состояния с растяжением 1, полоса прогресса (скрыта), «My CV».
   Переключатель — три нажимаемые кнопки в `QButtonGroup` ([144](../../job_finder/window.py#L144)):
   группа сама следит, чтобы нажата была ровно одна, а `idClicked → show_tab` переключает вид:
   найденные, отклики или вкладку Insights ([раздел 11](11-insights.md)).

2. **Списки** ([171-180](../../job_finder/window.py#L171-L180)): две таблицы из `_make_table` в
   `QStackedWidget` `lists`: 0 — найденные (`itemSelectionChanged → on_select`), 1 — отклики
   (`→ on_select_applied`). У найденных колонка Location — постоянной ширины 150 px (`Interactive`):
   длинный список регионов («Remote: APAC, EMEA, …») иначе растягивал её и сжимал название до
   нескольких букв; теперь текст обрезается «…», а полностью место видно в карточке.

3. **Разделитель** ([182-186](../../job_finder/window.py#L182-L186)) — списки слева, карточка справа;
   ширина ручки равна `GAP`, поэтому промежуток между ними такой же, как от краёв окна.

4. **Компоновка и стили** ([188-199](../../job_finder/window.py#L188-L199)) — всё в вертикальный столбик,
   `setStyleSheet(style.STYLESHEET)` применяет тему ко всему окну и его потомкам.

5. **Worker** ([201-205](../../job_finder/window.py#L201-L205)) — создаётся и подписывается:
   `status → status_label.setText`, `progress → on_progress`, `evaluated → on_evaluated`,
   `finished → on_finished`.

6. **Данные** ([207-208](../../job_finder/window.py#L207-L208)):
   `load_rows()` — сразу показать прошлые оценки и отклики из базы;
   `QTimer.singleShot(0, self.refresh)` — запустить обновление «через 0 мс». Таймер сработает только
   когда заработает цикл событий, то есть после `window.show()` и `app.exec()`. Окно появляется
   мгновенно, а обновление стартует уже после этого.

## `_build_details()` — карточка — [строка 210](../../job_finder/window.py#L210)

Строит всё правое поле и возвращает рамку `card`. Ссылки на виджеты, которые потом заполняются,
сохраняются в поля окна:

| Поле | Что это |
|---|---|
| `d_title`, `d_company` | название и компания в шапке |
| `badge`, `badge_number`, `badge_caption` | плашка 64×64 с числом и «of 10» |
| `d_status` | плашка «Applied ГГГГ-ММ-ДД · статус» — видна только у откликов |
| `d_notice` | жёлтая плашка «You already applied…» — видна только у перепубликованных вакансий |
| `facts` | словарь `{"city": QLabel, "published": QLabel, "source": QLabel}` — значения фактов |
| `d_summary` | текст «почему такая оценка» |
| `detail_lists` | словарь `{"have": (заголовок, подпись, компоновка строк), …}` |
| `d_stale` | янтарная подсказка «No reply for over 14 days…» под плашкой отклика |
| `notes_box`, `notes`, `notes_timer`, `notes_url` | блок «NOTES», поле `QPlainTextEdit`, таймер сохранения 0,5 с и отклик, к которому относится текст |
| `open_button`, `found_buttons`, `applied_buttons`, `status_buttons` | кнопки нижней полосы: общая, два набора и словарь «статус → кнопка» |
| `pages` | стопка: 0 — «Select a job on the left», 1 — карточка |

Детали построения:

- **Плашки отклика и заметки** ([234-255](../../job_finder/window.py#L234-L255)) стоят сразу под
  шапкой. Отступ сверху у них задан в стиле (`margin-top`) или полями блока `notes_box`, а не через
  `addSpacing`: у скрытого блока нет и отступа, и карточка обычной вакансии выглядит как раньше.
  Поле заметок — `QPlainTextEdit` (обычный текст). Каждое нажатие клавиши перезапускает одноразовый
  таймер на 0,5 с (`textChanged → notes_timer.start`), по таймеру срабатывает `save_notes`.
- **Факты** ([257-268](../../job_finder/window.py#L257-L268)) — сетка 2 колонки: подпись серым
  (`metaKey`) и значение. `setColumnStretch(1, 1)` — колонка значений забирает ширину.
- **Отступы** — `box.setSpacing(0)` и явные `addSpacing(…)` между блоками: так у каждого промежутка
  своя точная величина (14, 16, 18, 8 px).
- **Списки** ([290-299](../../job_finder/window.py#L290-L299)) — для каждого из `LISTS` заголовок и
  пустая вертикальная компоновка, куда `_fill_list` потом добавляет строки.
- `box.addStretch(1)` в конце — прижимает содержимое к верху.
- **Кнопки** ([310-340](../../job_finder/window.py#L310-L340)): «Open job» есть всегда;
  `found_buttons` («I applied», «Hide») и `applied_buttons` («Waiting», «Accepted», «Rejected»,
  «Back to found») показываются по очереди в `show_details`; из кнопок статусов
  (`status_buttons`) видны только отличные от текущего статуса. Кнопки отклика скрыты сразу при создании
  ([330](../../job_finder/window.py#L330)): иначе при первой раскладке ширина карточки считалась бы по
  всем кнопкам сразу и таблица слева получилась бы уже.
- `card_box.setContentsMargins(1, 1, 1, 1)` ([362](../../job_finder/window.py#L362)) — отступ в 1 px,
  чтобы страницы не закрывали рамку карточки (рамка рисуется по краю `card`).
- В конце `show_details(None)` — изначально видна страница «Select a job on the left».

## Методы окна

### `load_rows()` — [строка 433](../../job_finder/window.py#L433)

```python
cv = read_cv()
self.rows = db.list_jobs(cv[1], config.MIN_SCORE) if cv else []
self.applied = db.list_applied()
self.applied_by_key = {sources.same_job_key(r["company"], r["title"]): r for r in reversed(self.applied)}
self.new_urls = db.unseen_urls()
self.render()
self.render_applied()
```

Перечитать из базы найденные (оценённые **по текущему ключу**, не ниже порога, без отклика) и все
отклики. Нет резюме — найденных нет, отклики всё равно видны. `reversed(...)`: отклики идут новые
сверху, и при нескольких откликах с одним ключом в словаре остаётся самый новый.

### `render()` — перерисовать найденные — [строка 444](../../job_finder/window.py#L444)

Строит ячейки (`values(row)`, [448](../../job_finder/window.py#L448)): оценка через `_score_item`,
название — с «↻ » впереди, если на вакансию с той же компанией и названием уже был отклик
(`_previous_application`, [429](../../job_finder/window.py#L429)), компания, город, дата. У
непросмотренной вакансии (`url` в `new_urls`) перед названием «• » и жирный шрифт. Затем
`_fill_table(...)` и подпись кнопки «Found · N (+K)», где K — сколько новых (без «(+0)»).

Как восстанавливается выделение (внутри `_fill_table`):

```python
table.blockSignals(True)          # не дёргать on_select во время перестройки
table.clearSelection()
table.setRowCount(len(rows))
for i, row in enumerate(rows):
    ... заполнить ячейки
    if row["url"] == selected_url:
        table.selectRow(i)        # вернуть выделение на ту же вакансию
table.blockSignals(False)
```

Зачем: новая оценка может встать **выше** выбранной строки. Номер выбранной строки изменится, и если
ничего не делать, выделение «съедет» на другую вакансию. Поэтому выделение запоминается по `url`.
`blockSignals(True)` нужен, чтобы перестройка не вызывала `on_select` и карточка не мигала.

`render()` трогает карточку, только если в ней **найденная** вакансия: если открыт отклик, а фоновое
обновление прислало новую найденную, карточка остаётся на отклике (тест
`test_new_found_row_keeps_application_selected`). Если выбранная найденная вакансия исчезла из
списка — `show_details(None)`.

### `render_applied()` — перерисовать отклики — [строка 464](../../job_finder/window.py#L464)

То же для таблицы откликов: дата отклика, название, компания, статус (текст из `STATUS_TEXT`, цвет
из `style.STATUS_COLORS`), «Days waiting» (дни с отклика через `days_waiting`, только у «Waiting»,
у остальных «—»; больше `config.STALE_DAYS` — янтарным цветом `notice_text`), оценка; число на кнопке «My applications · M». Карточку трогает, только если в
ней отклик.

### `show_tab(index)` — [строка 516](../../job_finder/window.py#L516)

Переключает стопку `lists` (0 — найденные, 1 — отклики), нажимает нужную кнопку переключателя,
снимает выделение в обеих таблицах и показывает пустую карточку.

### `on_select()` и `on_select_applied()` — [строки 529-535](../../job_finder/window.py#L529-L535)

Берут выбранную строку своей таблицы, по номеру находят словарь в `self.rows` или `self.applied`
и отдают в `show_details`. Ничего не выбрано — `show_details(None)`.

### `show_details(row)` — [строка 537](../../job_finder/window.py#L537)

- `row is None` → страница 0 («Select a job on the left»).
- Иначе страница 1 и заполнение: название, компания, факты (`row["city"]`, `row["published"]`,
  `row["source"]`), плашка оценки, «почему», три списка.
- Цвета, которые зависят от оценки, задаются **стилем прямо на виджете** (`setStyleSheet` с
  f-строкой): фон плашки, цвет числа, цветная полоса слева у блока «почему». Общая тема лежит в
  `style.py`, а эти стили меняются от вакансии к вакансии.
- `evaluation.get("summary") or "—"` и `evaluation.get(key) or []` — защита на случай, если в
  сохранённой оценке поля нет или оно пустое.
- **Сначала** `save_notes()` — дописать заметку прошлого отклика, если таймер ещё не сработал.
- **Отклик или найденная** ([561-593](../../job_finder/window.py#L561-L593)): у отклика (`"status" in
  row`) видна плашка `d_status` цветом статуса (у «Waiting» — с числом дней через `plural_days`;
  дольше `STALE_DAYS` — янтарная, и видна подсказка `d_stale`), поле заметок с текстом отклика
  (подставляется при `blockSignals`, чтобы не запускать таймер), «Back to found» и кнопки
  только других статусов; у найденной — кнопки
  `found_buttons` и, если на такую же вакансию уже был отклик, жёлтая `d_notice` «You already applied to
  "…" at … on ГГГГ-ММ-ДД — status: …». Видимость всех плашек и кнопок задаётся при каждом выборе, поэтому
  при переходе с отклика на обычную вакансию лишнее исчезает (тест `test_card_extras_reset_between_rows`).

### `_fill_list(key, mark, items)` — [строка 404](../../job_finder/window.py#L404)

Заполняет один из трёх списков:

1. Заголовок: `YOU HAVE · 2`, если пункты есть, или просто `YOU HAVE`.
2. **Удаление строк прошлой вакансии** ([408-411](../../job_finder/window.py#L408-L411)):

   ```python
   while rows.count():
       line = rows.takeAt(0).layout()
       while line.count():
           line.takeAt(0).widget().setParent(None)
   ```

   Каждая строка списка — горизонтальная компоновка «значок + текст». Её вынимаем, а виджеты внутри
   отвязываем от родителя через `setParent(None)` — так они **сразу** исчезают из окна. Привычный
   `deleteLater()` удалил бы их только на следующем проходе цикла событий, и какое-то время в
   карточке были бы видны строки прежней вакансии (это поймал тест
   [test_switching_rows_replaces_list_items](../../tests/test_window.py#L84)).

3. Пустые списки:

   | Список пуст | Что показывается |
   |---|---|
   | `risks` | зелёная ✓ «No blockers found» — хорошая новость, поэтому зелёным |
   | `have` | серое «—» без значка |
   | `missing` | серое «Nothing major» без значка |

4. Для каждого пункта — строка: значок фиксированной ширины 14 px цветом списка
   (`style.LIST_COLORS[key]`), прижатый к верху (если текст переносится на две строки), и текст
   с растяжением 1.

### `refresh()` — [строка 595](../../job_finder/window.py#L595)

```python
self.refresh_button.setEnabled(False)
self.load_rows()        # если резюме изменилось, старые оценки уходят из списка
self.worker.start()
```

Вызывается таймером при старте и кнопкой «Refresh». `load_rows()` здесь нужен на случай, если
резюме поменяли, пока окно было открыто: таблица сразу покажет только оценки по новому ключу.

### `on_progress(done, total)` — [строка 600](../../job_finder/window.py#L600)

Показывает полосу прогресса, ставит максимум и значение, пишет «Evaluated N of M».

### `on_evaluated(row)` — [строка 606](../../job_finder/window.py#L606)

```python
if row["score"] < config.MIN_SCORE:
    return
self.rows.append(row)
self.rows.sort(key=lambda r: (r["score"], r["published"]), reverse=True)
self.new_urls = db.unseen_urls()
self.render()
```

Свежая оценка ниже порога игнорируется. Иначе строка добавляется, список сортируется **тем же
порядком, что и SQL в `list_jobs`** (оценка по убыванию, затем дата по убыванию), таблица
перерисовывается. Поэтому порядок строк одинаков и во время оценки, и после перезапуска.
`new_urls` перечитывается, потому что фоновое обновление могло записать вакансию в базу уже после
загрузки списка — тогда и она получит пометку «•».

### `on_finished()` — [строка 614](../../job_finder/window.py#L614)

Прячет полосу прогресса, снова включает кнопку «Refresh» и перечитывает списки из базы
([`load_rows()`, строка 617](../../job_finder/window.py#L617)). Так из таблицы сразу уходят вакансии,
которые за это обновление пропали из источника или были отсеяны по месту: во время обновления окно
только добавляет новые оценки, а убирать строки ему было некому.

### `show_cv()` — [строка 621](../../job_finder/window.py#L621)

Кнопка «My CV» в верхней полосе ([строки 159-161](../../job_finder/window.py#L159-L161)). При первом
нажатии создаётся `CvWindow(self)`, дальше то же окно переиспользуется: `reload()` перечитывает файл,
`show()` / `raise_()` / `activateWindow()` выводят окно вперёд. Окно не модальное — главное окно
остаётся доступным. Импорт `CvWindow` сделан внутри метода, потому что `cv_window.py` сам берёт
`_label` из этого модуля: импорт наверху обоих файлов дал бы циклический импорт.

### `open_job()` и `hide_job()` — [строки 632-640](../../job_finder/window.py#L632-L640)

- `open_job` — `QDesktopServices.openUrl(...)` открывает ссылку в браузере по умолчанию.
- `hide_job` — `db.hide(url)`, убрать строку из `self.rows`, показать пустую страницу, перерисовать.

Обе используют `self.current` без проверки на `None`. Это безопасно: кнопки находятся на странице
карточки, а она видна только когда вакансия выбрана.

### Отклики: `apply_job()`, `set_status(status)`, `unapply_job()` — [строки 642-659](../../job_finder/window.py#L642-L659)

- `apply_job` — «I applied»: `db.apply(url)` (статус «Waiting», сегодняшняя дата), пустая карточка,
  `load_rows()` — вакансия уходит из найденных и появляется в откликах, числа на переключателе
  обновляются.
- `set_status("accepted" / "rejected")` — «Accepted» / «Rejected»: `db.set_status(...)`, `load_rows()`,
  и карточка **остаётся на этом отклике** с новым статусом (её заново заполняют свежей строкой из
  `self.applied`).
- `unapply_job` — «Back to found»: `db.unapply(url)` убирает статус и дату. Вакансия снова в
  найденных, если она всё ещё на сайте и её оценка сделана по текущему ключу. Если с момента отклика
  поменялись резюме, правила или модель, она появится после ближайшего «Refresh» (её оценят заново).
  Если вакансия уже пропала с сайта — исчезает из обоих списков.

### `save_notes()` — [строка 661](../../job_finder/window.py#L661)

Останавливает таймер и, если в карточке отклик и текст поля отличается от сохранённого, пишет его
в базу (`db.set_notes`) и в строку `self.applied`. Вызывается по таймеру, первой строкой
`show_details` (переход к другой строке, смена статуса, «Вернуть») и при закрытии окна — поэтому
набранная заметка не теряется, даже если таймер не успел сработать.

### `closeEvent(event)` — [строка 673](../../job_finder/window.py#L673)

Qt вызывает этот метод, когда окно закрывают. Сначала `save_notes()` и `db.mark_all_seen()` — все
оценённые вакансии становятся просмотренными, и при следующем запуске «•» будет только у пришедших
после этого (и у тех, что ещё ждут оценки). Если `worker.model_loaded` — запускаем `llm.release(wait=False)` (не ждём), затем
`event.accept()` — окно закрывается.

---

## cv_window.py — окно «My CV»

`CvWindow` ([строка 12](../../job_finder/cv_window.py#L12)) — отдельное окно (`QDialog`) с текущим
`master_cv.md`. Его родитель — главное окно, поэтому стили (`STYLESHEET`) применяются и к нему.

- **Сверху** карточка `card` со сведениями: путь к файлу, когда он изменён, навыки для отсева —
  `skills.load_skills(text)`, то есть ровно то, что использует отсев без ИИ.
- **Посередине** `QTextBrowser.setMarkdown(text)`: заголовки, списки и ссылки с оформлением. Это
  обычный виджет Qt, без браузера. Ссылки кликабельные (`setOpenExternalLinks(True)`).
- **Внизу** «Open in editor» (`QDesktopServices.openUrl(QUrl.fromLocalFile(...))` — откроет
  программу, назначенную для `.md`) и «Close».

`reload()` ([строка 53](../../job_finder/cv_window.py#L53)) перечитывает файл при каждом открытии.
Если файла нет — сообщение «master_cv.md not found…», кнопка редактора неактивна. Файл
читается с `errors="replace"`: даже если он сохранён не в UTF-8, окно откроется.

---

## style.py — тёмная тема

Все цвета и стили собраны в одном файле: чтобы поменять тему, достаточно поменять значения здесь.

### Палитра `COLORS` — [строка 5](../../job_finder/style.py#L5)

| Ключ | Цвет | Где |
|---|---|---|
| `bg` | `#1b1d23` | фон окна |
| `panel` | `#24272f` | фон таблицы, карточки, обычных кнопок |
| `border` | `#323641` | рамки, линии, фон неактивной главной кнопки и полосы прогресса |
| `scroll` | `#4b5060` | ползунок прокрутки |
| `text` | `#e5e7eb` | основной текст |
| `muted` | `#9ca3af` | второстепенный текст: заголовки колонок, подписи фактов и разделов |
| `accent` | `#16a34a` | зелёный: «Refresh», «Open job», заполнение прогресса |
| `accent_hover` | `#15803d` | главная кнопка под мышкой |
| `accent_soft` | `#1e3a2b` | выделенная строка таблицы |
| `alt` | `#272a33` | чередование строк, фон блока «почему», обычная кнопка под мышкой |
| `link` | `#4ade80` | ссылки в окне «My CV» (через палитру приложения, см. `apply_app_theme`) |
| `notice_bg`, `notice_text` | `#3a2f12`, `#fcd34d` | жёлтая плашка «You already applied» |

`GAP = 12` ([строка 21](../../job_finder/style.py#L21)) — единый отступ от краёв окна и между блоками.

`LIST_COLORS` ([строка 24](../../job_finder/style.py#L24)) — цвета значков: ✓ зелёный `#4ade80`,
✕ красный `#f87171`, ! жёлтый `#fbbf24`.

`STATUS_COLORS` ([строка 27](../../job_finder/style.py#L27)) — цвета статуса отклика, пары (фон плашки,
цвет текста): «Waiting» синий, «Accepted» зелёный, «Rejected» красный. Цвет текста красит ячейку
статуса в таблице откликов, пара целиком — плашку «Applied · статус» в карточке.

### Цвет оценки `score_colors(score)` — [строка 36](../../job_finder/style.py#L36)

Возвращает пару (фон плашки, цвет текста):

| Оценка | Пара | Вид |
|---|---|---|
| 8–10 | `_GOOD` = (`#14532d`, `#4ade80`) | зелёный |
| 7 | `_OK` = (`#0c4a6e`, `#7dd3fc`) | синий |
| ниже 7 | `_MAYBE` = (`#713f12`, `#fcd34d`) | янтарный (в таблице это 5–6, ниже порога строк нет) |

### Тема приложения `apply_app_theme(app)` — [строка 96](../../job_finder/style.py#L96)

Вызывается из `__main__` сразу после создания `QApplication`. Включает тёмную схему Qt
(`setColorScheme(Dark)`) и задаёт в палитре приложения цвет ссылок `link`: Qt красит ссылки из
Markdown цветом палитры приложения, а не стилями.

### Таблица стилей `STYLESHEET` — [строка 45](../../job_finder/style.py#L45)

Строка в синтаксисе Qt Style Sheets (похож на CSS). В конце — `.format(**COLORS)`: на место
`{bg}`, `{panel}`… подставляются цвета из палитры. Поэтому настоящие фигурные скобки CSS записаны
двойными `{{ }}` — так `str.format` понимает, что это не место подстановки.

Как читать селекторы:

| Селектор | Что выбирает |
|---|---|
| `QPushButton` | все кнопки |
| `QPushButton#primary` | кнопки с `objectName == "primary"` («Refresh», «Open job») |
| `QPushButton#segmentLeft`, `#segmentRight` | две половины переключателя «Found / My applications»: скругления только снаружи, жирный шрифт в обоих состояниях — чтобы ширина кнопки не менялась и текст не обрезался |
| `QPushButton#…:checked` | нажатая половина переключателя — фон `accent_soft` |
| `QLabel#notice` | жёлтая плашка «You already applied»; `margin-top` даёт отступ только видимой плашке |
| `QLabel#staleHint` | янтарная подсказка «No reply for over 14 days…» с отступом сверху |
| `QPlainTextEdit#notes` | поле заметок: фон `alt`, рамка, скругление |
| `QPushButton:hover`, `:disabled` | состояние: под мышкой, неактивна |
| `QTableWidget::item:selected` | «под-элемент» таблицы: выделенная ячейка |
| `QHeaderView::section` | ячейки заголовка таблицы |
| `QLabel#title`, `#company`, `#metaKey`, `#muted`, `#section`, `#empty` | подписи, которым `_label(...)` дал имя |
| `QFrame#card`, `QFrame#divider`, `QWidget#footer` | рамка карточки, линия, полоса кнопок |
| `QScrollBar:vertical`, `::handle`, `::add-line` | тонкая полоса прокрутки без стрелок |

Прозрачный фон у `detailsScroll`, `details`, `detailsPage`, `emptyPage`
([строки 77-78](../../job_finder/style.py#L77-L78)) нужен, чтобы сквозь них был виден фон карточки
`#card`, а не белый фон по умолчанию.

[← Фоновое обновление](07-worker.md) · [Оглавление](README.md) · [Дальше: тесты →](09-tests.md)
