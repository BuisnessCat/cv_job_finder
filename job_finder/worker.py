"""Фоновое обновление: загрузка → отсев по навыкам → оценка моделью (раздел 3 спека)."""
import hashlib
import logging
import threading

from PySide6.QtCore import QObject, Signal

from job_finder import config, db, llm, skills, sources

log = logging.getLogger(__name__)


def read_cv() -> tuple[str, str] | None:
    """Текст master_cv.md и его SHA-256 или None, если файла нет."""
    if not config.CV_PATH.exists():
        return None
    text = config.CV_PATH.read_text(encoding="utf-8")
    return text, hashlib.sha256(text.encode("utf-8")).hexdigest()


def _join(summary: str, notes: list[str]) -> str:
    return "; ".join([summary, *notes])


class Worker(QObject):
    status = Signal(str)
    progress = Signal(int, int)  # оценено, всего
    evaluated = Signal(object)   # строка вида db.make_row
    finished = Signal()

    def __init__(self):
        super().__init__()
        self.model_loaded = False

    def start(self) -> None:
        # daemon: окно закрывается сразу, не дожидаясь текущего запроса к модели
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self) -> None:
        try:
            message = self._refresh()
            log.info(message)
            self.status.emit(message)
        except Exception:
            log.exception("Обновление упало")
            self.status.emit("Ошибка обновления, подробности в job_finder.log")
        finally:
            self.finished.emit()

    def _refresh(self) -> str:
        """Одно обновление. Возвращает итоговую строку состояния."""
        self.status.emit("Загружаю вакансии…")
        fetched, errors = sources.fetch_all()
        for name, jobs in fetched.items():
            db.save_jobs(name, jobs)
        log.info("Загружено: %s", {name: len(jobs) for name, jobs in fetched.items()})
        notes = [f"{name}: ошибка ({error})" for name, error in errors.items()]

        cv = read_cv()
        if cv is None:
            return _join("Нет файла master_cv.md, оценка не запущена", notes)
        cv_text, cv_hash = cv
        skill_list = skills.load_skills(cv_text)
        if not skill_list:
            return _join("В master_cv.md не найден раздел Skills, оценка не запущена", notes)
        todo = [job for job in db.pending_jobs(cv_hash) if skills.matches(job, skill_list)]
        log.info("К оценке: %d", len(todo))

        if todo:
            self.status.emit("Запускаю LM Studio…")
            self.model_loaded = True
            try:
                llm.prepare()
                failed = self._evaluate(todo, cv_text, cv_hash)
                if failed:
                    notes.append(f"не удалось оценить: {failed}")
            except Exception as error:
                log.exception("LM Studio недоступна")
                notes.append(f"LM Studio: {error}")
            finally:
                llm.release()
                self.model_loaded = False

        suitable = len(db.list_jobs(cv_hash, config.MIN_SCORE))
        return _join(f"Готово: {suitable} подходящих", notes)

    def _evaluate(self, todo: list[sources.Job], cv_text: str, cv_hash: str) -> int:
        """Оценить вакансии по одной; возвращает число неудачных оценок."""
        failed = 0
        self.progress.emit(0, len(todo))
        for done, job in enumerate(todo, 1):
            try:
                evaluation = llm.evaluate(cv_text, job)
            except llm.ModelLost:
                raise  # дальше оценивать нечем — останавливаем весь проход
            except Exception:
                log.exception("Не удалось оценить %s", job.url)
                failed += 1
            else:
                db.save_evaluation(job.url, evaluation, cv_hash)
                self.evaluated.emit(db.make_row(job, evaluation))
            self.progress.emit(done, len(todo))
        return failed
