"""Qt runs without a screen in tests. With the system fonts text has its real width, which the width guards need."""
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
FONTS = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
if FONTS.is_dir():
    os.environ.setdefault("QT_QPA_FONTDIR", str(FONTS))


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def usual_model(monkeypatch):
    # Not this computer's graphics card: the model (and so every evaluation key) is the same on any machine
    from job_finder import config, hardware
    monkeypatch.setattr(hardware, "default_model", lambda: config.MODEL)


@pytest.fixture(autouse=True)
def own_downloader(monkeypatch):
    # Every test gets its own model downloader: a window left from an earlier test never hears a later download
    from job_finder import lmstudio, ready_window
    monkeypatch.setattr(ready_window, "_downloader", None)
    monkeypatch.setattr(lmstudio, "downloading", False)


@pytest.fixture(autouse=True)
def cv_copy_in_tmp(tmp_path, monkeypatch):
    # The app's copy of the CV: never the real one in the data folder
    from job_finder import config
    monkeypatch.setattr(config, "CV_COPY", tmp_path / "cv-copy" / "cv.md")
