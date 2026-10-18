import weakref

import pytest
from PySide6.QtWidgets import QApplication

from job_finder import config, llm, ready_window
from job_finder.ready_window import ReadyDialog

MODEL = config.MODEL


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def machine(monkeypatch):
    """A fake computer: is LM Studio installed, which models are downloaded, what a download does."""
    state = {"lms": True, "models": set(), "downloads": [], "result": 0, "vram": 12.0}
    monkeypatch.setattr(ready_window, "lms_installed", lambda: state["lms"])
    monkeypatch.setattr(llm, "downloaded_models", lambda: set(state["models"]))
    monkeypatch.setattr(ready_window, "vram_gb", lambda: state["vram"])

    def download(model):
        state["downloads"].append(model)
        if state["result"] == 0:
            state["models"].add(model)
        return state["result"]

    monkeypatch.setattr(ready_window, "download_model", download)
    monkeypatch.setattr(ready_window, "start_thread", lambda target: target())  # the download runs right away
    return state


def test_everything_ready(machine):
    assert not ready_window.everything_ready(MODEL)
    machine["models"].add(MODEL)
    assert ready_window.everything_ready(MODEL)  # nothing to show: the app opens as before
    machine["lms"] = False
    assert not ready_window.everything_ready(MODEL)


def test_without_lm_studio(app, machine, monkeypatch):
    machine["lms"] = False
    opened = []
    monkeypatch.setattr(ready_window.QDesktopServices, "openUrl", lambda url: opened.append(url.toString()))
    dialog = ReadyDialog(MODEL)
    assert not dialog.get_button.isHidden() and not dialog.download_button.isEnabled()
    assert "not installed" in dialog.lms_status.text() and dialog.continue_button.text() == "Continue anyway"
    dialog.get_button.click()
    assert opened == ["https://lmstudio.ai"]
    machine["lms"] = True  # installed and opened once
    dialog.check_button.click()
    assert dialog.get_button.isHidden() and dialog.download_button.isEnabled()


def test_download_model(app, machine):
    dialog = ReadyDialog(MODEL)
    assert "Ministral 3 8B" in dialog.model_status.text() and "12 GB" in dialog.model_status.text()
    assert dialog.continue_button.text() == "Continue anyway"
    dialog.download_button.click()
    assert machine["downloads"] == [MODEL]
    assert dialog.continue_button.text() == "Continue" and dialog.download_button.isHidden()


def test_failed_download_can_be_retried(app, machine):
    machine["result"] = 1  # e.g. no network
    dialog = ReadyDialog(MODEL)
    dialog.download_button.click()
    assert "failed" in dialog.download_note.text() and dialog.download_button.isEnabled()
    assert dialog.continue_button.isEnabled()  # the app can still be opened


def test_small_model_is_explained(app, machine):
    machine["vram"] = 6.0
    dialog = ReadyDialog(config.SMALL_MODEL)
    assert "Ministral 3 3B" in dialog.model_status.text() and "weaker" in dialog.model_note.text()


def test_dialog_is_freed(app, machine):
    dialog = ReadyDialog(MODEL)
    ref = weakref.ref(dialog)
    del dialog
    assert ref() is None
