import weakref

import pytest
from helpers import use_settings
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog

from job_finder import config, db, settings
from job_finder.cv_window import CvWindow
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
    assert wizard.step_label.text() == "Step 3 of 4" and wizard.next_button.isEnabled()  # junior by default
    wizard.form.city_box.setCurrentText("Brno")
    wizard.next_button.click()
    wizard.form.language_rows[0].level_box.setCurrentText("B2")
    wizard.next_button.click()
    assert wizard.result() == QDialog.Accepted
    assert wizard.values() == Settings(cv_path=str(cv), skills=["Python", "Docker"], main_skill="Python",
                                       city="Brno", languages={"English": "B2"})


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
    done = Settings(cv_path=str(cv), skills=["Docker"], main_skill="Docker", languages={"English": "B2"})
    monkeypatch.setattr(Wizard, "exec", lambda wizard: QDialog.Accepted)
    monkeypatch.setattr(Wizard, "values", lambda wizard: done)
    assert first_run(cv) is True and settings.load() == done
    monkeypatch.setattr(Wizard, "exec", lambda wizard: pytest.fail("the wizard must not show again"))
    assert first_run(cv) is True


def test_settings_still_needed_and_pages(app, cv):
    dialog = SettingsDialog(use_settings(cv))
    assert [dialog.nav.item(i).text() for i in range(dialog.nav.count())] == [
        "Your CV", "What you're looking for", "Languages"]
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


def test_rescore_question_only_for_scoring_fields(app, cv, monkeypatch):
    use_settings(cv)
    asked = []
    dialog = SettingsDialog(settings.load())
    monkeypatch.setattr(dialog, "confirm_rescore", lambda jobs: asked.append(jobs) or False)
    add_skill(dialog.form, "SQL")
    dialog.form.main_skill_box.setCurrentText("SQL")
    dialog.save_button.click()
    assert asked == [] and (settings.load().skills, settings.load().main_skill) == (["Python", "SQL"], "SQL")
    dialog = SettingsDialog(settings.load())
    monkeypatch.setattr(dialog, "confirm_rescore", lambda jobs: asked.append(jobs) or False)
    dialog.form.city_box.setCurrentText("Brno")
    dialog.save_button.click()
    assert len(asked) == 1 and settings.load().city == "Praha"  # "Cancel" on the question saves nothing
    monkeypatch.setattr(dialog, "confirm_rescore", lambda jobs: True)
    dialog.save_button.click()
    assert settings.load().city == "Brno"


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
