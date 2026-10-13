import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from job_finder import config, style
from job_finder.cv_window import CvWindow

CV = "# Test CV\n\n## Skills — level\n- Python — main language\n- SQL — JOINs\n\n## Projects\n- job-radar\n"


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def cv_path(tmp_path, monkeypatch):
    path = tmp_path / "master_cv.md"  # a temporary CV, the real master_cv.md is not touched
    monkeypatch.setattr(config, "CV_PATH", path)
    return path


def test_shows_cv_text_path_and_skills(app, cv_path):
    cv_path.write_text(CV, encoding="utf-8")
    window = CvWindow()
    assert "Test CV" in window.body.toPlainText()
    assert window.path_label.text() == str(cv_path)
    assert window.skills_label.text() == "Python, SQL"
    assert window.modified_label.text() not in ("", "—")


def test_reload_shows_current_file(app, cv_path):
    cv_path.write_text(CV, encoding="utf-8")
    window = CvWindow()
    cv_path.write_text(CV.replace("Test CV", "Updated CV"), encoding="utf-8")
    window.reload()
    assert "Updated CV" in window.body.toPlainText()


def test_english_cv_window_texts(app, cv_path):
    cv_path.write_text(CV, encoding="utf-8")
    window = CvWindow()
    assert window.windowTitle() == "My CV — master_cv.md"
    assert window.open_button.text() == "Open in editor"


def test_missing_cv_shows_message(app, cv_path):
    window = CvWindow()
    assert "not found" in window.body.toPlainText()
    assert not window.open_button.isEnabled()


def link_color(window):
    block = window.body.document().begin()
    while block.isValid():
        it = block.begin()
        while not it.atEnd():
            fmt = it.fragment().charFormat()
            if fmt.isAnchor():
                return fmt.foreground().color().name()
            it += 1
        block = block.next()
    return None


def test_links_use_theme_color(app, cv_path):
    # Qt colors Markdown links from the app palette, so the theme sets the color there
    style.apply_app_theme(app)
    cv_path.write_text("Email: [me@example.cz](mailto:me@example.cz)", encoding="utf-8")
    assert link_color(CvWindow()) == style.COLORS["link"]
