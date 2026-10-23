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


def test_scoring_changed_sees_language_order_but_not_path_spelling():
    base = filled(languages={"English": "B2", "Czech": "B1"})
    assert settings.scoring_changed(base, replace(base, languages={"Czech": "B1", "English": "B2"}))  # rules list them in order
    assert not settings.scoring_changed(base, replace(base, cv_path="./cv.md"))  # the same file


def test_detect_skills_ignores_everyday_words():
    assert settings.detect_skills("Mobile: +420 123. Spring 2024 exams, grade C. I like to go deeper. "
                                  "The rest is history.") == []
    assert settings.detect_skills("Go, C, C++, R, Spring Boot, mobile apps, REST APIs") == [
        "C/C++", "Go", "R", "Spring", "Mobile", "REST API"]
    assert settings.guess_main_skill(["Go", "Python"], "go go go. Python") == "Python"
    assert settings.detect_skills("Mobile phone: +420 777. Mobile number: 1. Mobile +420 2. Spring semester 2024. "
                                  "During spring I worked.") == []
    assert settings.detect_skills("Languages: Python, Java, C" + chr(10) + "Tools: Docker | R | Git") == [
        "Python", "Java", "C/C++", "R", "Docker", "Git"]


def test_canonical_skill_and_language_names():
    assert settings.skill_name("python") == "Python" and settings.skill_name("Kotlin MP") == "Kotlin MP"
    assert settings.language_name("  english ") == "English"
    assert settings.language_name("vietnamese") == "Vietnamese"


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


def edit(path, text):
    """Change a file so that its stamp changes even within the same clock tick."""
    import os
    before = path.stat().st_mtime_ns if path.exists() else 0
    path.write_text(text, encoding="utf-8")
    os.utime(path, ns=(before + 10**9, before + 10**9))


def test_the_cv_is_scored_from_its_copy(tmp_path):
    cv = tmp_path / "cv.md"
    edit(cv, "Python developer")
    s = settings.store_cv(filled(cv_path=str(cv)), "Python developer")
    assert config.CV_COPY.read_text(encoding="utf-8") == "Python developer"
    assert s.cv_stamp == settings.file_stamp(str(cv))
    cv.unlink()  # moved away, deleted, or in use by another program
    assert settings.cv_text(s) == "Python developer"


def test_cv_text_before_the_first_copy(tmp_path):
    cv = tmp_path / "cv.md"
    edit(cv, "Python developer")
    assert settings.cv_text(filled(cv_path=str(cv))) == "Python developer"  # an older version's settings


def test_the_copy_follows_the_file(tmp_path, monkeypatch):
    cv = tmp_path / "cv.md"
    edit(cv, "Python developer")
    s = filled(cv_path=str(cv))
    settings.save(s)
    s, note = settings.sync_cv(s)  # the first refresh of an older version: the copy is made, nothing to say
    assert note == "" and config.CV_COPY.read_text(encoding="utf-8") == "Python developer"
    assert settings.load().cv_stamp == s.cv_stamp
    real = settings.read_cv_text
    monkeypatch.setattr(settings, "read_cv_text", lambda path: pytest.fail("the file didn't change: not read"))
    assert settings.sync_cv(s) == (s, "")
    monkeypatch.setattr(settings, "read_cv_text", real)
    edit(cv, "Python and SQL developer")  # edited in its own program
    s, note = settings.sync_cv(s)
    assert note == "your CV changed, so all jobs were scored again"
    assert settings.cv_text(s) == "Python and SQL developer"


def test_a_missing_or_broken_file_keeps_the_copy(tmp_path):
    cv = tmp_path / "cv.pdf"
    cv.write_bytes(b"%PDF-1.4 a real one")
    s = settings.store_cv(filled(cv_path=str(cv)), "Python developer")
    settings.save(s)
    edit(cv, "not a PDF any more")
    s, note = settings.sync_cv(s)
    assert "saved copy" in note and settings.cv_text(s) == "Python developer"
    assert settings.sync_cv(s)[1] == ""  # said once, not on every refresh
    cv.unlink()
    s, note = settings.sync_cv(s)
    assert note == "your CV file isn't found, so the saved copy is used"
    assert settings.sync_cv(s)[1] == "" and settings.cv_text(s) == "Python developer"


def test_no_file_and_no_copy_is_an_error(tmp_path):
    with pytest.raises(settings.CvError):
        settings.sync_cv(filled(cv_path=str(tmp_path / "gone.pdf")))
