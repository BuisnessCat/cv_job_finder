import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QSize
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QLabel

from job_finder import config, db, style, worker
from job_finder.window import MainWindow


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(app, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "jobs.db")
    monkeypatch.setattr(config, "CV_PATH", tmp_path / "master_cv.md")  # резюме нет → список пуст
    monkeypatch.setattr(worker.Worker, "start", lambda self: None)
    db.init()
    w = MainWindow()
    yield w
    w.deleteLater()


def row(url, score, published="2026-10-01"):
    return {"url": url, "source": "Jobicy", "title": f"Job {url}", "company": "ACME", "city": "Praha",
            "published": published, "score": score,
            "evaluation": {"score": score, "summary": "ok", "have": ["Python"], "missing": [], "risks": []}}


def titles(w):
    return [w.table.item(i, 1).text() for i in range(w.table.rowCount())]


def test_evaluated_rows_sorted_and_filtered(window):
    for r in [row("a", 6), row("b", 4), row("c", 9), row("d", 6, "2026-10-05")]:
        window.on_evaluated(r)
    assert titles(window) == ["Job c", "Job d", "Job a"]


def test_selection_kept_when_new_row_arrives(window):
    window.on_evaluated(row("a", 6))
    window.table.selectRow(0)
    window.on_evaluated(row("c", 9))
    assert window.current["url"] == "a"
    assert window.table.selectionModel().selectedRows()[0].row() == 1


def test_hide_removes_row(window, monkeypatch):
    hidden = []
    monkeypatch.setattr(db, "hide", hidden.append)
    window.on_evaluated(row("a", 6))
    window.on_evaluated(row("c", 9))
    window.table.selectRow(0)
    window.hide_job()
    assert hidden == ["c"]
    assert titles(window) == ["Job a"]
    assert window.current is None


def test_score_colored_by_band(window):
    window.on_evaluated(row("a", 9))
    window.on_evaluated(row("b", 5))
    assert window.table.item(0, 0).foreground().color().name() == style.score_colors(9)[1]
    assert window.table.item(1, 0).foreground().color().name() == style.score_colors(5)[1]
    window.table.selectRow(0)
    assert style.score_colors(9)[0] in window.badge.styleSheet()  # плашка оценки в деталях
    assert window.badge_number.text() == "9"


def list_texts(w, key):
    rows = w.lists[key][2]
    return [rows.itemAt(i).layout().itemAt(1).widget().text() for i in range(rows.count())]


def test_switching_rows_replaces_list_items(window):
    first = row("a", 9)
    second = row("b", 7)
    second["evaluation"]["have"] = ["SQL", "Git"]
    window.on_evaluated(first)
    window.on_evaluated(second)
    window.table.selectRow(0)
    window.table.selectRow(1)
    assert list_texts(window, "have") == ["SQL", "Git"]
    # Строки прошлой вакансии не должны оставаться в карточке, даже до удаления через цикл событий
    labels = window.pages.widget(1).findChildren(QLabel)
    assert "Python" not in [label.text() for label in labels]
    assert window.lists["have"][0].text() == "ЕСТЬ · 2"


def test_no_risks_shows_no_blockers(window):
    window.on_evaluated(row("a", 9))
    window.table.selectRow(0)
    assert list_texts(window, "risks") == ["Блокеров не найдено"]


def test_empty_state_until_row_selected(window):
    window.on_evaluated(row("a", 9))
    assert window.pages.currentIndex() == 0  # «Выберите вакансию в списке слева»
    window.table.selectRow(0)
    assert window.pages.currentIndex() == 1
    window.hide_job()
    assert window.pages.currentIndex() == 0


def test_icon_file_has_small_and_large_sizes(app):
    sizes = QIcon(str(config.ICON_PATH)).availableSizes()
    assert QSize(16, 16) in sizes  # заголовок окна и панель задач
    assert QSize(256, 256) in sizes  # ярлык на рабочем столе
