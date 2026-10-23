from dataclasses import replace
import weakref

import pytest
from helpers import use_settings
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog

from job_finder import config, db, llm, lmstudio, ready_window, settings
from job_finder.cv_window import CvWindow
from job_finder.ready_window import ReadyPanel
from job_finder.settings import Settings
from job_finder.settings_window import SettingsDialog, Wizard, first_run
from job_finder.sources import Job


@pytest.fixture(autouse=True)
def tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "jobs.db")
    db.init()


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def cv(tmp_path):
    path = tmp_path / "cv.md"
    path.write_text("Python and Docker developer", encoding="utf-8")
    return path


def add_skill(form, name):
    form.skill_input.setText(name)
    QTest.keyClick(form.skill_input, Qt.Key_Return)


def to_last_step(wizard):
    for _ in range(3):
        wizard.next_button.click()
    fill_about_you(wizard.form)


def fill_about_you(form):
    """The last page's education and experience (the languages are each test's own)."""
    form.education_box.setCurrentIndex(form.education_box.findData("studying"))
    form.experience_box.setCurrentIndex(form.experience_box.findData("none"))


def test_wizard_next_waits_for_required_fields(app, cv):
    wizard = Wizard(Settings())
    assert wizard.step_label.text() == "Step 1 of 4" and wizard.next_button.isEnabled()  # Welcome
    wizard.next_button.click()
    assert wizard.step == 1 and not wizard.next_button.isEnabled()
    wizard.form.set_cv(str(cv))
    assert wizard.form.skill_chips() == ["Python", "Docker"]
    assert wizard.form.main_skill_box.currentText() == "Python" and wizard.next_button.isEnabled()
    wizard.back_button.click()
    assert wizard.step == 0


def test_wizard_reports_unreadable_cv(app, tmp_path):
    wizard = Wizard(Settings())
    wizard.next_button.click()
    wizard.form.set_cv(str(tmp_path / "missing.pdf"))
    assert not wizard.form.cv_error.isHidden() and "not found" in wizard.form.cv_error.text()
    assert not wizard.next_button.isEnabled()


def test_chips_add_remove_and_main_skill(app, cv):
    wizard = Wizard(Settings())
    wizard.next_button.click()
    form = wizard.form
    form.set_cv(str(cv))
    add_skill(form, "SQL")
    add_skill(form, "docker")  # already there in another case: not added
    assert form.skill_chips() == ["Python", "Docker", "SQL"] and form.skill_input.text() == ""
    form.remove_skill("Python")  # it was the main skill: a new guess from the rest
    assert form.main_skill_box.currentText() == "Docker"
    form.main_skill_box.setCurrentText("SQL")
    form.remove_skill("Docker")
    assert form.main_skill_box.currentText() == "SQL"  # the chosen main skill stays
    form.remove_skill("SQL")
    assert form.skill_chips() == [] and not wizard.next_button.isEnabled()


def test_levels_several_and_never_none(app):
    wizard = Wizard(Settings())
    buttons = {button.text(): button for button in wizard.form.level_buttons.buttons()}
    assert list(buttons) == ["Intern", "Junior", "Mid", "Senior", "Lead"]
    assert [name for name, button in buttons.items() if button.isChecked()] == ["Junior"]
    buttons["Intern"].click()
    assert wizard.form.values().levels == ["intern", "junior"]
    buttons["Intern"].click()
    buttons["Junior"].click()  # the last chosen level can't be turned off
    assert wizard.form.values().levels == ["junior"] and buttons["Junior"].isChecked()


def test_languages_rows(app, cv):
    wizard = Wizard(settings.initial(cv))
    to_last_step(wizard)
    form = wizard.form
    assert [(r.name_box.currentText(), r.level_box.currentText()) for r in form.language_rows] == [("English", "")]
    assert wizard.next_button.text() == "Start search" and not wizard.next_button.isEnabled()
    form.language_rows[0].level_box.setCurrentText("B2")
    assert wizard.next_button.isEnabled()
    form.add_language_button.click()
    assert len(form.language_rows) == 2 and not wizard.next_button.isEnabled()  # the new row is empty
    row = form.language_rows[1]
    row.name_box.setCurrentText("English")
    row.level_box.setCurrentText("C1")
    assert form.values().languages == {"English": "C1"}  # the same language twice: the last level
    row.remove_button.click()
    assert len(form.language_rows) == 1 and form.values().languages == {"English": "B2"}


def test_wizard_finishes_with_values(app, cv):
    wizard = Wizard(Settings())
    wizard.next_button.click()
    wizard.form.set_cv(str(cv))
    wizard.next_button.click()
    # Junior by default; Backend guessed from the CV's Python
    assert wizard.step_label.text() == "Step 3 of 4" and wizard.next_button.isEnabled()
    wizard.form.city_box.setCurrentText("Brno")
    wizard.next_button.click()
    fill_about_you(wizard.form)
    wizard.form.language_rows[0].level_box.setCurrentText("B2")
    wizard.next_button.click()
    assert wizard.result() == QDialog.Accepted
    assert wizard.values() == Settings(cv_path=str(cv), skills=["Python", "Docker"], main_skill="Python",
                                       city="Brno", languages={"English": "B2"}, education="studying",
                                       experience="none", areas=["Backend"])


def test_wizard_last_step_warns_when_jobs_were_scored(app, cv):
    wizard = Wizard(settings.initial(cv))
    to_last_step(wizard)
    assert wizard.rescore_note.isHidden()
    db.save_jobs("Jobicy", [Job(url="u", source="Jobicy", title="Dev", company="A", city="", published="2026-10-01",
                                description="")])
    db.save_evaluation("u", {"score": 6, "summary": "", "have": [], "missing": [], "risks": []}, "old-key")
    wizard = Wizard(settings.initial(cv))
    assert wizard.rescore_note.isHidden()  # only on the last step
    to_last_step(wizard)
    assert not wizard.rescore_note.isHidden()


def test_first_run_shows_wizard_only_for_missing_settings(app, cv, monkeypatch):
    shown = []

    def closed_early(wizard):
        shown.append(wizard.values())
        return QDialog.Rejected

    monkeypatch.setattr(Wizard, "exec", closed_early)
    assert first_run(cv) is False and settings.load() is None  # nothing saved, the app quits
    assert (shown[0].cv_path, shown[0].skills) == (str(cv), ["Python", "Docker"])  # prefilled from the CV
    db.put_settings({"cv_path": str(cv), "skills": ["Docker"], "city": "Brno", "keywords": ["python"],
                     "english": "B2"})  # saved by the first version
    assert first_run(cv) is False
    assert (shown[1].skills, shown[1].city, shown[1].main_skill) == (["Docker"], "Brno", "Docker")
    done = Settings(cv_path=str(cv), skills=["Docker"], main_skill="Docker", languages={"English": "B2"},
                    education="none", experience="none", areas=["DevOps / cloud"])
    monkeypatch.setattr(Wizard, "exec", lambda wizard: QDialog.Accepted)
    monkeypatch.setattr(Wizard, "values", lambda wizard: done)
    assert first_run(cv) is True and replace(settings.load(), cv_stamp="") == done  # + which file was copied
    monkeypatch.setattr(Wizard, "exec", lambda wizard: pytest.fail("the wizard must not show again"))
    assert first_run(cv) is True


def test_settings_still_needed_and_pages(app, cv):
    dialog = SettingsDialog(use_settings(cv))
    assert [dialog.nav.item(i).text() for i in range(dialog.nav.count())] == [
        "Your CV", "What you're looking for", "About you"]
    assert dialog.save_button.isEnabled() and dialog.missing_label.text() == ""
    dialog.form.language_rows[0].level_box.setCurrentIndex(-1)
    assert not dialog.save_button.isEnabled() and dialog.missing_label.text() == "Still needed: language levels"
    dialog.nav.setCurrentRow(2)
    assert dialog.pages.currentIndex() == 2


def test_settings_cancel_changes_nothing(app, cv):
    s = use_settings(cv)
    dialog = SettingsDialog(s)
    dialog.form.city_box.setCurrentText("Brno")
    dialog.cancel_button.click()
    assert settings.load() == s


def test_rescore_question_only_for_a_new_cv(app, cv, monkeypatch, tmp_path):
    use_settings(cv)
    asked = []
    dialog = SettingsDialog(settings.load())
    monkeypatch.setattr(dialog, "confirm_rescore", lambda jobs: asked.append(jobs) or False)
    add_skill(dialog.form, "SQL")
    dialog.form.main_skill_box.setCurrentText("SQL")
    dialog.form.city_box.setCurrentText("Brno")
    dialog.form.education_box.setCurrentIndex(dialog.form.education_box.findData("bachelor"))
    dialog.form.language_rows[0].level_box.setCurrentText("C1")
    dialog.save_button.click()  # the program compares the jobs with these again in an instant
    s = settings.load()
    assert asked == [] and (s.skills, s.city, s.education, s.languages) == (
        ["Python", "SQL"], "Brno", "bachelor", {"English": "C1"})
    other = tmp_path / "other.md"
    other.write_text("Python and SQL developer", encoding="utf-8")
    dialog = SettingsDialog(settings.load())
    monkeypatch.setattr(dialog, "confirm_rescore", lambda jobs: asked.append(jobs) or False)
    dialog.form.set_cv(str(other))
    dialog.save_button.click()
    assert len(asked) == 1 and settings.load().cv_path == str(cv)  # "Cancel" on the question saves nothing
    monkeypatch.setattr(dialog, "confirm_rescore", lambda jobs: True)
    dialog.save_button.click()
    assert settings.load().cv_path == str(other)


def test_save_keeps_hidden_thresholds(app, cv):
    dialog = SettingsDialog(use_settings(cv, min_score=7, stale_days=10, stale_job_days=30))
    add_skill(dialog.form, "SQL")
    dialog.save_button.click()
    s = settings.load()
    assert (s.min_score, s.stale_days, s.stale_job_days) == (7, 10, 30)
    wizard = Wizard(Settings())
    assert (wizard.values().min_score, wizard.values().stale_days, wizard.values().stale_job_days) == (5, 14, 21)


def test_picking_a_cv_again_asks_before_replacing_skills(app, cv, tmp_path, monkeypatch):
    dialog = SettingsDialog(use_settings(cv, skills=["Python", "SQL"], main_skill="SQL"))
    other = tmp_path / "new.md"
    other.write_text("Python and Docker", encoding="utf-8")
    asked = []
    monkeypatch.setattr(dialog.form, "confirm_replace_skills", lambda: asked.append("no") or False)
    dialog.form.set_cv(str(other))
    assert asked == ["no"] and dialog.form.skill_chips() == ["Python", "SQL"]
    assert dialog.form.main_skill_box.currentText() == "SQL"
    monkeypatch.setattr(dialog.form, "confirm_replace_skills", lambda: asked.append("yes") or True)
    dialog.form.set_cv(str(other))
    assert dialog.form.skill_chips() == ["Python", "Docker"]
    assert dialog.form.main_skill_box.currentText() == "Python"  # SQL is gone: a new guess
    asked.clear()
    dialog.form.remove_skill("Python")
    add_skill(dialog.form, "Python")  # the chips in the user's own order
    dialog.form.set_cv(str(cv))  # the found skills are the same as the chips: nothing to ask, nothing changes
    assert asked == [] and dialog.form.skill_chips() == ["Docker", "Python"]


def test_typed_names_match_known_ones(app, cv):
    wizard = Wizard(Settings())
    add_skill(wizard.form, "python")
    assert wizard.form.skill_chips() == ["Python"]
    form = wizard.form
    form.language_rows[0].name_box.setCurrentText("english")
    form.language_rows[0].level_box.setCurrentText("B2")
    form.add_language_button.click()
    form.language_rows[1].name_box.setCurrentText("English")
    form.language_rows[1].level_box.setCurrentText("C1")
    assert form.values().languages == {"English": "C1"}


def test_still_needed_names_the_language_problem(app, cv):
    dialog = SettingsDialog(use_settings(cv))
    dialog.form.add_language_button.click()
    assert dialog.missing_label.text() == "Still needed: a language name"
    dialog.form.language_rows[1].name_box.setCurrentText("Czech")
    assert dialog.missing_label.text() == "Still needed: language levels"


def test_settings_flag_a_moved_cv(app, cv):
    s = use_settings(cv, skills=["Python", "SQL"])  # saved skills are kept, not found again
    assert SettingsDialog(s).form.skill_chips() == ["Python", "SQL"]
    cv.unlink()
    dialog = SettingsDialog(s)
    assert not dialog.form.cv_error.isHidden() and not dialog.save_button.isEnabled()
    assert "CV file" in dialog.missing_label.text()
    dialog.cancel_button.click()
    assert dialog.result() == QDialog.Rejected


def test_windows_are_freed_when_closed(app, cv):
    # A window kept alive by its own signal connections outlives the app and crashes Python at exit
    use_settings(cv)
    for make in (lambda: Wizard(settings.load()), lambda: SettingsDialog(settings.load()), CvWindow):
        window = make()
        if hasattr(window, "form"):
            window.form.add_language_button.click()  # language rows and skill chips connect their buttons too
        ref = weakref.ref(window)
        del window
        assert ref() is None, make


def test_wizard_asks_for_the_model_first(app, cv, monkeypatch):
    monkeypatch.setattr(lmstudio, "lms_installed", lambda: True)
    monkeypatch.setattr(lmstudio, "model_file_present", lambda model: False)
    monkeypatch.setattr(llm, "downloaded_models", lambda: set())
    monkeypatch.setattr(ready_window, "vram_gb", lambda: 12.0)
    wizard = Wizard(settings.initial(cv), config.MODEL)  # LM Studio or the model is missing
    assert len(wizard.steps) == 5 and wizard.step_label.text() == "Step 1 of 5"
    wizard.next_button.click()
    assert isinstance(wizard.pages.currentWidget(), ReadyPanel)
    assert not wizard.pages.currentWidget().download_button.isHidden()
    assert wizard.next_button.isEnabled()  # the setup goes on while the model downloads
    wizard.next_button.click()
    assert wizard.pages.currentIndex() == 2 and wizard.step_label.text() == "Step 3 of 5"  # Your CV
    assert len(Wizard(settings.initial(cv)).steps) == 4  # everything is there: no model step


def test_first_run_passes_the_model_to_the_wizard(app, cv, monkeypatch):
    models = []
    monkeypatch.setattr(Wizard, "exec", lambda wizard: models.append(len(wizard.steps)) or QDialog.Rejected)
    first_run(cv, config.MODEL)
    first_run(cv)
    assert models == [5, 4]


def test_a_gone_cv_file_with_a_copy_still_saves(app, cv):
    s = Settings(cv_path=str(cv), skills=["Python"], main_skill="Python", languages={"English": "B2"},
                 education="studying", experience="none", areas=["Backend"])
    settings.save(settings.store_cv(s, cv.read_text(encoding="utf-8")))
    cv.unlink()
    dialog = SettingsDialog(settings.load())
    assert dialog.save_button.isEnabled()  # the scoring goes on with the copy
    assert "saved copy" in dialog.form.cv_error.text()


def test_the_chosen_cv_is_copied_when_the_setup_is_saved(app, cv, monkeypatch):
    done = Settings(cv_path=str(cv), skills=["Python"], main_skill="Python", languages={"English": "B2"},
                    education="studying", experience="none", areas=["Backend"])
    monkeypatch.setattr(Wizard, "exec", lambda wizard: QDialog.Accepted)
    monkeypatch.setattr(Wizard, "values", lambda wizard: done)
    assert first_run(cv)
    assert config.CV_COPY.read_text(encoding="utf-8") == "Python and Docker developer"
    assert settings.load().cv_stamp == settings.file_stamp(str(cv))
    cv.write_text("Python, Docker and SQL developer", encoding="utf-8")
    dialog = SettingsDialog(settings.load())
    dialog.save()  # the file was read again when the dialog opened
    assert config.CV_COPY.read_text(encoding="utf-8") == "Python, Docker and SQL developer"


def test_the_profile_in_the_wizard(app, cv):
    wizard = Wizard(settings.initial(cv))  # Python and Docker in the CV: Backend is guessed
    form = wizard.form
    wizard.next_button.click()  # Your CV
    wizard.next_button.click()  # What you're looking for
    backend = form.area_buttons.button(settings.AREAS.index("Backend"))
    assert backend.isChecked()
    backend.click()
    assert not wizard.next_button.isEnabled()  # at least one area
    form.area_buttons.button(settings.AREAS.index("Data / analytics")).click()
    wizard.next_button.click()  # About you
    assert wizard.step_label.text() == "Step 4 of 4" and not wizard.next_button.isEnabled()
    fill_about_you(form)
    form.language_rows[0].level_box.setCurrentText("B2")
    assert wizard.next_button.isEnabled()
    values = wizard.values()
    assert (values.education, values.experience, values.areas) == ("studying", "none", ["Data / analytics"])


def test_settings_show_the_saved_profile(app, cv):
    s = Settings(cv_path=str(cv), skills=["Python"], main_skill="Python", languages={"English": "B2"},
                 education="bachelor", experience="1-2", areas=["Backend", "QA / testing"])
    dialog = SettingsDialog(s)
    assert dialog.form.education_box.currentData() == "bachelor"
    assert dialog.form.experience_box.currentData() == "1-2"
    assert dialog.form.values().areas == ["Backend", "QA / testing"]
    assert [dialog.nav.item(i).text() for i in range(dialog.nav.count())] == [
        "Your CV", "What you're looking for", "About you"]
