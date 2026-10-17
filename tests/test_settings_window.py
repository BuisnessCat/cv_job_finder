import pytest
from helpers import use_settings
from PySide6.QtWidgets import QApplication, QDialog

from job_finder import config, db, settings
from job_finder.settings import Settings
from job_finder.settings_window import SettingsDialog, Wizard, first_run


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


def test_wizard_next_waits_for_required_fields(app, cv):
    wizard = Wizard(Settings())
    assert wizard.step_label.text() == "Step 1 of 4" and wizard.next_button.isEnabled()  # Welcome
    wizard.next_button.click()
    assert wizard.step == 1 and not wizard.next_button.isEnabled()
    wizard.form.set_cv(str(cv))
    assert wizard.form.skills() == ["Python", "Docker"] and wizard.next_button.isEnabled()
    wizard.back_button.click()
    assert wizard.step == 0


def test_wizard_finishes_with_values(app, cv):
    wizard = Wizard(Settings())
    wizard.next_button.click()
    wizard.form.set_cv(str(cv))
    wizard.next_button.click()
    assert wizard.step_label.text() == "Step 3 of 4" and not wizard.next_button.isEnabled()  # keywords are required
    wizard.form.keywords_input.setText("python, fastapi")
    wizard.next_button.click()
    assert wizard.next_button.text() == "Start search" and not wizard.next_button.isEnabled()
    wizard.form.english_box.setCurrentText("B2")
    wizard.form.czech_box.setCurrentText("none")
    wizard.form.permit_no.setChecked(True)
    wizard.next_button.click()
    assert wizard.result() == QDialog.Accepted
    assert wizard.values() == Settings(cv_path=str(cv), skills=["Python", "Docker"], keywords=["python", "fastapi"],
                                       english="B2", czech="none", needs_permit=False)


def test_wizard_reports_unreadable_cv(app, tmp_path):
    wizard = Wizard(Settings())
    wizard.next_button.click()
    wizard.form.set_cv(str(tmp_path / "missing.pdf"))
    assert not wizard.form.cv_error.isHidden() and "not found" in wizard.form.cv_error.text()
    assert not wizard.next_button.isEnabled()


def test_first_run_saves_only_when_the_wizard_is_finished(app, cv, monkeypatch):
    monkeypatch.setattr(Wizard, "exec", lambda self: QDialog.Rejected)
    assert first_run(cv) is False and settings.load() is None  # closed early: nothing saved, the app quits
    done = Settings(cv_path=str(cv), skills=["Python"], keywords=["python"], english="B2", czech="none",
                    needs_permit=False)
    monkeypatch.setattr(Wizard, "exec", lambda self: QDialog.Accepted)
    monkeypatch.setattr(Wizard, "values", lambda self: done)
    assert first_run(cv) is True and settings.load() == done
    monkeypatch.setattr(Wizard, "exec", lambda self: pytest.fail("the wizard must not show again"))
    assert first_run(cv) is True


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
    dialog.form.skill_input.setText("SQL")
    dialog.form.add_skill_button.click()
    dialog.save_button.click()
    assert asked == [] and settings.load().skills == ["Python", "SQL"]
    dialog = SettingsDialog(settings.load())
    monkeypatch.setattr(dialog, "confirm_rescore", lambda jobs: asked.append(jobs) or False)
    dialog.form.city_box.setCurrentText("Brno")
    dialog.save_button.click()
    assert len(asked) == 1 and settings.load().city == "Praha"  # "Cancel" on the question saves nothing
    monkeypatch.setattr(dialog, "confirm_rescore", lambda jobs: True)
    dialog.save_button.click()
    assert settings.load().city == "Brno"


def test_settings_save_waits_for_required_fields(app, cv):
    dialog = SettingsDialog(use_settings(cv))
    assert dialog.save_button.isEnabled()
    dialog.form.keywords_input.setText("python, java, go, rust")  # 1–3 keywords
    assert not dialog.save_button.isEnabled()
    dialog.form.keywords_input.setText("")
    assert not dialog.save_button.isEnabled()
    dialog.form.keywords_input.setText("java")
    dialog.form.skills_list.selectAll()
    dialog.form.remove_skill_button.click()
    assert dialog.form.skills() == [] and not dialog.save_button.isEnabled()


def test_settings_keep_saved_skills_and_flag_a_moved_cv(app, cv, tmp_path):
    dialog = SettingsDialog(use_settings(cv, skills=["Python", "SQL"]))  # the CV mentions Docker, not SQL
    assert dialog.form.skills() == ["Python", "SQL"] and dialog.form.cv_error.isHidden()
    cv.unlink()
    dialog = SettingsDialog(settings.load())
    assert not dialog.form.cv_error.isHidden() and not dialog.save_button.isEnabled()
