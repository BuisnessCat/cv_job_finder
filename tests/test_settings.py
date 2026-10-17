from dataclasses import replace

import pytest
from PySide6.QtGui import QPainter, QPdfWriter
from PySide6.QtWidgets import QApplication

from job_finder import config, db, settings
from job_finder.settings import Settings


@pytest.fixture(autouse=True)
def tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "jobs.db")
    db.init()


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def write_pdf(path, text):
    writer = QPdfWriter(str(path))
    painter = QPainter(writer)
    painter.drawText(100, 100, text)
    painter.end()


def filled(**overrides):
    values = dict(cv_path="cv.md", skills=["Python"], keywords=["python"], english="B2", czech="none",
                  needs_permit=False)
    return Settings(**{**values, **overrides})


def test_no_settings_until_saved():
    assert settings.load() is None
    s = filled()
    settings.save(s)
    assert settings.load() == s


def test_missing_lists_required_fields_in_order():
    assert settings.missing(Settings()) == ["cv_path", "skills", "keywords", "english", "czech", "needs_permit"]
    assert settings.missing(filled(english="none", czech="A1", needs_permit=True)) == []


def test_scoring_changed_only_for_scoring_fields():
    base = filled()
    assert not settings.scoring_changed(base, replace(base, skills=["Python", "SQL"], keywords=["java"], min_score=6))
    assert settings.scoring_changed(base, replace(base, city="Brno"))
    assert settings.scoring_changed(base, replace(base, needs_permit=True))


def test_read_cv_text_from_markdown_and_pdf(tmp_path, app):
    md = tmp_path / "cv.md"
    md.write_text("# CV\nPython, Docker", encoding="utf-8")
    assert "Docker" in settings.read_cv_text(str(md))
    pdf = tmp_path / "cv.pdf"
    write_pdf(pdf, "Kubernetes and PostgreSQL")
    assert "Kubernetes" in settings.read_cv_text(str(pdf))


def test_unreadable_cv_raises_cv_error(tmp_path):
    with pytest.raises(settings.CvError):
        settings.read_cv_text(str(tmp_path / "missing.pdf"))
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"not a pdf")
    with pytest.raises(settings.CvError):
        settings.read_cv_text(str(broken))


def test_detect_skills_skips_non_technical_groups():
    found = settings.detect_skills("Python, FastAPI, PostgreSQL, Docker. 3+ years. English C1. Czech B1.")
    assert found == ["Python", "FastAPI", "PostgreSQL", "Docker"]


def test_initial_prefills_only_cv_and_skills(tmp_path):
    cv = tmp_path / "master_cv.md"
    cv.write_text("Python and Docker", encoding="utf-8")
    s = settings.initial(cv)
    assert (s.cv_path, s.skills, s.keywords, s.english, s.needs_permit) == (str(cv), ["Python", "Docker"], [], "", None)
    assert settings.initial(tmp_path / "none.md") == Settings()
