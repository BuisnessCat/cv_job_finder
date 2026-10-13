# 7. Фоновое обновление — worker.py

[← База данных](06-db.md) · [Оглавление](README.md) · [Дальше: окно и оформление →](08-window-and-style.md)

Файл: [job_finder/worker.py](../../job_finder/worker.py) (107 строк).

Этот модуль — «дирижёр»: он сам почти ничего не делает, а вызывает `sources`, `skills`, `db`,
`llm` в правильном порядке и сообщает окну о ходе работы. И всё это — в фоновом потоке.

## Зачем фоновый поток

У Qt-приложения есть **главный поток**, в котором крутится цикл событий: он обрабатывает клики,
перерисовывает окно, запускает таймеры. Если в главном потоке выполнить долгую операцию (загрузка
вакансий — секунды, оценка — десятки минут), цикл событий остановится: окно перестанет
перерисовываться, и Windows напишет «Не отвечает».

Поэтому вся долгая работа идёт в отдельном потоке, а окно только получает готовые результаты.

## Справка: сигналы Qt и потоки

**Сигнал** — это «событие», которое объект может испустить, а другие — на него подписаться.

```python
class Worker(QObject):
    status = Signal(str)          # объявление: сигнал с одним аргументом-строкой

worker.status.connect(label.setText)   # подписка: при сигнале вызвать label.setText(текст)
worker.status.emit("Loading…")         # испускание: все подписчики получат "Loading…"
```

Главное правило Qt: **виджеты можно трогать только из главного потока**. Изменение подписи
или таблицы из фонового потока может привести к падению или порче окна.

Сигналы решают эту проблему автоматически. Когда сигнал испускается, Qt смотрит: в каком потоке
мы сейчас и в каком потоке «живёт» получатель (окно и его виджеты живут в главном). Если потоки
разные, Qt **не вызывает** получателя сразу, а кладёт вызов в очередь событий главного потока.
Цикл событий доходит до него и выполняет — уже в главном потоке. Это называется *queued connection*.

Поэтому в коде строгое разделение:

- фоновый поток **никогда** не обращается к виджетам — только испускает сигналы;
- методы окна `on_progress`, `on_evaluated`, `on_finished` и `setText` всегда выполняются
  в главном потоке, и в них можно спокойно менять виджеты.

**Почему `threading.Thread`, а не `QThread`.** Обычный поток Python проще (не нужно переносить
объект в поток через `moveToThread`), а сигналы Qt правильно работают из любого потока. Код
запуска — одна строка.

## read_cv и ключ оценки

[`read_cv()`, строка 13](../../job_finder/worker.py#L13):

```python
if not config.CV_PATH.exists():
    return None
text = config.CV_PATH.read_text(encoding="utf-8")
return text, hashlib.sha256(f"{text}\n{llm.fingerprint()}".encode("utf-8")).hexdigest()
```

Возвращает пару (текст резюме, ключ оценки) или `None`, если файла нет.

**Ключ оценки** — SHA-256 от строки «резюме + модель + правила». SHA-256 превращает любой текст
в 64 шестнадцатеричных символа; изменится хоть один символ входа — получится совсем другой ключ.

Ключ сохраняется вместе с каждой оценкой (колонка `cv_hash`). Дальше:

- `db.pending_jobs(key)` — в очереди всё, что оценено **не** с этим ключом;
- `db.list_jobs(key, …)` — в окне только то, что оценено **с этим** ключом.

Что из этого следует:

| Действие | Что произойдёт |
|---|---|
| поправили `master_cv.md` | ключ другой → таблица пустеет → все вакансии снова в очереди → таблица заполняется по мере переоценки |
| поменяли `RULES` или `MODEL` | то же самое |
| вернули резюме как было | ключ снова прежний → старые оценки сразу снова показываются, переоценивать нечего |
| поменяли `MIN_SCORE`, цвета, источники | ключ тот же, переоценки нет |

`read_cv()` вызывается из двух мест: здесь, в `_refresh()`, и в `window.load_rows()` — окно
считает ключ тем же способом, чтобы показать оценки именно по текущему резюме.

## `_join(summary, notes)` — [строка 24](../../job_finder/worker.py#L24)

Склеивает итог и замечания через `"; "`:
`"Done: 23 matches out of 259 evaluated; Jobicy: error (…)"`.

## Класс `Worker` — [строка 28](../../job_finder/worker.py#L28)

Наследуется от `QObject` — базового класса Qt, без которого нельзя объявлять сигналы.

### Сигналы

| Сигнал | Аргументы | Когда испускается | Кто получает в окне |
|---|---|---|---|
| `status` | `str` | смена этапа и итог | `status_label.setText` |
| `progress` | `int, int` (оценено, всего) | перед оценкой и после каждой вакансии | `on_progress` |
| `evaluated` | `object` (словарь `make_row`) | после каждой успешной оценки | `on_evaluated` |
| `finished` | — | в самом конце, всегда | `on_finished` |

`Signal(object)` означает «любой объект Python» — так через сигнал передаётся словарь как есть.

### `model_loaded` — [строка 36](../../job_finder/worker.py#L36)

Флаг «модель сейчас может быть в видеопамяти». Его читает `closeEvent` окна: если флаг поднят,
при закрытии нужно выгрузить модель.

### `start()` — [строка 38](../../job_finder/worker.py#L38)

```python
threading.Thread(target=self._run, daemon=True).start()
```

Каждый вызов — новый поток, который выполнит `_run()` и завершится.
`daemon=True` — поток-«демон» не мешает процессу завершиться: окно закрывается сразу, даже если
поток ждёт ответа модели.

Защиты от двух одновременных запусков в `Worker` нет. Её роль играет окно: на время обновления
кнопка «Refresh» неактивна (`refresh()` её выключает, `on_finished()` включает).

### `_run()` — [строка 42](../../job_finder/worker.py#L42)

```python
try:
    message = self._refresh()
    log.info(message)
    self.status.emit(message)
except Exception:
    log.exception("Обновление упало")
    self.status.emit("Update failed, see job_finder.log")
finally:
    self.finished.emit()
```

Обёртка, которая гарантирует две вещи: любое непредвиденное исключение попадёт в лог (а не
потеряется молча в фоновом потоке), и `finished` придёт **всегда** — иначе кнопка «Refresh»
навсегда осталась бы серой.

## `_refresh()` — одно обновление, по шагам — [строка 53](../../job_finder/worker.py#L53)

**Шаг 1. Загрузка и запись** ([55-60](../../job_finder/worker.py#L55-L60))

```python
self.status.emit("Loading jobs…")
fetched, errors = sources.fetch_all()
for name, jobs in fetched.items():
    db.save_jobs(name, jobs)
log.info("Загружено: %s", {name: len(jobs) for name, jobs in fetched.items()})
notes = [f"{name}: ошибка ({error})" for name, error in errors.items()]
```

Только успешно загруженные источники записываются в базу. Ошибки превращаются в замечания
`notes`, которые в конце допишутся к итогу.

**Шаг 2. Резюме и навыки** ([62-68](../../job_finder/worker.py#L62-L68))

Нет `master_cv.md` → возврат с сообщением «No master_cv.md, evaluation skipped».
Нет навыков → «No Skills section in master_cv.md, evaluation skipped». Вакансии при этом уже
загружены и записаны — пропускается только оценка.

**Шаг 3. Очередь** ([69-70](../../job_finder/worker.py#L69-L70))

```python
todo = [job for job in db.pending_jobs(cv_hash) if skills.matches(job, skill_list)]
```

Из базы — вакансии без оценки по текущему ключу (сначала новые), из них — только с навыками.

**Шаг 4. Оценка** ([72-85](../../job_finder/worker.py#L72-L85)) — только если очередь не пуста

```python
self.status.emit("Starting LM Studio…")
self.model_loaded = True
try:
    llm.prepare()
    failed = self._evaluate(todo, cv_text, cv_hash)
    if failed:
        notes.append(f"failed to evaluate: {failed}")
except Exception as error:
    log.exception("LM Studio недоступна")
    notes.append(f"LM Studio: {error}")
finally:
    llm.release()
    self.model_loaded = False
```

Тонкости:

- `model_loaded = True` ставится **до** `prepare()`: если закрыть окно, пока модель ещё грузится,
  `closeEvent` всё равно отправит `unload`. А если `unload` дойдёт раньше, чем модель догрузится,
  сработает `--ttl 300` и LM Studio выгрузит её сама.
- `except Exception` ловит и ошибки `prepare()` (нет `lms.exe`, сервер не поднялся, модель не
  загрузилась), и `ModelLost` из `_evaluate()`. Текст ошибки попадает в строку состояния.
- `finally: llm.release()` — модель выгружается **в любом случае**, даже после ошибки.
  Видеопамять не остаётся занятой после обновления.

**Шаг 5. Итог** ([87-89](../../job_finder/worker.py#L87-L89))

```python
suitable = len(db.list_jobs(cv_hash, config.MIN_SCORE))
evaluated = db.count_evaluated(cv_hash)
return _join(f"Done: {suitable} matches out of {evaluated} evaluated", notes)
```

Числа — по всей базе с текущим ключом, а не только за этот запуск: «23 подходящих из 259 оценённых»
означает «всего сейчас».

## `_evaluate(todo, cv_text, cv_hash)` — [строка 91](../../job_finder/worker.py#L91)

```python
failed = 0
self.progress.emit(0, len(todo))
for done, job in enumerate(todo, 1):          # done считается с 1
    try:
        evaluation = llm.evaluate(cv_text, job)
    except llm.ModelLost:
        raise                                  # дальше оценивать нечем — стоп
    except Exception:
        log.exception("Не удалось оценить %s", job.url)
        failed += 1                            # эту пропускаем, идём дальше
    else:                                      # выполняется, только если не было исключения
        db.save_evaluation(job.url, evaluation, cv_hash)
        self.evaluated.emit(db.make_row(job, evaluation))
    self.progress.emit(done, len(todo))
return failed
```

- Порядок `except` важен: `ModelLost` наследуется от `RuntimeError`, а значит и от `Exception`.
  Если бы `except Exception` стоял первым, он перехватил бы и `ModelLost`.
- **Каждая оценка сохраняется сразу.** Если закрыть приложение посреди оценки, сделанное не
  пропадёт: при следующем обновлении в очереди будут только оставшиеся вакансии.
- Неудачная вакансия не получает оценки и сама вернётся в очередь в следующий раз.

## Пример того, что видно в строке состояния

```
Loading jobs…
Starting LM Studio…
Evaluated 0 of 42        ← сигнал progress (текст ставит on_progress в окне)
Evaluated 1 of 42
…
Evaluated 42 of 42
Done: 23 matches out of 259 evaluated; Jobicy: error (HTTPSConnectionPool…)
```

Если оценивать нечего (всё уже оценено), шагов «Starting LM Studio…» и «Evaluated…» не будет:
сразу «Done: …».

## Все ситуации с ошибками

| Ситуация | Где обрабатывается | Что видно |
|---|---|---|
| источник недоступен / сменил формат | `sources.fetch_all` | «<источник>: ошибка (…)» в итоге; его вакансии в базе не меняются |
| нет `master_cv.md` | `_refresh`, шаг 2 | «No master_cv.md, evaluation skipped»; таблица пустая (окно тоже не находит резюме) |
| нет раздела Skills | `_refresh`, шаг 2 | «No Skills section in master_cv.md, evaluation skipped» |
| нет `lms.exe` / сервер не поднялся / модель не загрузилась | `_refresh`, шаг 4 | «LM Studio: …» в итоге; вакансии ждут следующего обновления |
| не удалась оценка одной вакансии | `_evaluate` | оценка остальных продолжается; в итоге «failed to evaluate: N» |
| нашу модель выгрузили посреди оценки | `_evaluate` → `_refresh` | проход останавливается; «LM Studio: модель job-finder выгружена (ответила …)» |
| любое другое исключение | `_run` | «Update failed, see job_finder.log» |

Во всех случаях подробности с трассировкой — в `job_finder.log`.

[← База данных](06-db.md) · [Оглавление](README.md) · [Дальше: окно и оформление →](08-window-and-style.md)
