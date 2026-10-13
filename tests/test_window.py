import os
import sqlite3
from datetime import date, timedelta

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QSize
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QLabel

from job_finder import config, db, style, worker
from job_finder.sources import Job
from job_finder.window import MainWindow, days_waiting, plural_days


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
    rows = w.detail_lists[key][2]
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
    assert window.detail_lists["have"][0].text() == "ЕСТЬ · 2"


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


def test_finished_reloads_rows_from_db(window):
    config.CV_PATH.write_text("## Skills\n- Python — x\n", encoding="utf-8")  # временное резюме из фикстуры
    key = worker.read_cv()[1]
    db.save_jobs("Jobicy", [Job(url="a", source="Jobicy", title="Job a", company="ACME", city="Praha",
                                published="2026-10-01", description="")])
    db.save_evaluation("a", row("a", 8)["evaluation"], key)
    db.mark_all_seen()  # тест про перечитывание, а не про пометку «новое»
    window.on_evaluated(row("gone", 9))  # в базе её уже нет: пропала из источника или отсеяна по месту
    window.on_finished()
    assert titles(window) == ["Job a"]


def test_cv_button_opens_one_cv_window(window):
    window.cv_button.click()
    first = window.cv_window
    assert first is not None and first.isVisible()
    window.cv_button.click()
    assert window.cv_window is first  # повторное нажатие не плодит окна
    first.close()


def add_found(url, score, title=None, company="ACME", new=False):
    """Найденная вакансия в базе, оценённая по временному резюме из фикстуры; new=False — уже просмотрена."""
    if not config.CV_PATH.exists():
        config.CV_PATH.write_text("## Skills\n- Python — x\n", encoding="utf-8")  # временное резюме
    # Свой источник у каждой вакансии: save_jobs выключает вакансии источника, которых нет в выборке
    job = Job(url=url, source=f"src-{url}", title=title or f"Job {url}", company=company, city="Praha",
              published="2026-10-01", description="")
    db.save_jobs(job.source, [job])
    db.save_evaluation(url, row(url, score)["evaluation"], worker.read_cv()[1])
    if not new:
        with sqlite3.connect(config.DB_PATH) as conn:
            conn.execute("UPDATE jobs SET seen = 1 WHERE url = ?", (url,))


def applied_titles(w):
    return [w.applied_table.item(i, 1).text() for i in range(w.applied_table.rowCount())]


def test_apply_moves_row_to_applications(window):
    add_found("a", 8)
    add_found("b", 7)
    window.load_rows()
    window.table.selectRow(0)
    window.apply_button.click()
    assert titles(window) == ["Job b"]
    assert applied_titles(window) == ["Job a"]
    assert window.applied_table.item(0, 3).text() == "Ждём ответа"
    assert window.found_tab.text() == "Найденные · 1"
    assert window.applied_tab.text() == "Мои отклики · 1"


def test_status_buttons_and_return(window):
    add_found("a", 8)
    window.load_rows()
    window.table.selectRow(0)
    window.apply_button.click()
    window.show_tab(1)
    window.applied_table.selectRow(0)
    assert not window.accept_button.isHidden() and window.apply_button.isHidden()
    window.accept_button.click()
    assert window.applied_table.item(0, 3).text() == "Приняли"
    assert "Приняли" in window.d_status.text()  # карточка осталась на этом отклике и обновилась
    window.reject_button.click()
    assert window.applied_table.item(0, 3).text() == "Отказали"
    window.unapply_button.click()
    assert applied_titles(window) == []
    assert titles(window) == ["Job a"]
    assert window.applied_tab.text() == "Мои отклики · 0"


def test_repost_marked(window):
    add_found("old", 8, title="Python Dev", company="ACME")
    window.load_rows()
    window.table.selectRow(0)
    window.apply_button.click()
    add_found("new", 7, title="python  dev", company=" acme ")  # та же вакансия с новой ссылкой
    window.load_rows()
    assert titles(window) == ["↻ python  dev"]
    window.table.selectRow(0)
    assert not window.d_notice.isHidden()
    assert "Вы уже подавались" in window.d_notice.text()


def test_card_extras_reset_between_rows(window):
    add_found("old", 8, title="Python Dev")
    add_found("plain", 6, title="Other")
    window.load_rows()
    window.table.selectRow(0)
    window.apply_button.click()
    add_found("new", 7, title="Python Dev")
    window.load_rows()
    window.table.selectRow(0)  # перепубликованная — с жёлтой плашкой
    assert not window.d_notice.isHidden()
    window.table.selectRow(1)  # обычная найденная
    assert window.d_notice.isHidden() and window.d_status.isHidden()
    assert not window.apply_button.isHidden() and window.accept_button.isHidden()


def test_new_found_row_keeps_application_selected(window):
    add_found("a", 8)
    window.load_rows()
    window.table.selectRow(0)
    window.apply_button.click()
    window.show_tab(1)
    window.applied_table.selectRow(0)
    window.on_evaluated(row("fresh", 9))  # фоновое обновление прислало новую найденную вакансию
    assert window.current["url"] == "a"


def set_applied_at(url, days_ago):
    with sqlite3.connect(config.DB_PATH) as conn:
        conn.execute("UPDATE jobs SET applied_at = ? WHERE url = ?",
                     ((date.today() - timedelta(days=days_ago)).isoformat(), url))


def test_days_waiting_and_plural():
    assert days_waiting("2026-09-22", date(2026, 10, 13)) == 21
    assert [plural_days(n) for n in (0, 1, 2, 5, 11, 12, 21, 22, 25, 101, 111)] == [
        "0 дней", "1 день", "2 дня", "5 дней", "11 дней", "12 дней", "21 день", "22 дня", "25 дней",
        "101 день", "111 дней"]


def test_new_rows_marked_and_counted(window):
    add_found("a", 8, new=True)
    add_found("b", 7)
    window.load_rows()
    assert titles(window) == ["• Job a", "Job b"]
    assert window.table.item(0, 1).font().bold() and not window.table.item(1, 1).font().bold()
    assert window.found_tab.text() == "Найденные · 2 (+1)"


def test_job_arriving_during_refresh_is_marked(window):
    window.load_rows()
    add_found("x", 9, new=True)  # фоновое обновление записало новую вакансию уже после загрузки списка
    window.on_evaluated(row("x", 9))
    assert titles(window) == ["• Job x"]


def test_status_buttons_show_only_other_statuses(window):
    add_found("a", 8)
    window.load_rows()
    window.table.selectRow(0)
    window.apply_button.click()
    window.show_tab(1)
    window.applied_table.selectRow(0)
    visible = lambda: {s for s, b in window.status_buttons.items() if not b.isHidden()}
    assert visible() == {"accepted", "rejected"}
    window.reject_button.click()
    assert visible() == {"applied", "accepted"}
    window.waiting_button.click()
    assert window.applied_table.item(0, 3).text() == "Ждём ответа"
    assert visible() == {"accepted", "rejected"}


def test_waiting_days_and_stale_highlight(window):
    add_found("old", 8)
    add_found("fresh", 7)
    add_found("done", 6)
    for url in ("old", "fresh", "done"):
        db.apply(url)
    set_applied_at("old", 20)
    set_applied_at("fresh", 3)
    set_applied_at("done", 30)
    db.set_status("done", "rejected")
    window.load_rows()
    cells = {window.applied_table.item(i, 1).text(): window.applied_table.item(i, 4)
             for i in range(window.applied_table.rowCount())}
    assert cells["Job old"].text() == "20"
    assert cells["Job old"].foreground().color().name() == style.COLORS["notice_text"]
    assert cells["Job fresh"].text() == "3"
    assert cells["Job fresh"].foreground().color().name() != style.COLORS["notice_text"]
    assert cells["Job done"].text() == "—"
    window.show_tab(1)
    old_row = [r["url"] for r in window.applied].index("old")
    window.applied_table.selectRow(old_row)
    assert "20 дней" in window.d_status.text() and not window.d_stale.isHidden()
    window.reject_button.click()  # итог пришёл — подсказка больше не нужна
    assert window.d_stale.isHidden() and "дн" not in window.d_status.text()


def test_notes_saved_on_row_switch(window):
    add_found("a", 8)
    add_found("b", 7)
    for url in ("a", "b"):
        db.apply(url)
    window.load_rows()
    window.show_tab(1)
    index = {r["url"]: i for i, r in enumerate(window.applied)}
    window.applied_table.selectRow(index["a"])
    assert not window.notes_box.isHidden()
    window.notes.setPlainText("Писал HR 30.09")
    window.applied_table.selectRow(index["b"])  # раньше, чем сработала задержка сохранения
    assert {r["url"]: r["notes"] for r in db.list_applied()}["a"] == "Писал HR 30.09"
    assert window.notes.toPlainText() == ""
    window.applied_table.selectRow(index["a"])
    assert window.notes.toPlainText() == "Писал HR 30.09"


def test_close_saves_notes_and_marks_seen(window):
    add_found("a", 8)
    add_found("n", 7, new=True)
    db.apply("a")
    window.load_rows()
    window.show_tab(1)
    window.applied_table.selectRow(0)
    window.notes.setPlainText("Собеседование в пятницу")
    window.show()
    window.close()
    assert db.list_applied()[0]["notes"] == "Собеседование в пятницу"
    assert db.unseen_urls() == set()
