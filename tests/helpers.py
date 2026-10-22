"""Shared test helpers: filled-in settings saved to the temporary test database, a PDF CV."""
from dataclasses import replace
from pathlib import Path

from PySide6.QtGui import QPainter, QPdfWriter

from job_finder import settings
from job_finder.settings import Settings


def use_settings(cv: Path, text: str = "Python developer", **overrides) -> Settings:
    """Write the CV file if it is missing, save complete settings pointing at it and return them."""
    if not cv.exists():
        cv.write_text(text, encoding="utf-8")
    s = replace(Settings(cv_path=str(cv), skills=["Python"], main_skill="Python", languages={"English": "B2"}),
                **overrides)
    settings.save(s)
    return s


def write_pdf(path: Path, text: str) -> None:
    """A one-page PDF with the text (needs a QApplication)."""
    writer = QPdfWriter(str(path))
    painter = QPainter(writer)
    painter.drawText(100, 100, text)
    painter.end()


def model_answer(score: int) -> dict:
    """A model answer the program counts to this score: nine "nice to have" requirements without technologies,
    score - 1 of them met (1 + 9 x met / 9)."""
    return {"summary": "", "blockers": [],
            "requirements": [{"requirement": f"skill {i}", "required": False, "match": "yes" if i < score - 1 else "no"}
                             for i in range(9)]}
