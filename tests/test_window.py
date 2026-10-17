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
    monkeypatch.setattr(config, "CV_PATH", tmp_path / "master_cv.md")  # no CV, so the list is empty
    monkeypatch.setattr(worker.Worker, "start", lambda self: None)
    db.init()
    w = MainWindow()
    w.freshness_buttons.button(3).click()  # "All": older tests use fixed dates; freshness tests pick a filter
    yield w
    w.deleteLater()


def row(url, score, published="2026-10-01"):
    return {"url": url, "source": "Jobicy", "title": f"Job {url}", "company": "ACME", "city": "Prague",
            "published": published, "first_seen": published, "score": score,
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
    assert style.score_colors(9)[0] in window.badge.styleSheet()  # score pill in the details
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
    # Rows of the previous job must not stay in the card, even before the event loop deletes them
    labels = window.pages.widget(1).findChildren(QLabel)
    assert "Python" not in [label.text() for label in labels]
    assert window.detail_lists["have"][0].text() == "YOU HAVE · 2"


def test_no_risks_shows_no_blockers(window):
    window.on_evaluated(row("a", 9))
    window.table.selectRow(0)
    assert list_texts(window, "risks") == ["No blockers found"]


def test_empty_state_until_row_selected(window):
    window.on_evaluated(row("a", 9))
    assert window.pages.currentIndex() == 0  # "Select a job on the left"
    window.table.selectRow(0)
    assert window.pages.currentIndex() == 1
    window.hide_job()
    assert window.pages.currentIndex() == 0


def test_icon_file_has_small_and_large_sizes(app):
    sizes = QIcon(str(config.ICON_PATH)).availableSizes()
    assert QSize(16, 16) in sizes  # window title and taskbar
    assert QSize(256, 256) in sizes  # desktop shortcut


def test_finished_reloads_rows_from_db(window):
    config.CV_PATH.write_text("## Skills\n- Python — x\n", encoding="utf-8")  # temporary CV from the fixture
    key = worker.read_cv()[1]
    db.save_jobs("Jobicy", [Job(url="a", source="Jobicy", title="Job a", company="ACME", city="Praha",
                                published="2026-10-01", description="")])
    db.save_evaluation("a", row("a", 8)["evaluation"], key)
    db.mark_all_seen()  # this test is about re-reading, not about the "new" mark
    window.on_evaluated(row("gone", 9))  # gone from the database: vanished from the source or filtered out by location
    window.on_finished()
    assert titles(window) == ["Job a"]


def test_cv_button_opens_one_cv_window(window):
    window.cv_button.click()
    first = window.cv_window
    assert first is not None and first.isVisible()
    window.cv_button.click()
    assert window.cv_window is first  # a second click does not open another window
    first.close()


def add_found(url, score, title=None, company="ACME", new=False, evaluation=None):
    """A found job in the database, scored under the fixture's temporary CV; new=False: already seen."""
    if not config.CV_PATH.exists():
        config.CV_PATH.write_text("## Skills\n- Python — x\n", encoding="utf-8")  # temporary CV
    # Each job gets its own source: save_jobs deactivates a source's jobs missing from the batch
    job = Job(url=url, source=f"src-{url}", title=title or f"Job {url}", company=company, city="Prague",
              published="2026-10-01", description="")
    db.save_jobs(job.source, [job])
    db.save_evaluation(url, evaluation or row(url, score)["evaluation"], worker.read_cv()[1])
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
    assert window.applied_table.item(0, 3).text() == "Waiting"
    assert window.found_tab.text() == "Found · 1"
    assert window.applied_tab.text() == "My applications · 1"


def test_status_buttons_and_return(window):
    add_found("a", 8)
    window.load_rows()
    window.table.selectRow(0)
    window.apply_button.click()
    window.show_tab(1)
    window.applied_table.selectRow(0)
    assert not window.accept_button.isHidden() and window.apply_button.isHidden()
    window.accept_button.click()
    assert window.applied_table.item(0, 3).text() == "Accepted"
    assert "Accepted" in window.d_status.text()  # the card stayed on this application and updated
    window.reject_button.click()
    assert window.applied_table.item(0, 3).text() == "Rejected"
    window.unapply_button.click()
    assert applied_titles(window) == []
    assert titles(window) == ["Job a"]
    assert window.applied_tab.text() == "My applications · 0"


def test_repost_marked(window):
    add_found("old", 8, title="Python Dev", company="ACME")
    window.load_rows()
    window.table.selectRow(0)
    window.apply_button.click()
    add_found("new", 7, title="python  dev", company=" acme ")  # the same job with a new link
    window.load_rows()
    assert titles(window) == ["↻ python  dev"]
    window.table.selectRow(0)
    assert not window.d_notice.isHidden()
    applied_at = date.today().isoformat()
    assert window.d_notice.text() == f'You already applied to "Python Dev" at ACME on {applied_at} — status: waiting'


def test_card_extras_reset_between_rows(window):
    add_found("old", 8, title="Python Dev")
    add_found("plain", 6, title="Other")
    window.load_rows()
    window.table.selectRow(0)
    window.apply_button.click()
    add_found("new", 7, title="Python Dev")
    window.load_rows()
    window.table.selectRow(0)  # reposted, with the yellow notice
    assert not window.d_notice.isHidden()
    window.table.selectRow(1)  # a regular found job
    assert window.d_notice.isHidden() and window.d_status.isHidden()
    assert not window.apply_button.isHidden() and window.accept_button.isHidden()


def test_new_found_row_keeps_application_selected(window):
    add_found("a", 8)
    window.load_rows()
    window.table.selectRow(0)
    window.apply_button.click()
    window.show_tab(1)
    window.applied_table.selectRow(0)
    window.on_evaluated(row("fresh", 9))  # the background refresh sent a new found job
    assert window.current["url"] == "a"


def set_applied_at(url, days_ago):
    with sqlite3.connect(config.DB_PATH) as conn:
        conn.execute("UPDATE jobs SET applied_at = ? WHERE url = ?",
                     ((date.today() - timedelta(days=days_ago)).isoformat(), url))


def test_days_waiting_and_plural():
    assert days_waiting("2026-09-22", date(2026, 10, 13)) == 21
    assert [plural_days(n) for n in (0, 1, 2, 11, 21)] == ["0 days", "1 day", "2 days", "11 days", "21 days"]


def test_new_rows_marked_and_counted(window):
    add_found("a", 8, new=True)
    add_found("b", 7)
    window.load_rows()
    assert titles(window) == ["• Job a", "Job b"]
    assert window.table.item(0, 1).font().bold() and not window.table.item(1, 1).font().bold()
    assert window.found_tab.text() == "Found · 2 (+1)"


def test_job_arriving_during_refresh_is_marked(window):
    window.load_rows()
    add_found("x", 9, new=True)  # the background refresh saved a new job after the list was loaded
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
    assert window.applied_table.item(0, 3).text() == "Waiting"
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
    assert "20 days" in window.d_status.text() and not window.d_stale.isHidden()
    assert window.d_stale.text() == f"No reply for over {config.STALE_DAYS} days — time to follow up or close it"
    window.reject_button.click()  # the outcome arrived: the hint is no longer needed
    assert window.d_stale.isHidden() and "days" not in window.d_status.text()


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
    window.notes.setPlainText("Emailed HR on 30.09")
    window.applied_table.selectRow(index["b"])  # before the save delay fires
    assert {r["url"]: r["notes"] for r in db.list_applied()}["a"] == "Emailed HR on 30.09"
    assert window.notes.toPlainText() == ""
    window.applied_table.selectRow(index["a"])
    assert window.notes.toPlainText() == "Emailed HR on 30.09"


def test_close_saves_notes_and_marks_seen(window):
    add_found("a", 8)
    add_found("n", 7, new=True)
    db.apply("a")
    window.load_rows()
    window.show_tab(1)
    window.applied_table.selectRow(0)
    window.notes.setPlainText("Interview on Friday")
    window.show()
    window.close()
    assert db.list_applied()[0]["notes"] == "Interview on Friday"
    assert db.unseen_urls() == set()


def test_english_window_texts(window):
    assert window.windowTitle() == "Job Finder"
    assert window.refresh_button.text() == "Refresh" and window.cv_button.text() == "My CV"
    headers = lambda table: [table.horizontalHeaderItem(i).text() for i in range(table.columnCount())]
    assert headers(window.table) == ["Score", "Job", "Company", "Location", "Posted"]
    assert headers(window.applied_table) == ["Applied", "Job", "Company", "Status", "Days waiting", "Score"]
    assert [b.text() for b in (window.open_button, window.apply_button, window.hide_button,
                               window.unapply_button)] == ["Open job", "I applied", "Hide", "Back to found"]
    assert window.badge_caption.text() == "of 10"


def test_application_card_fits_window_width(window):
    add_found("a", 8, title="Junior Python Backend Developer (Django, FastAPI, PostgreSQL)")
    for i in range(12):
        add_found(f"x{i}", 6)
        db.apply(f"x{i}")
    db.apply("a")
    window.load_rows()
    window.show_tab(1)
    window.applied_table.selectRow([r["url"] for r in window.applied].index("a"))
    window.show()
    assert window.applied_tab.text() == "My applications · 13"
    assert window.minimumSizeHint().width() <= 1200


def test_long_location_does_not_squeeze_job_title(window):
    # A remote job open to many regions must not push the title column down to a few letters
    long_city = row("a", 8)
    long_city["city"] = "Remote: APAC, EMEA, LATAM, Canada, USA, Australia, New Zealand"
    window.on_evaluated(long_city)
    window.on_evaluated(row("b", 7))
    window.resize(1200, 750)
    window.show()
    QApplication.processEvents()
    assert window.table.columnWidth(1) > window.table.columnWidth(3)


def evaluation_with(have, missing, score=6):
    return {"score": score, "summary": "ok", "have": have, "missing": missing, "risks": []}


def bar_texts(rows):
    return [(rows.itemAt(i).widget().findChild(QLabel, "barName").text(),
             rows.itemAt(i).widget().findChild(QLabel, "barCount").text()) for i in range(rows.count())]


def test_insights_tab_counts_requirements(window):
    add_found("a", 8, evaluation=evaluation_with(["Python backend"], ["Kubernetes (k8s)", "AWS cloud"]))
    add_found("b", 3, evaluation=evaluation_with(["Python"], ["AWS", "underwater basket weaving"]))
    window.load_rows()
    window.insights_tab.click()
    assert window.views.currentIndex() == 1 and not window.insights_cards.isHidden()
    assert bar_texts(window.missing_rows) == [("AWS", "2"), ("Cloud (any)", "1"), ("Kubernetes", "1")]
    assert bar_texts(window.required_rows)[:2] == [("AWS", "2"), ("✓ Python", "2")]
    assert window.insights_note.text() == "Based on 2 evaluated jobs · 1 missing item not recognised"
    window.applied_tab.click()
    assert window.views.currentIndex() == 0 and window.lists.currentIndex() == 1
    window.found_tab.click()
    assert window.views.currentIndex() == 0 and window.lists.currentIndex() == 0


def test_insights_messages_without_cv_or_evaluations(window):
    window.insights_tab.click()
    assert window.insights_message.text() == "No master_cv.md — nothing to analyse"
    assert window.insights_cards.isHidden()
    config.CV_PATH.write_text("## Skills\n- Python — x\n", encoding="utf-8")  # temporary CV from the fixture
    window.render_insights()
    assert window.insights_message.text() == "Nothing evaluated yet"


def test_insights_recounted_after_refresh(window):
    add_found("a", 8, evaluation=evaluation_with([], ["AWS"]))
    window.load_rows()
    window.insights_tab.click()
    add_found("b", 7, evaluation=evaluation_with([], ["AWS", "Docker"]))  # the background refresh scored one more
    window.on_finished()
    assert window.views.currentIndex() == 1
    assert bar_texts(window.missing_rows) == [("AWS", "2"), ("Docker", "1")]
    window.found_tab.click()
    window.on_finished()
    assert window.views.currentIndex() == 0  # a finished refresh does not switch the view


def test_insights_page_does_not_raise_window_minimum(window):
    # Twenty rows of fixed-width bars must not make the whole window impossible to shrink on any tab
    names = ["AWS", "Azure", "GCP", "Kubernetes", "Docker", "Terraform", "Linux", "Git", "JavaScript", "TypeScript",
             "React", "Vue", "Angular", "Java", "Go", "Rust", "PHP", "Ruby", "Kotlin", "Swift"]
    add_found("a", 8, evaluation=evaluation_with([], names))
    window.load_rows()
    window.show()  # layouts are only recalculated for a shown window
    QApplication.processEvents()
    before = window.minimumSizeHint()
    window.insights_tab.click()
    QApplication.processEvents()
    window.found_tab.click()
    QApplication.processEvents()
    after = window.minimumSizeHint()
    assert after.width() <= max(before.width(), 700) and after.height() <= max(before.height(), 450)


def days_ago(n):
    return (date.today() - timedelta(days=n)).isoformat()


def test_posted_column_shows_age_and_reposted(window):
    bumped = row("b", 7, days_ago(0))
    bumped["first_seen"] = days_ago(30)
    for r in (row("a", 8, days_ago(0)), bumped, row("c", 6, days_ago(25))):
        window.on_evaluated(r)
    assert window.table.horizontalHeaderItem(4).text() == "Posted"
    posted = {window.table.item(i, 1).text(): window.table.item(i, 4).text() for i in range(window.table.rowCount())}
    assert posted == {"Job a": "today", "Job b": "30 days ago · reposted", "Job c": "25 days ago"}
    stale = next(i for i in range(window.table.rowCount()) if window.table.item(i, 1).text() == "Job c")
    assert window.table.item(stale, 1).foreground().color().name() == style.COLORS["muted"]


def test_filters_and_order_change_visible_rows(window):
    other = row("b", 6, days_ago(1))
    other["company"] = "Globex"
    for r in (row("a", 9, days_ago(20)), other, row("c", 7, days_ago(3))):
        window.on_evaluated(r)
    assert window.shown_label.isHidden()
    window.search.setText("globex")
    assert titles(window) == ["Job b"]
    assert window.shown_label.text() == "1 of 3 shown" and not window.shown_label.isHidden()
    window.search.setText("")
    window.freshness_buttons.button(0).click()  # 7d
    assert titles(window) == ["Job c", "Job b"]
    window.order_buttons.button(1).click()  # Newest
    assert titles(window) == ["Job b", "Job c"]
    window.search.setText("nothing like this")
    assert window.no_match.text() == "No jobs match the filters"
    assert not window.no_match.isHidden() and window.table.isHidden()


def test_selection_maps_to_visible_row(window):
    for url in ("a", "b", "c"):
        r = row(url, 7, days_ago(1))
        r["company"] = "Globex" if url == "b" else "ACME"
        window.on_evaluated(r)
    window.search.setText("globex")
    window.table.selectRow(0)
    assert window.current["url"] == "b"


def test_selection_cleared_when_filtered_out(window):
    window.on_evaluated(row("a", 7, days_ago(1)))
    window.table.selectRow(0)
    window.search.setText("zzz")
    assert window.current is None


def test_new_evaluation_respects_filters(window):
    window.freshness_buttons.button(0).click()  # 7d
    window.on_evaluated(row("old", 8, days_ago(20)))
    assert titles(window) == [] and [r["url"] for r in window.rows] == ["old"]


def test_card_published_shows_site_date_and_first_seen(window):
    r = row("a", 8, days_ago(0))
    r["first_seen"] = days_ago(30)
    window.on_evaluated(r)
    window.table.selectRow(0)
    assert window.facts["published"].text() == f"{days_ago(0)} (today) · first seen 30 days ago"


def set_description(url, text):
    with sqlite3.connect(config.DB_PATH) as conn:
        conn.execute("UPDATE jobs SET description = ? WHERE url = ?", (text, url))


def test_description_collapsed_then_shown(window):
    add_found("a", 8)
    add_found("b", 7)
    set_description("a", "Build REST APIs")
    set_description("b", "Write tests")
    window.load_rows()
    window.table.selectRow(0)
    assert window.d_description.isHidden() and window.description_button.text() == "Show description"
    window.description_button.click()
    assert not window.d_description.isHidden() and window.d_description.text() == "Build REST APIs"
    assert window.description_button.text() == "Collapse"
    window.table.selectRow(1)
    assert window.d_description.text() == "Write tests"


def test_progress_shows_time_left(window, monkeypatch):
    ticks = iter([100.0, 120.0, 130.0])
    monkeypatch.setattr(MainWindow, "clock", staticmethod(lambda: next(ticks)))
    window.on_progress(0, 213)
    window.on_progress(2, 213)
    assert window.status_label.text() == "Evaluated 2 of 213"
    window.on_progress(3, 213)
    assert window.status_label.text() == "Evaluated 3 of 213 · ~35 min left"


def test_close_during_refresh_asks(window, monkeypatch):
    marked = []
    monkeypatch.setattr(db, "mark_all_seen", lambda: marked.append(True))
    window.show()
    window.refreshing = True
    monkeypatch.setattr(window, "confirm_close", lambda: False)
    window.close()
    assert window.isVisible() and marked == []
    monkeypatch.setattr(window, "confirm_close", lambda: True)
    window.close()
    assert not window.isVisible() and marked == [True]


def test_close_without_refresh_does_not_ask(window, monkeypatch):
    asked = []
    monkeypatch.setattr(window, "confirm_close", lambda: asked.append(True) or True)
    window.refresh()
    assert window.refreshing
    window.on_finished()
    window.show()
    window.close()
    assert asked == [] and not window.refreshing


def test_undo_hide(window):
    add_found("a", 8)
    add_found("b", 7)
    window.load_rows()
    window.table.selectRow(0)
    window.hide_button.click()
    assert not window.undo_toast.isHidden() and window.undo_label.text() == "Hidden: Job a"
    window.undo_button.click()
    assert titles(window) == ["Job a", "Job b"] and window.current["url"] == "a"
    assert window.undo_toast.isHidden()
    window.hide_button.click()  # "a" is selected again
    window.undo_timer.timeout.emit()
    assert window.undo_toast.isHidden()
    window.table.selectRow(0)  # "b"
    window.hide_button.click()  # a newer hide replaces the older undo
    window.undo()
    assert titles(window) == ["Job b"]


def test_undo_for_filtered_job_does_not_crash(window):
    add_found("a", 8)
    window.load_rows()
    window.table.selectRow(0)
    window.hide_button.click()
    window.search.setText("zzz")
    window.undo()
    assert [r["url"] for r in window.rows] == ["a"] and window.current is None


def test_closed_application_marked(window):
    config.CV_PATH.write_text("## Skills\n- Python — x\n", encoding="utf-8")  # temporary CV from the fixture
    key = worker.read_cv()[1]
    for url, source, title in [("jg", "junior.guru", "Dev JG"), ("him", "Himalayas", "Dev H")]:
        db.save_jobs(source, [Job(url=url, source=source, title=title, company=url, city="Prague",
                                  published="2026-10-01", description="")])
        db.save_evaluation(url, row(url, 8)["evaluation"], key)
        db.apply(url)
        db.save_jobs(source, [])  # gone from the source's results
    window.load_rows()
    window.show_tab(1)
    by_title = {window.applied_table.item(i, 1).text(): i for i in range(window.applied_table.rowCount())}
    assert set(by_title) == {"⊘ Dev JG", "Dev H"}
    window.applied_table.selectRow(by_title["⊘ Dev JG"])
    assert not window.d_closed.isHidden()
    assert window.d_closed.text() == "No longer listed on junior.guru — probably filled"
    window.applied_table.selectRow(by_title["Dev H"])
    assert window.d_closed.isHidden()
