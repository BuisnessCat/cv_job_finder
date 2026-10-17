"""Shared test helpers: filled-in settings saved to the temporary test database."""
from dataclasses import replace
from pathlib import Path

from job_finder import settings
from job_finder.settings import Settings


def use_settings(cv: Path, text: str = "Python developer", **overrides) -> Settings:
    """Write the CV file if it is missing, save complete settings pointing at it and return them."""
    if not cv.exists():
        cv.write_text(text, encoding="utf-8")
    s = replace(Settings(cv_path=str(cv), skills=["Python"], keywords=["python"], english="B2", czech="none",
                         needs_permit=False), **overrides)
    settings.save(s)
    return s
