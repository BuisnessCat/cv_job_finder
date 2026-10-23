"""Background refresh: fetch → skills filter → model evaluation (spec section 3)."""
import hashlib
import logging
import threading
from datetime import date

from PySide6.QtCore import QObject, Signal

from job_finder import busy, config, db, freshness, grounding, llm, lmstudio, settings, skills, sources
from job_finder.settings import Settings

log = logging.getLogger(__name__)


def cv_key(text: str, s: Settings) -> str:
    """SHA-256 of the CV with the rules and the model: if any of them changes, earlier scores are outdated."""
    return hashlib.sha256(f"{text}\n{llm.fingerprint(s)}".encode("utf-8")).hexdigest()


def read_cv(s: Settings | None) -> tuple[str, str] | None:
    """CV text (from the app's copy) and the evaluation key, or None without settings or when it can't be read."""
    if s is None:
        return None
    try:
        text = settings.cv_text(s)
    except settings.CvError:
        return None
    return text, cv_key(text, s)


def recount(s: Settings) -> int:
    """Give every job scored under the current CV its verdict again from the model's saved facts, without the
    model (spec section 21.4): after Settings change. Older scores without facts stay. Returns how many."""
    cv = read_cv(s)
    if cv is None:
        return 0
    known = grounding.cv_technologies(cv[0])
    new = [(job.url, grounding.verdict(evaluation["extraction"], job, known, s))
           for job, evaluation in db.scored_jobs(cv[1]) if isinstance(evaluation.get("extraction"), dict)]
    db.save_evaluations(new, cv[1])
    return len(new)


def too_old(job: sources.Job, today: date) -> bool:
    """Older than OLD_JOB_DAYS by the site's date: not worth the model's time. A job without a date is scored."""
    age = freshness.age_days(job.published, today)
    return age is not None and age > config.OLD_JOB_DAYS


def _join(summary: str, notes: list[str]) -> str:
    return "; ".join([summary, *notes])


class Worker(QObject):
    status = Signal(str)
    progress = Signal(int, int)  # evaluated, total
    evaluated = Signal(object)   # a row like db.make_row
    finished = Signal()

    pause_check = staticmethod(busy.windows_busy)  # a full-screen game: stop scoring, it needs the graphics card

    def __init__(self):
        super().__init__()
        self.model_loaded = False
        self.paused = False  # the last pass stopped for a full-screen app; the window tries again later
        self.model_missing = False  # the last pass had jobs to score but no LM Studio or model: the window offers it
        self.manual = False  # started by the user (the button, Start search, Save in Settings): a big pass runs too
        self.waiting = 0  # jobs of a big pass that waits for the user (the window offers "Start scoring")
        self.cancelled = False  # the settings were saved during the pass: it stops after the current job
        self.cv_changed = False  # the CV file was edited during the pass: it stops and starts over

    def start(self, manual: bool = False) -> None:
        self.manual, self.cancelled = manual, False
        # daemon: the window closes right away without waiting for the current model request
        threading.Thread(target=self._run, daemon=True).start()

    def cancel(self) -> None:
        """Stop the running pass after the job it is scoring (Save in Settings)."""
        self.cancelled = True

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
        self.paused = self.model_missing = self.cv_changed = False
        self.waiting = 0
        s = settings.load()
        if s is None or settings.missing(s):
            return "Finish the setup in Settings first"
        self.status.emit("Loading jobs…")
        fetched, errors = sources.fetch_all(s)
        for name, jobs in fetched.items():
            # Remote turned off: the remote-only sites weren't asked, their jobs aren't "no longer listed"
            db.save_jobs(name, jobs, fetched=s.remote or name not in sources.REMOTE_ONLY)
        log.info("Loaded: %s", {name: len(jobs) for name, jobs in fetched.items()})
        notes = [f"{name}: error ({error})" for name, error in errors.items()]

        try:
            s, cv_note = settings.sync_cv(s)  # an edited CV file is copied again; a gone one leaves the copy
            cv_text = settings.cv_text(s)
        except settings.CvError as error:
            return _join(f"Can't read your CV: {error}. Check it in Settings", notes)
        if cv_note:
            notes.append(cv_note)
        cv_hash = cv_key(cv_text, s)
        skill_list = s.skills
        if not skill_list:
            return _join("No skills in Settings, evaluation skipped", notes)
        today = date.today()
        todo = [job for job in db.pending_jobs(cv_hash, config.GONE_DAYS)
                if skills.matches(job, skill_list) and not too_old(job, today)]
        log.info("To evaluate: %d", len(todo))

        if todo and not lmstudio.everything_ready(llm.model_name(s)):
            # Loading a model that isn't there only gives a long error from LM Studio
            self.model_missing = True
            if not lmstudio.lms_installed():
                return _join("LM Studio isn't installed: click Get AI model", notes)
            if lmstudio.downloading:
                return _join("Downloading the AI model: the jobs will be scored when it has finished", notes)
            return _join("The AI model isn't downloaded yet: click Get AI model", notes)
        if self.cancelled:
            return _join("Stopped: the settings changed, starting again", notes)
        if len(todo) > config.BIG_PASS_JOBS and not self.manual:  # e.g. after an update: not without the user
            self.waiting = len(todo)
            minutes = max(1, round(len(todo) * config.SECONDS_PER_JOB / 60))
            return _join(f"{len(todo)} jobs to score (about {minutes} min): click Start scoring", notes)
        if todo:
            self.status.emit("Starting LM Studio…")
            self.model_loaded = True
            try:
                llm.prepare(llm.model_name(s))
                failed = self._evaluate(todo, cv_text, cv_hash, s)
                if failed:
                    notes.append(f"failed to evaluate: {failed}")
            except Exception as error:
                log.exception("LM Studio unavailable")
                notes.append(f"LM Studio: {error}")
            finally:
                llm.release()
                self.model_loaded = False

        if self.cancelled:
            return _join("Stopped: the settings changed, starting again", notes)
        if self.cv_changed:
            return _join("Your CV changed: starting again with the new version", notes)
        if self.paused:
            return _join("Paused while a full-screen app runs; the rest will be scored later", notes)
        suitable = len(db.list_jobs(cv_hash, s.min_score))
        evaluated = db.count_evaluated(cv_hash)
        matches = "match" if suitable == 1 else "matches"
        return _join(f"Done: {suitable} {matches} out of {evaluated} evaluated", notes)

    def _evaluate(self, todo: list[sources.Job], cv_text: str, cv_hash: str, s: Settings) -> int:
        """Evaluate jobs one by one; returns the number of failed evaluations. The model gets the technologies the
        program found in each ad and takes the facts out of it; the program gives the verdict."""
        failed = 0
        known = grounding.cv_technologies(cv_text)
        rules = llm.render_rules(s)
        self.progress.emit(0, len(todo))
        for done, job in enumerate(todo, 1):
            if self.cancelled:
                break
            stamp = settings.file_stamp(s.cv_path)
            if stamp is not None and stamp != s.cv_stamp:  # the CV file was saved in its own program
                self.cv_changed = True
                break
            if self.pause_check():
                self.paused = True
                break
            try:
                answer = llm.evaluate(cv_text, job, rules, grounding.facts(job, known))
                # The verdict follows the settings saved now, also when Settings were saved during the pass
                evaluation = grounding.verdict(answer, job, known, settings.load() or s)
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
