import os
from pathlib import Path
import sqlite3
import time
from datetime import date, timedelta

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from dataclasses import replace

import pytest
from PySide6.QtCore import QSize
from PySide6.QtGui import QDesktopServices, QIcon
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QSystemTrayIcon

from helpers import use_settings

from job_finder import busy, config, db, llm, settings, settings_window, style, updates, worker
from job_finder.__main__ import tell_running_instance
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
    monkeypatch.setattr(MainWindow, "tray_available", staticmethod(lambda: False))  # the tray has its own tests
    db.init()
    w = MainWindow()
    w.freshness_buttons.button(3).click()  # "All": older tests use fixed dates; freshness tests pick a filter
    yield w
    w.deleteLater()


@pytest.fixture
def tray_window(app, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "jobs.db")
    monkeypatch.setattr(config, "CV_PATH", tmp_path / "master_cv.md")
    monkeypatch.setattr(worker.Worker, "start", lambda self: None)
    monkeypatch.setattr(MainWindow, "tray_available", staticmethod(lambda: True))
    db.init()
    w = MainWindow()
    exits = []
    monkeypatch.setattr(w, "exit_app", lambda: exits.append(True))  # the real one ends the Qt event loop
    w.exits = exits
    yield w
    w.tray.hide()
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
    use_settings(config.CV_PATH)  # temporary CV from the fixture
    key = worker.read_cv(settings.load())[1]
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


def test_card_shows_salary_only_when_known(window):
    window.on_evaluated(row("a", 8) | {"salary": "$2,000–3,000 / month"})
    window.on_evaluated(row("b", 7))
    window.table.selectRow(0)
    assert window.facts["salary"].text() == "$2,000–3,000 / month" and not window.facts["salary"].isHidden()
    window.table.selectRow(1)
    assert window.facts["salary"].isHidden() and window.fact_names["salary"].isHidden()


def test_settings_button_reloads_and_refreshes_on_city_change(window, monkeypatch):
    s = use_settings(config.CV_PATH)  # temporary CV from the fixture
    window.load_rows()
    refreshed = []
    monkeypatch.setattr(window, "refresh", lambda: refreshed.append(True))
    new = replace(s, min_score=8)

    class FakeDialog:  # "Save" in the Settings window writes the settings and closes it
        def __init__(self, current, parent):
            assert current == window.settings

        def exec(self):
            settings.save(new)
            return QDialog.Accepted

        def deleteLater(self):
            pass

    monkeypatch.setattr(settings_window, "SettingsDialog", FakeDialog)
    window.settings_button.click()
    assert window.settings.min_score == 8 and refreshed == []  # a threshold: only the list is re-read
    new = replace(new, city="Brno")
    window.settings_button.click()
    assert window.settings.city == "Brno" and refreshed == [True]  # where to search changed: a new search


def test_settings_unavailable_while_refreshing(window):
    assert window.settings_button.text() == "Settings" and window.settings_button.isEnabled()
    window.refresh()
    assert not window.settings_button.isEnabled()  # the running pass uses the old settings
    window.on_finished()
    assert window.settings_button.isEnabled()


def test_thresholds_come_from_settings(window):
    use_settings(config.CV_PATH, min_score=8, stale_days=5, stale_job_days=10)
    window.load_rows()
    for r in [row("a", 7), row("b", 8, days_ago(11)), row("c", 9, days_ago(9))]:
        window.on_evaluated(r)
    assert titles(window) == ["Job c", "Job b"]
    assert window.table.item(1, 1).foreground().color().name() == style.COLORS["muted"]  # older than 10 days
    assert window.table.item(0, 1).foreground().color().name() != style.COLORS["muted"]
    add_found("x", 8)
    db.apply("x")
    set_applied_at("x", 6)
    window.load_rows()
    window.show_tab(1)
    window.applied_table.selectRow(0)
    assert window.d_stale.text() == "No reply for over 5 days — time to follow up or close it"
    assert not window.d_stale.isHidden()


def add_found(url, score, title=None, company="ACME", new=False, evaluation=None):
    """A found job in the database, scored under the fixture's temporary CV; new=False: already seen."""
    if settings.load() is None:
        use_settings(config.CV_PATH)  # temporary CV and settings
    # Each job gets its own source: save_jobs deactivates a source's jobs missing from the batch
    job = Job(url=url, source=f"src-{url}", title=title or f"Job {url}", company=company, city="Prague",
              published="2026-10-01", description="")
    db.save_jobs(job.source, [job])
    db.save_evaluation(url, evaluation or row(url, score)["evaluation"], worker.read_cv(settings.load())[1])
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
    assert window.d_stale.text() == "No reply for over 14 days — time to follow up or close it"  # the default
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
    assert window.insights_message.text() == "Can't read your CV — check it in Settings"
    assert window.insights_cards.isHidden()
    use_settings(config.CV_PATH)  # temporary CV from the fixture
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


def test_closed_mark_only_for_jobs_still_searched(window):
    s = use_settings(config.CV_PATH)  # temporary CV from the fixture; Praha, remote is fine
    key = worker.read_cv(s)[1]
    for url, source, city in [("up", "Úřad práce", "Prague"), ("jy", "Jobicy", "Remote")]:
        db.save_jobs(source, [Job(url=url, source=source, title=f"Dev {url}", company=url, city=city,
                                  published="2026-10-01", description="")])
        db.save_evaluation(url, row(url, 8)["evaluation"], key)
        db.apply(url)
        db.save_jobs(source, [])  # gone from the source's results

    def marks():
        window.load_rows()
        return sorted(window.applied_table.item(i, 1).text() for i in range(window.applied_table.rowCount()))

    assert marks() == ["⊘ Dev jy", "⊘ Dev up"]
    settings.save(replace(s, city="Brno"))  # Prague jobs are not searched for any more; remote ones still are
    assert marks() == ["Dev up", "⊘ Dev jy"]
    settings.save(replace(s, city="Brno", remote=False))
    assert marks() == ["Dev jy", "Dev up"]


def test_settings_save_reloads_open_cv_window(window, monkeypatch, tmp_path):
    s = use_settings(config.CV_PATH, text="First CV")
    window.load_rows()
    window.cv_button.click()
    other = tmp_path / "other.md"
    other.write_text("Second CV", encoding="utf-8")

    class FakeDialog:  # "Save" in the Settings window picks another CV file
        def __init__(self, current, parent):
            pass

        def exec(self):
            settings.save(replace(s, cv_path=str(other)))
            return QDialog.Accepted

        def deleteLater(self):
            pass

    monkeypatch.setattr(settings_window, "SettingsDialog", FakeDialog)
    monkeypatch.setattr(window, "refresh", lambda: None)
    window.settings_button.click()
    assert "Second CV" in window.cv_window.body.toPlainText()
    window.cv_window.close()
    reloads = []  # an error raised inside a Qt slot would not reach pytest, so calls are recorded
    monkeypatch.setattr(window.cv_window, "reload", lambda: reloads.append(True))
    window.settings_button.click()
    assert reloads == []  # a closed window is read again when it is opened


def test_closed_application_marked(window):
    use_settings(config.CV_PATH)  # temporary CV from the fixture
    key = worker.read_cv(settings.load())[1]
    for url, source, title in [("jb", "Jobicy", "Dev JB"), ("him", "Himalayas", "Dev H")]:
        db.save_jobs(source, [Job(url=url, source=source, title=title, company=url, city="Prague",
                                  published="2026-10-01", description="")])
        db.save_evaluation(url, row(url, 8)["evaluation"], key)
        db.apply(url)
        db.save_jobs(source, [])  # gone from the source's results
    window.load_rows()
    window.show_tab(1)
    by_title = {window.applied_table.item(i, 1).text(): i for i in range(window.applied_table.rowCount())}
    assert set(by_title) == {"⊘ Dev JB", "Dev H"}
    window.applied_table.selectRow(by_title["⊘ Dev JB"])
    assert not window.d_closed.isHidden()
    assert window.d_closed.text() == "No longer listed on Jobicy — probably filled"
    window.applied_table.selectRow(by_title["Dev H"])
    assert window.d_closed.isHidden()


def test_undo_toast_stays_usable_after_tab_switch_and_resize(window):
    add_found("a", 8, title="A very long job title that keeps going " * 4)
    add_found("b", 7)
    window.load_rows()
    window.show()
    QApplication.processEvents()
    window.table.selectRow(0)
    window.hide_button.click()
    window.show_tab(1)  # a trip to another tab within the 10 s
    window.show_tab(0)
    QApplication.processEvents()
    card = window.found_card
    center = window.undo_button.mapTo(card, window.undo_button.rect().center())
    assert card.childAt(center) is window.undo_button  # on top, so a click reaches Undo
    window.resize(900, 600)
    QApplication.processEvents()
    assert card.rect().contains(window.undo_toast.geometry())  # long title elided, toast kept inside


def test_close_hides_to_tray_and_marks_seen(tray_window, monkeypatch):
    actions = [action.text() for action in tray_window.tray.contextMenu().actions()]
    assert actions == ["Open Job Finder", "Refresh now", "", "Quit"]
    messages = []
    monkeypatch.setattr(tray_window.tray, "showMessage", lambda *args: messages.append(args[1]))
    released = []
    monkeypatch.setattr(llm, "release", lambda wait=True: released.append(wait))
    db.save_jobs("Jobicy", [Job(url="a", source="Jobicy", title="Dev", company="A", city="", published="",
                                description="")])
    db.save_evaluation("a", row("a", 8)["evaluation"], "key")  # shown in the list (not evaluated stays new)
    tray_window.worker.model_loaded = True  # a refresh is still running
    tray_window.refreshing = True
    tray_window.show()
    tray_window.close()
    assert not tray_window.isVisible() and tray_window.exits == [] and released == []  # still running
    assert db.unseen_urls() == set()  # what was in the list is no longer new
    assert len(messages) == 1 and "Quit" in messages[0]  # how to close it, once per run
    tray_window.show_window()
    tray_window.close()
    assert len(messages) == 1


def test_close_without_tray_quits(window):
    assert window.tray is None
    window.show()
    window.close()
    assert not window.isVisible()


def test_quit_closes_for_real(tray_window, monkeypatch):
    released = []
    monkeypatch.setattr(llm, "release", lambda wait=True: released.append(wait))
    tray_window.worker.model_loaded = True
    tray_window.refreshing = True
    monkeypatch.setattr(tray_window, "confirm_close", lambda: False)
    tray_window.quit_app()
    assert tray_window.exits == [] and not tray_window.quitting  # "Cancel": the app keeps running
    monkeypatch.setattr(tray_window, "confirm_close", lambda: True)
    tray_window.quit_app()
    assert tray_window.exits == [True] and released == [False] and not tray_window.tray.isVisible()
    assert QApplication.quitOnLastWindowClosed() is False  # with a tray only Quit ends the app


def test_auto_refresh_skips_busy_and_running(tray_window, monkeypatch):
    assert tray_window.auto_timer.isActive() and tray_window.auto_timer.interval() == 3 * 3600 * 1000
    started = []
    monkeypatch.setattr(worker.Worker, "start", lambda self: started.append(True))
    monkeypatch.setattr(busy, "windows_busy", lambda: True)  # a full-screen game shares the graphics card
    tray_window.auto_refresh()
    assert started == [] and tray_window.retry_timer.isActive()
    assert tray_window.retry_timer.interval() == 15 * 60 * 1000
    monkeypatch.setattr(busy, "windows_busy", lambda: False)
    tray_window.auto_refresh()
    assert started == [True]
    tray_window.auto_refresh()
    tray_window.refresh_now()  # "Refresh now" in the tray menu
    assert started == [True]  # one refresh at a time
    tray_window.on_finished()
    tray_window.refresh_now()
    assert started == [True, True]


def test_notification_for_new_good_jobs_when_window_inactive(tray_window, monkeypatch):
    use_settings(config.CV_PATH)  # temporary CV from the fixture; threshold 5
    messages = []
    monkeypatch.setattr(tray_window.tray, "showMessage", lambda *args: messages.append(args[1]))

    def scored(url, score):
        score_new(tray_window, url, score)

    tray_window.refresh()
    scored("a", 8)
    scored("b", 6)
    tray_window.on_finished()
    assert messages == ["1 new job with a score of 7+"]
    tray_window.refresh()
    scored("c", 9)
    monkeypatch.setattr(tray_window, "isActiveWindow", lambda: True)
    tray_window.on_finished()
    assert len(messages) == 1  # the window is in front: the list shows them
    monkeypatch.setattr(tray_window, "isActiveWindow", lambda: False)
    db.mark_all_seen()
    tray_window.refresh()
    tray_window.on_evaluated(row("c", 9))  # scored again (e.g. after a settings change), but already seen
    tray_window.on_finished()
    assert len(messages) == 1
    tray_window.refresh()
    scored("e", 7)
    scored("f", 10)
    tray_window.on_finished()
    assert messages[-1] == "2 new jobs with a score of 7+"


def score_new(window, url, score):
    """A job that arrived during the current refresh and got its score."""
    db.save_jobs(f"src-{url}", [Job(url=url, source=f"src-{url}", title=f"Job {url}", company="A", city="",
                                    published=date.today().isoformat(), description="")])
    db.save_evaluation(url, row(url, score)["evaluation"], worker.read_cv(settings.load())[1])
    window.on_evaluated(row(url, score, date.today().isoformat()))


def test_notification_ignores_jobs_seen_before_hiding(tray_window, monkeypatch):
    use_settings(config.CV_PATH)
    messages = []
    monkeypatch.setattr(tray_window.tray, "showMessage", lambda *args: messages.append(args[1]))
    tray_window.show()
    tray_window.refresh()
    score_new(tray_window, "a", 8)  # it appears in the list while the window is open
    tray_window.close()  # hidden: what was in the list counts as seen
    tray_window.on_finished()
    assert not [m for m in messages if "with a score of" in m]  # only the "keeps running in the tray" hint


def test_second_launch_opens_the_running_window(tray_window, monkeypatch):
    name = f"job_finder_test_{os.getpid()}"
    opened = []
    monkeypatch.setattr(tray_window, "show_window", lambda: opened.append(True))
    tray_window.listen_for_launches(name)
    assert tell_running_instance(name)  # the second launch hands over and quits quietly
    for _ in range(100):
        QApplication.processEvents()
        if opened:
            break
        time.sleep(0.02)
    assert opened == [True]
    assert not tell_running_instance(name + "_nobody")  # nothing running: the old message is shown


def test_refresh_never_runs_twice(tray_window, monkeypatch):
    starts = []
    monkeypatch.setattr(worker.Worker, "start", lambda self: starts.append(True))
    s = use_settings(config.CV_PATH)
    tray_window.load_rows()
    tray_window.refresh()
    assert not tray_window.refresh_action.isEnabled()  # "Refresh now" in the tray menu
    tray_window.refresh()  # e.g. the timer fired while the Settings window was open
    assert starts == [True]

    class FakeDialog:  # saved during the running pass: the search changed
        def __init__(self, current, parent):
            pass

        def exec(self):
            settings.save(replace(s, city="Brno"))
            return QDialog.Accepted

        def deleteLater(self):
            pass

    monkeypatch.setattr(settings_window, "SettingsDialog", FakeDialog)
    tray_window.open_settings()
    assert starts == [True]
    tray_window.on_finished()  # one more pass with the new settings
    assert starts == [True, True]
    tray_window.on_finished()
    assert starts == [True, True] and tray_window.refresh_action.isEnabled()


def test_show_window_keeps_maximized(tray_window):
    tray_window.showMaximized()
    tray_window.close()
    tray_window.show_window()
    assert tray_window.isVisible() and tray_window.isMaximized()


def test_tray_clicks(tray_window, monkeypatch):
    opened = []
    monkeypatch.setattr(tray_window, "show_window", lambda: opened.append(True))
    tray_window.on_tray_activated(QSystemTrayIcon.Context)  # the right click opens the menu, not the window
    tray_window.on_tray_activated(QSystemTrayIcon.Trigger)
    assert opened == [True]
    monkeypatch.setattr(tray_window.tray, "showMessage", lambda *args: None)
    tray_window.show()
    tray_window.close()  # the "keeps running in the tray" hint
    tray_window.tray.messageClicked.emit()
    assert opened == [True]  # clicking the hint does not bring back the window just closed
    use_settings(config.CV_PATH)
    tray_window.refresh()
    score_new(tray_window, "a", 9)
    tray_window.on_finished()  # "1 new job with a score of 7+"
    tray_window.tray.messageClicked.emit()
    assert opened == [True, True]


def test_paused_refresh_is_retried(tray_window):
    tray_window.refresh()
    tray_window.worker.paused = True  # a full-screen game started during scoring
    tray_window.on_finished()
    assert tray_window.retry_timer.isActive()


def test_gone_job_shown_muted_with_a_note(window):
    add_found("a", 8)
    add_found("b", 7)
    with sqlite3.connect(config.DB_PATH) as conn:  # fresh jobs: muted only because one of them is gone
        conn.execute("UPDATE jobs SET published = ?, first_seen = ?", (date.today().isoformat(),) * 2)
    db.save_jobs("src-a", [])  # "a" is no longer in its source's list
    window.load_rows()
    rows = {window.table.item(i, 1).text(): i for i in range(window.table.rowCount())}
    assert set(rows) == {"Job a", "Job b"}  # still in the list for a week
    gone = rows["Job a"]
    assert "no longer listed" in window.table.item(gone, 4).text()
    assert window.table.item(gone, 1).foreground().color().name() == style.COLORS["muted"]
    window.table.selectRow(gone)
    assert not window.d_gone.isHidden() and "src-a" in window.d_gone.text() and "check" in window.d_gone.text()
    assert "no longer listed" not in window.table.item(rows["Job b"], 4).text()
    assert window.table.item(rows["Job b"], 1).foreground().color().name() != style.COLORS["muted"]
    window.table.selectRow(rows["Job b"])
    assert window.d_gone.isHidden()


def test_gone_remote_job_hidden_when_remote_is_off(window):
    s = use_settings(config.CV_PATH)
    key = worker.read_cv(s)[1]
    db.save_jobs("Remote OK", [Job(url="r", source="Remote OK", title="Remote dev", company="R", city="Remote",
                                   published=date.today().isoformat(), description="")])
    db.save_evaluation("r", row("r", 8)["evaluation"], key)
    settings.save(replace(s, remote=False))
    db.save_jobs("Remote OK", [])  # not fetched with remote off: not "gone", just not searched for
    window.load_rows()
    assert window.rows == []


def test_update_button_opens_the_release_page(window, monkeypatch):
    monkeypatch.setattr(MainWindow, "updates_on", True)
    monkeypatch.setattr(updates, "start_thread", lambda target: target())  # no thread in tests
    monkeypatch.setattr(updates, "check", lambda current=None: updates.Release("9.0.0"))  # no setup to download
    assert window.update_button.isHidden()
    window.check_updates()
    assert not window.update_button.isHidden()
    assert window.update_button.text() == "Update to 9.0.0"
    opened = []
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: opened.append(url.toString()))
    window.update_button.click()
    assert opened == [config.RELEASES_PAGE]


def test_no_update_check_when_run_from_the_sources(window, monkeypatch):
    monkeypatch.setattr(MainWindow, "updates_on", False)  # the sources are updated with git
    started = []
    monkeypatch.setattr(updates, "start_thread", lambda target: started.append(target))
    window.check_updates()
    assert started == []
    assert window.update_button.isHidden()


def test_update_checked_with_every_auto_refresh(tray_window, monkeypatch):
    monkeypatch.setattr(MainWindow, "updates_on", True)
    checks = []
    monkeypatch.setattr(updates, "start_thread", lambda target: checks.append(target))
    monkeypatch.setattr(busy, "windows_busy", lambda: True)  # even while a game runs: one small request
    tray_window.auto_timer.timeout.emit()
    assert len(checks) == 1


def test_update_notified_once_from_the_tray(tray_window, monkeypatch):
    messages, opened = [], []
    monkeypatch.setattr(tray_window.tray, "showMessage", lambda *args: messages.append(args[1]))
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: opened.append(url.toString()))
    monkeypatch.setattr(tray_window, "isActiveWindow", lambda: False)
    tray_window.on_update("9.0.0")
    assert messages == ["Version 9.0.0 is out. Click here to download it."]
    tray_window.tray.messageClicked.emit()
    assert opened == [config.RELEASES_PAGE]
    tray_window.on_update("9.0.0")  # the next check finds the same version
    assert len(messages) == 1
    tray_window.on_update("9.1.0")
    assert len(messages) == 2
    assert tray_window.update_button.text() == "Update to 9.1.0"
    monkeypatch.setattr(tray_window, "isActiveWindow", lambda: True)
    tray_window.on_update("9.2.0")  # the window is in front: the button is enough
    assert len(messages) == 2


def test_tray_tooltip_shows_the_version(tray_window):
    assert tray_window.tray.toolTip() == f"Job Finder {config.VERSION}"


def test_status_stays_one_line(window):
    window.resize(1200, 750)
    window.show()

    def shown():  # what is painted; text() is the whole status
        return QLabel.text(window.status_label)

    error = "LM Studio: model failed to load: " + "\n".join(f"line {i} of a long error from LM Studio" for i in range(60))
    window.status_label.setText(error)
    height = window.status_label.fontMetrics().height()
    assert window.status_label.sizeHint().height() <= 2 * height
    assert shown().endswith("…")
    assert "\n" not in shown()
    assert window.status_label.toolTip() == error
    assert window.status_label.text() == error
    window.status_label.setText("Done: 3 matches out of 10 evaluated")
    assert shown() == "Done: 3 matches out of 10 evaluated"
    assert window.status_label.toolTip() == ""


def test_get_model_button_and_refresh_after_the_download(window, monkeypatch):
    from job_finder import ready_window
    assert window.model_button.isHidden()
    window.worker.model_missing = True  # a pass that had jobs to score but no model
    window.on_finished()
    assert not window.model_button.isHidden()
    refreshed = []
    monkeypatch.setattr(MainWindow, "refresh", lambda self: refreshed.append(self))
    ready_window.downloader().done.emit(0)  # the download from the wizard or the button has finished
    assert refreshed.count(window) == 1
    window.worker.model_missing = False
    window.on_finished()
    assert window.model_button.isHidden()


def test_get_model_button_opens_getting_ready(window, monkeypatch):
    from job_finder import lmstudio, ready_window
    monkeypatch.setattr(lmstudio, "lms_installed", lambda: True)
    monkeypatch.setattr(lmstudio, "have_model", lambda model: True)  # downloaded in the meantime
    monkeypatch.setattr(ready_window, "vram_gb", lambda: 12.0)
    shown, refreshed = [], []
    monkeypatch.setattr(ready_window.ReadyDialog, "exec", lambda dialog: shown.append(dialog.panel.model) or 0)
    monkeypatch.setattr(MainWindow, "refresh", lambda self: refreshed.append(self))
    window.model_button.click()
    assert shown == [config.MODEL] and refreshed == [window]


def test_card_names_the_site_behind_junior_guru(window):
    window.on_evaluated(row("https://www.linkedin.com/jobs/view/1/", 8) | {"source": "junior.guru"})
    window.table.selectRow(0)
    assert window.facts["source"].text() == "junior.guru (from LinkedIn)"


def list_marks(w, key):
    rows = w.detail_lists[key][2]
    return [rows.itemAt(i).layout().itemAt(0).widget().text() for i in range(rows.count())]


def counted_row(url="c"):
    """A job scored the new way: the model's requirements, counted by the program."""
    r = row(url, 6)
    r["evaluation"] = {
        "score": 6, "summary": "Python and SQL match; Docker is missing.",
        "requirements": [{"requirement": "Python", "required": True, "match": "yes"},
                         {"requirement": "SQL", "required": True, "match": "yes"},
                         {"requirement": "Django (has FastAPI)", "required": True, "match": "similar"},
                         {"requirement": "Docker", "required": True, "match": "no"},
                         {"requirement": "React", "required": False, "match": "no"},
                         {"requirement": "AWS", "required": False, "match": "no"}],
        "blockers": [], "counted": {"must": [2.7, 4], "nice": [0.0, 2], "base": 6, "cap": None},
        "have": ["Python", "SQL", "Django (has FastAPI)"], "missing": ["Docker", "React", "AWS"], "risks": []}
    return r


def test_card_shows_how_the_score_is_counted(window):
    window.on_evaluated(counted_row())
    window.table.selectRow(0)
    assert window.detail_lists["have"][0].text() == "MUST-HAVE · 3 of 4"
    assert list_texts(window, "have") == ["Python", "SQL", "Django (has FastAPI)", "Docker"]
    assert list_marks(window, "have") == ["✓", "✓", "≈", "✕"]
    assert window.detail_lists["missing"][0].text() == "NICE TO HAVE · 0 of 2"
    assert list_marks(window, "missing") == ["✕", "✕"]
    assert window.detail_lists["risks"][0].text() == "BLOCKERS"
    assert list_texts(window, "risks") == ["No blockers found"]
    assert not window.d_counted.isHidden()
    assert window.d_counted.text() == "Counted: must-have 2.7 of 4 · nice to have 0 of 2 → 6/10"
    assert "1 + 9" in window.d_counted.toolTip()


def test_card_shows_the_ceiling(window):
    r = counted_row()
    r["score"] = r["evaluation"]["score"] = 7  # a low ceiling would hide the job: the list starts at 5
    r["evaluation"]["counted"] = {"must": [2.0, 2], "nice": [0.0, 0], "base": 10, "cap": 7}
    r["evaluation"]["risks"] = ["The ad names few concrete requirements: read it before applying (score at most 7)"]
    window.on_evaluated(r)
    window.table.selectRow(0)
    assert window.d_counted.text().endswith("2 of 2 · nice to have 0 of 0 → 10/10, ceiling 7")
    assert list_texts(window, "risks") == [r["evaluation"]["risks"][0]] and list_marks(window, "risks") == ["!"]


def test_card_of_an_old_score_stays_as_it_was(window):
    window.on_evaluated(counted_row("new"))
    window.on_evaluated(row("old", 9))  # e.g. an application scored before the counted score
    window.table.selectRow(1)
    window.table.selectRow(0)
    assert window.current["url"] == "old"
    assert window.detail_lists["have"][0].text() == "YOU HAVE · 1" and list_marks(window, "have") == ["✓"]
    assert window.detail_lists["risks"][0].text() == "RISKS"
    assert window.d_counted.isHidden()


SETUP_PATH = str(Path("C:/Users/me/AppData/Local/Job Finder/update/JobFinder-Setup-9.0.0.exe"))


@pytest.fixture
def applied(monkeypatch):
    calls = []
    monkeypatch.setattr(updates, "apply", lambda setup, restart=True: calls.append((str(setup), restart)))
    return calls


def test_restart_to_update(tray_window, applied):
    tray_window.on_update_ready("9.0.0", SETUP_PATH)  # downloaded in the background
    assert not tray_window.update_button.isHidden()
    assert tray_window.update_button.text() == "Restart to update"
    tray_window.update_button.click()
    assert applied == [(SETUP_PATH, True)] and tray_window.exits == [True]


def test_restart_to_update_asks_while_scoring(tray_window, applied, monkeypatch):
    tray_window.on_update_ready("9.0.0", SETUP_PATH)
    tray_window.refreshing = True
    monkeypatch.setattr(tray_window, "confirm_close", lambda: False)  # "Cancel"
    tray_window.update_button.click()
    assert applied == [] and tray_window.exits == []


def test_quit_installs_a_downloaded_update(tray_window, applied):
    tray_window.on_update_ready("9.0.0", SETUP_PATH)
    tray_window.quit_app()
    assert applied == [(SETUP_PATH, False)] and tray_window.exits == [True]  # installed, not opened again


def test_quit_without_an_update_installs_nothing(tray_window, applied):
    tray_window.quit_app()
    assert applied == [] and tray_window.exits == [True]


def test_ready_update_notified_once_from_the_tray(tray_window, applied, monkeypatch):
    messages = []
    monkeypatch.setattr(tray_window.tray, "showMessage", lambda *args: messages.append(args[1]))
    monkeypatch.setattr(tray_window, "isActiveWindow", lambda: False)
    tray_window.on_update_ready("9.0.0", SETUP_PATH)
    tray_window.on_update_ready("9.0.0", SETUP_PATH)  # the next check finds it downloaded already
    assert messages == ["Version 9.0.0 is ready. Click here to restart and update."]
    tray_window.tray.messageClicked.emit()
    assert applied == [(SETUP_PATH, True)]


def test_an_unreadable_cv_keeps_the_list(window):
    use_settings(config.CV_PATH)
    add_found("a", 8)
    window.load_rows()
    assert titles(window) == ["Job a"]
    config.CV_PATH.unlink()  # the file and its copy are gone
    if config.CV_COPY.exists():
        config.CV_COPY.unlink()
    window.load_rows()
    assert titles(window) == ["Job a"]  # still there
    assert "Can't read your CV" in window.status_label.text()


def test_empty_applications_explain_themselves(window):
    window.applied_tab.click()
    assert window.applied_pages.currentIndex() == 1
    assert "I applied" in window.applied_empty.text()
    window.found_tab.click()
