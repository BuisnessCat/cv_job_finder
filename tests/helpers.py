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
    s = replace(Settings(cv_path=str(cv), skills=["Python"], main_skill="Python", languages={"English": "B2"},
                         education="studying", experience="none", areas=["Backend"]), **overrides)
    settings.save(s)
    return s


def write_pdf(path: Path, text: str) -> None:
    """A one-page PDF with the text (needs a QApplication)."""
    writer = QPdfWriter(str(path))
    painter = QPainter(writer)
    painter.drawText(100, 100, text)
    painter.end()


def model_answer(score: int) -> dict:
    """The model's facts about a job that the program turns into this score, for a profile like use_settings's
    (Backend, junior, Praha): skills without technologies, so the ad's text doesn't matter."""
    def skills(yes, no):
        return [{"skill": f"skill {i}", "match": "yes" if i < yes else "no"} for i in range(yes + no)]

    facts = {"area": "Backend", "seniority": "junior", "min_years": 0, "degree": "none", "students_welcome": False,
             "languages": [], "workplace": "not stated", "place": "", "must_have": skills(2, 0), "nice_to_have": [],
             "about": "A job."}
    shapes = {10: dict(), 9: dict(must_have=skills(5, 0), nice_to_have=skills(0, 1)),
              8: dict(nice_to_have=skills(0, 1)), 7: dict(nice_to_have=skills(0, 2)), 6: dict(must_have=skills(1, 1)),
              5: dict(must_have=skills(1, 2)), 4: dict(must_have=skills(1, 3)), 3: dict(area="QA / testing"),
              2: dict(workplace="office", place="Brno"),
              1: dict(workplace="office", place="Brno", languages=[{"language": "German", "level": "C1"}])}
    return {**facts, **shapes[score]}
