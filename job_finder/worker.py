"""Background refresh: fetch → skills filter → model evaluation (spec section 3)."""
import hashlib
import logging
import threading

from PySide6.QtCore import QObject, Signal

from job_finder import config, db, llm, skills, sources

log = logging.getLogger(__name__)


def read_cv() -> tuple[str, str] | None:
    """master_cv.md text and the evaluation key, or None if the file is missing.

    The key is SHA-256 of the CV together with the rules and the model: if any of them changed,
    earlier scores are outdated and jobs are evaluated again."""
    if not config.CV_PATH.exists():
        return None
    text = config.CV_PATH.read_text(encoding="utf-8")
    return text, hashlib.sha256(f"{text}\n{llm.fingerprint()}".encode("utf-8")).hexdigest()


def _join(summary: str, notes: list[str]) -> str:
    return "; ".join([summary, *notes])


class Worker(QObject):
    status = Signal(str)
    progress = Signal(int, int)  # evaluated, total
    evaluated = Signal(object)   # a row like db.make_row
    finished = Signal()

    def __init__(self):
        super().__init__()
        self.model_loaded = False

    def start(self) -> None:
        # daemon: the window closes right away without waiting for the current model request
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self) -> None:
        try:
            message = self._refresh()
            log.info(message)
            self.status.emit(message)
        except Exception:
            log.exception("Update crashed")
            self.status.emit("Update failed, see job_finder.log")
        finally:
            self.finished.emit()

    def _refresh(self) -> str:
        """One refresh. Returns the final status line."""
        self.status.emit("Loading jobs…")
        fetched, errors = sources.fetch_all()
        for name, jobs in fetched.items():
            db.save_jobs(name, jobs)
        log.info("Loaded: %s", {name: len(jobs) for name, jobs in fetched.items()})
        notes = [f"{name}: error ({error})" for name, error in errors.items()]

        cv = read_cv()
        if cv is None:
            return _join("No master_cv.md, evaluation skipped", notes)
        cv_text, cv_hash = cv
        skill_list = skills.load_skills(cv_text)
        if not skill_list:
            return _join("No Skills section in master_cv.md, evaluation skipped", notes)
        todo = [job for job in db.pending_jobs(cv_hash) if skills.matches(job, skill_list)]
        log.info("To evaluate: %d", len(todo))

        if todo:
            self.status.emit("Starting LM Studio…")
            self.model_loaded = True
            try:
                llm.prepare()
                failed = self._evaluate(todo, cv_text, cv_hash)
                if failed:
                    notes.append(f"failed to evaluate: {failed}")
            except Exception as error:
                log.exception("LM Studio unavailable")
                notes.append(f"LM Studio: {error}")
            finally:
                llm.release()
                self.model_loaded = False

        suitable = len(db.list_jobs(cv_hash, config.MIN_SCORE))
        evaluated = db.count_evaluated(cv_hash)
        matches = "match" if suitable == 1 else "matches"
        return _join(f"Done: {suitable} {matches} out of {evaluated} evaluated", notes)

    def _evaluate(self, todo: list[sources.Job], cv_text: str, cv_hash: str) -> int:
        """Evaluate jobs one by one; returns the number of failed evaluations."""
        failed = 0
        self.progress.emit(0, len(todo))
        for done, job in enumerate(todo, 1):
            try:
                evaluation = llm.evaluate(cv_text, job)
            except llm.ModelLost:
                raise  # nothing left to evaluate with: stop the whole pass
            except Exception:
                log.exception("Failed to evaluate %s", job.url)
                failed += 1
            else:
                db.save_evaluation(job.url, evaluation, cv_hash)
                self.evaluated.emit(db.make_row(job, evaluation, db.first_seen(job.url)))
            self.progress.emit(done, len(todo))
        return failed
