from dataclasses import replace

import pytest
from helpers import write_pdf
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


def filled(**overrides):
    values = dict(cv_path="cv.md", skills=["Python"], main_skill="Python", languages={"English": "B2"})
    return Settings(**{**values, **overrides})


def test_no_settings_until_saved():
    assert settings.load() is None
    s = filled()
    settings.save(s)
    assert settings.load() == s


def test_missing_lists_required_fields_in_order():
    assert settings.missing(Settings()) == ["cv_path", "skills", "main_skill", "languages"]  # junior by default
    assert settings.missing(filled()) == []
    assert settings.missing(filled(main_skill="Java")) == ["main_skill"]  # not one of the skills
    assert settings.missing(filled(levels=[])) == ["levels"]
    assert settings.missing(filled(levels=["expert"])) == ["levels"]
    assert settings.missing(filled(languages={"English": "B2", "Czech": ""})) == ["languages"]  # a level is required
    assert settings.missing(filled(languages={})) == ["languages"]


def test_old_settings_load_without_errors():
    # Settings saved by the first version: keywords, two languages, a work permit and one level
    db.put_settings({"cv_path": "cv.md", "skills": ["Python"], "city": "Brno", "remote": False,
                     "keywords": ["python"], "level": "junior", "english": "B2", "czech": "B1",
                     "needs_permit": False, "min_score": 5, "stale_days": 14, "stale_job_days": 21})
    s = settings.load()
    assert (s.cv_path, s.skills, s.city, s.remote) == ("cv.md", ["Python"], "Brno", False)
    assert settings.missing(s) == ["main_skill", "languages"]


def test_guess_main_skill():
    text = "Java, Spring and Java EE. Python scripts. Java 17. Docker."
    assert settings.guess_main_skill(["Docker", "Python", "Java"], text) == "Java"  # the most mentioned language
    assert settings.guess_main_skill(["Docker", "SQL"], text) == "Docker"  # no programming language: the first skill
    assert settings.guess_main_skill([], text) == ""


def test_scoring_changed_only_for_scoring_fields():
    base = filled()
    assert not settings.scoring_changed(base, replace(base, skills=["Python", "SQL"], main_skill="SQL", min_score=6))
    assert settings.scoring_changed(base, replace(base, city="Brno"))
    assert settings.scoring_changed(base, replace(base, levels=["junior", "mid"]))
    assert settings.scoring_changed(base, replace(base, languages={"English": "C1"}))


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


def test_initial_prefills_cv_skills_and_main_skill(tmp_path):
    cv = tmp_path / "master_cv.md"
    cv.write_text("Docker and Python", encoding="utf-8")
    assert settings.initial(cv) == Settings(cv_path=str(cv), skills=["Python", "Docker"], main_skill="Python")
    assert settings.initial(tmp_path / "none.md") == Settings()
