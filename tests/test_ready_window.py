import weakref

import pytest
from PySide6.QtWidgets import QApplication

from job_finder import config, llm, lmstudio, ready_window
from job_finder.ready_window import ReadyDialog

MODEL = config.MODEL


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def machine(monkeypatch):
    """A fake computer: is LM Studio installed, which models are downloaded, what a download does."""
    state = {"lms": True, "models": set(), "files": set(), "downloads": [], "result": 0, "vram": 12.0}
    monkeypatch.setattr(lmstudio, "lms_installed", lambda: state["lms"])
    monkeypatch.setattr(lmstudio, "model_file_present", lambda model: model in state["files"])
    monkeypatch.setattr(llm, "downloaded_models", lambda: set(state["models"]))
    monkeypatch.setattr(ready_window, "vram_gb", lambda: state["vram"])

    def download(model):
        state["downloads"].append(model)
        if state["result"] == 0:
            state["models"].add(model)
        return state["result"]

    monkeypatch.setattr(lmstudio, "download_model", download)
    monkeypatch.setattr(ready_window, "start_thread", lambda target: target())  # the download runs right away
    return state


def test_everything_ready(machine):
    assert not lmstudio.everything_ready(MODEL)
    machine["models"].add(MODEL)
    assert lmstudio.everything_ready(MODEL)  # nothing to show: the app opens as before
    machine["lms"] = False
    assert not lmstudio.everything_ready(MODEL)


def test_without_lm_studio(app, machine, monkeypatch):
    machine["lms"] = False
    opened = []
    monkeypatch.setattr(ready_window.QDesktopServices, "openUrl", lambda url: opened.append(url.toString()))
    dialog = ReadyDialog(MODEL)
    assert not dialog.panel.get_button.isHidden() and not dialog.panel.download_button.isEnabled()
    assert "not installed" in dialog.panel.lms_status.text() and dialog.continue_button.text() == "Continue anyway"
    dialog.panel.get_button.click()
    assert opened == ["https://lmstudio.ai"]
    machine["lms"] = True  # installed and opened once
    dialog.panel.check_button.click()
    assert dialog.panel.get_button.isHidden() and dialog.panel.download_button.isEnabled()


def test_download_model(app, machine):
    dialog = ReadyDialog(MODEL)
    assert "Ministral 3 8B" in dialog.panel.model_status.text() and "12 GB" in dialog.panel.model_status.text()
    assert dialog.continue_button.text() == "Continue anyway"
    dialog.panel.download_button.click()
    assert machine["downloads"] == [MODEL]
    assert dialog.continue_button.text() == "Continue" and dialog.panel.download_button.isHidden()


def test_failed_download_can_be_retried(app, machine):
    machine["result"] = 1  # e.g. no network
    dialog = ReadyDialog(MODEL)
    dialog.panel.download_button.click()
    assert "failed" in dialog.panel.download_note.text() and dialog.panel.download_button.isEnabled()
    assert dialog.continue_button.isEnabled()  # the app can still be opened


def test_small_model_is_explained(app, machine):
    machine["vram"] = 6.0
    dialog = ReadyDialog(config.SMALL_MODEL)
    assert "Ministral 3 3B" in dialog.panel.model_status.text() and "weaker" in dialog.panel.model_note.text()


def test_dialog_is_freed(app, machine):
    dialog = ReadyDialog(MODEL)
    ref = weakref.ref(dialog)
    del dialog
    assert ref() is None


def test_model_file_is_enough_without_running_lms(machine, monkeypatch):
    machine["files"].add(MODEL)  # the model's file is in LM Studio's downloads folder
    monkeypatch.setattr(llm, "downloaded_models", lambda: pytest.fail("lms must not run: it would wake LM Studio"))
    assert lmstudio.everything_ready(MODEL)


def test_model_file_present(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LMS_HOME", tmp_path / ".lmstudio")
    models = tmp_path / "Models"  # moved in LM Studio's settings
    (tmp_path / ".lmstudio").mkdir()
    (tmp_path / ".lmstudio" / "settings.json").write_text(
        '{"downloadsFolder": "' + str(models).replace("\\", "\\\\") + '"}', encoding="utf-8")
    folder = models / "lmstudio-community" / "Ministral-3-8B-Instruct-2512-GGUF"
    folder.mkdir(parents=True)
    (folder / "mmproj-Ministral-3-3B-Instruct-2512-F16.gguf").write_text("")  # a helper file, not the model
    (folder / "Ministral-3-8B-Instruct-2512-Q4_K_M.gguf").write_text("")
    assert lmstudio.model_file_present(config.MODEL)
    assert not lmstudio.model_file_present(config.SMALL_MODEL)
    (tmp_path / ".lmstudio" / "settings.json").unlink()  # no settings: the default folder, which is empty
    assert not lmstudio.model_file_present(config.MODEL)


def test_one_download_for_the_whole_app(app, machine, monkeypatch):
    assert ready_window.downloader() is ready_window.downloader()
    later = []
    monkeypatch.setattr(ready_window, "start_thread", later.append)  # the download is still running
    first = ReadyDialog(MODEL)
    first.panel.download_button.click()
    second = ReadyDialog(MODEL)  # e.g. opened from the main window while the wizard's download runs
    assert ready_window.downloader().running and lmstudio.downloading
    assert not second.panel.download_button.isEnabled() and not second.panel.progress.isHidden()
    second.panel.download_button.click()
    assert len(later) == 1  # one download, not two
    later[0]()  # it finishes
    assert not ready_window.downloader().running and not lmstudio.downloading
    assert machine["downloads"] == [MODEL]
    assert second.panel.download_button.isHidden() and second.continue_button.text() == "Continue"
