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
