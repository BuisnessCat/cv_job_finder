"""Main window: found jobs and applications, a card with the selected job's analysis."""
from datetime import date

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView, QButtonGroup, QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel, QMainWindow,
    QPlainTextEdit, QProgressBar, QPushButton, QScrollArea, QSplitter, QStackedWidget, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from job_finder import config, db, llm, sources, style
from job_finder.worker import Worker, read_cv

COLUMNS = ["Score", "Job", "Company", "Location", "Date"]
APPLIED_COLUMNS = ["Applied", "Job", "Company", "Status", "Days waiting", "Score"]
LISTS = [("have", "YOU HAVE", "✓"), ("missing", "MISSING", "✕"), ("risks", "RISKS", "!")]
EMPTY_LIST = {"have": "—", "missing": "Nothing major"}
STATUS_TEXT = {"applied": "Waiting", "accepted": "Accepted", "rejected": "Rejected"}
REPOST_MARK = "↻ "  # before the title of a found job you already applied to
NEW_MARK = "• "  # before the title of a job that appeared after the window was last closed


def _label(name: str = "") -> QLabel:
    """A label with plain text; name: the style name from style.py."""
    label = QLabel()
    label.setObjectName(name)
    label.setTextFormat(Qt.PlainText)  # plain text only, no HTML
    label.setWordWrap(True)
    label.setTextInteractionFlags(Qt.TextSelectableByMouse)
    return label


def _caption(text: str) -> QLabel:
    label = _label("section")
    label.setText(text)
    return label


def _make_table(columns: list[str], center: int) -> QTableWidget:
    """A table in the common style: whole-row selection, no grid; the center column (score) is centered."""
    table = QTableWidget(0, len(columns))
    table.setHorizontalHeaderLabels(columns)
    table.setSelectionBehavior(QAbstractItemView.SelectRows)
    table.setSelectionMode(QAbstractItemView.SingleSelection)
    table.setEditTriggers(QAbstractItemView.NoEditTriggers)
    table.verticalHeader().hide()
    table.verticalHeader().setDefaultSectionSize(34)
    table.setShowGrid(False)
    table.setAlternatingRowColors(True)
    header = table.horizontalHeader()
    header.setSectionResizeMode(QHeaderView.ResizeToContents)
    header.setSectionResizeMode(1, QHeaderView.Stretch)
    # Headers aligned to the same edge as the cell text
    header.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    table.horizontalHeaderItem(center).setTextAlignment(Qt.AlignCenter)
    return table


def _score_item(score: int) -> QTableWidgetItem:
    """Score cell: centered, bold, colored by score."""
    item = QTableWidgetItem(str(score))
    item.setTextAlignment(Qt.AlignCenter)
    item.setForeground(QColor(style.score_colors(score)[1]))
    font = item.font()
    font.setBold(True)
    item.setFont(font)
    return item


def _fill_table(table: QTableWidget, rows: list[dict], values, selected_url: str | None) -> None:
    """Fill a table: values(row) gives the row cells (text or ready QTableWidgetItem); selection by url."""
    table.blockSignals(True)
    table.clearSelection()
    table.setRowCount(len(rows))
    for i, row in enumerate(rows):
        for column, value in enumerate(values(row)):
            table.setItem(i, column, value if isinstance(value, QTableWidgetItem) else QTableWidgetItem(value))
        if row["url"] == selected_url:
            table.selectRow(i)
    table.blockSignals(False)


def days_waiting(applied_at: str, today: date) -> int:
    """Days since the application."""
    return (today - date.fromisoformat(applied_at)).days


def plural_days(n: int) -> str:
    """"1 day", "3 days"."""
    return f"{n} day" if n == 1 else f"{n} days"


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Job Finder")
        self.resize(1200, 750)
        self.rows: list[dict] = []        # found jobs in display order
        self.applied: list[dict] = []     # applications, newest first
        self.applied_by_key: dict[tuple[str, str], dict] = {}  # latest application by "company + title"
        self.new_urls: set[str] = set()  # unseen: appeared after the window was last closed
        self.current: dict | None = None  # selected row: a found job or an application (has a status key)

        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.setObjectName("primary")
        self.refresh_button.clicked.connect(self.refresh)
        self.found_tab = QPushButton()
        self.found_tab.setObjectName("segmentLeft")
        self.applied_tab = QPushButton()
        self.applied_tab.setObjectName("segmentRight")
        self.tabs = QButtonGroup(self)  # the "Found | My applications" switch: exactly one button is checked
        for index, button in enumerate((self.found_tab, self.applied_tab)):
            button.setCheckable(True)
            self.tabs.addButton(button, index)
        self.found_tab.setChecked(True)
        self.tabs.idClicked.connect(self.show_tab)
        tabs = QHBoxLayout()
        tabs.setSpacing(0)
        tabs.addWidget(self.found_tab)
        tabs.addWidget(self.applied_tab)
        self.status_label = _label()
        self.progress = QProgressBar()
        self.progress.setMaximumWidth(250)
        self.progress.hide()
        self.cv_button = QPushButton("My CV")
        self.cv_button.clicked.connect(self.show_cv)
        self.cv_window = None  # the "My CV" window is created on first click
        top = QHBoxLayout()
        top.addWidget(self.refresh_button)
        top.addSpacing(style.GAP)
        top.addLayout(tabs)
        top.addSpacing(style.GAP)
        top.addWidget(self.status_label, 1)
        top.addWidget(self.progress)
        top.addWidget(self.cv_button)

        self.table = _make_table(COLUMNS, 0)
        self.table.itemSelectionChanged.connect(self.on_select)
        self.applied_table = _make_table(APPLIED_COLUMNS, 5)
        self.applied_table.itemSelectionChanged.connect(self.on_select_applied)
        self.lists = QStackedWidget()  # 0: found, 1: applications
        self.lists.addWidget(self.table)
        self.lists.addWidget(self.applied_table)

        splitter = QSplitter()
        splitter.setHandleWidth(style.GAP)
        splitter.addWidget(self.lists)
        splitter.addWidget(self._build_details())
        splitter.setSizes([700, 500])

        central = QWidget()
        central.setObjectName("central")
        layout = QVBoxLayout(central)
        layout.setContentsMargins(style.GAP, style.GAP, style.GAP, style.GAP)
        layout.setSpacing(style.GAP)
        layout.addLayout(top)
        layout.addWidget(splitter, 1)
        self.setCentralWidget(central)
        self.setStyleSheet(style.STYLESHEET)

        self.worker = Worker()
        self.worker.status.connect(self.status_label.setText)
        self.worker.progress.connect(self.on_progress)
        self.worker.evaluated.connect(self.on_evaluated)
        self.worker.finished.connect(self.on_finished)

        self.load_rows()
        QTimer.singleShot(0, self.refresh)  # refresh right after the window is shown

    def _build_details(self) -> QWidget:
        """Details card: header with the score, application pills, facts, "why", lists; buttons at the bottom."""
        self.d_title = _label("title")
        self.d_company = _label("company")
        self.badge = QFrame()
        self.badge.setObjectName("badge")
        self.badge.setFixedSize(64, 64)
        self.badge_number = QLabel(alignment=Qt.AlignCenter)
        self.badge_caption = QLabel("of 10", alignment=Qt.AlignCenter)
        badge_box = QVBoxLayout(self.badge)
        badge_box.setContentsMargins(0, 8, 0, 8)
        badge_box.setSpacing(0)
        badge_box.addWidget(self.badge_number)
        badge_box.addWidget(self.badge_caption)

        names = QVBoxLayout()
        names.setSpacing(4)
        names.addWidget(self.d_title)
        names.addWidget(self.d_company)
        head = QHBoxLayout()
        head.setSpacing(16)
        head.addLayout(names, 1)
        head.addWidget(self.badge, 0, Qt.AlignTop)

        self.d_status = _label()  # pill "Applied YYYY-MM-DD · status", applications only
        self.d_status.setWordWrap(False)
        self.d_notice = _label("notice")  # "You already applied…", reposted jobs only
        self.d_stale = _label("staleHint")  # "No reply for over N days…", under the application pill
        self.d_stale.setText(f"No reply for over {config.STALE_DAYS} days — time to follow up"
                             " or close it")
        self.notes = QPlainTextEdit()  # application notes, saved automatically
        self.notes.setObjectName("notes")
        self.notes.setFixedHeight(70)
        self.notes.setPlaceholderText("Who you talked to, when the interview is…")
        self.notes_url: str | None = None  # the application the text in the field belongs to
        self.notes_timer = QTimer(self)  # save 0.5 s after the last key press
        self.notes_timer.setSingleShot(True)
        self.notes_timer.setInterval(500)
        self.notes_timer.timeout.connect(self.save_notes)
        self.notes.textChanged.connect(self.notes_timer.start)
        self.notes_box = QWidget()
        notes_layout = QVBoxLayout(self.notes_box)
        notes_layout.setContentsMargins(0, 14, 0, 0)
        notes_layout.setSpacing(8)
        notes_layout.addWidget(_caption("NOTES"))
        notes_layout.addWidget(self.notes)

        facts = QGridLayout()
        facts.setHorizontalSpacing(16)
        facts.setVerticalSpacing(6)
        facts.setColumnStretch(1, 1)
        self.facts = {}
        for i, (key, caption) in enumerate([("city", "Location"), ("published", "Published"),
                                            ("source", "Source")]):
            name = _label("metaKey")
            name.setText(caption)
            self.facts[key] = _label()
            facts.addWidget(name, i, 0)
            facts.addWidget(self.facts[key], i, 1)

        divider = QFrame()
        divider.setObjectName("divider")
        self.d_summary = _label()

        box = QVBoxLayout()
        box.setContentsMargins(20, 18, 20, 18)
        box.setSpacing(0)
        box.addLayout(head)
        box.addWidget(self.d_status, 0, Qt.AlignLeft)  # top margin is in the pill style, a hidden pill has none
        box.addWidget(self.d_stale)
        box.addWidget(self.notes_box)
        box.addWidget(self.d_notice)
        box.addSpacing(14)
        box.addLayout(facts)
        box.addSpacing(16)
        box.addWidget(divider)
        box.addSpacing(16)
        box.addWidget(_caption("WHY THIS SCORE"))
        box.addSpacing(8)
        box.addWidget(self.d_summary)
        self.detail_lists: dict[str, tuple[QLabel, str, QVBoxLayout]] = {}
        for key, caption, _ in LISTS:
            header = _caption(caption)
            rows = QVBoxLayout()
            rows.setSpacing(6)
            box.addSpacing(18)
            box.addWidget(header)
            box.addSpacing(8)
            box.addLayout(rows)
            self.detail_lists[key] = (header, caption, rows)
        box.addStretch(1)

        details = QWidget()
        details.setObjectName("details")
        details.setLayout(box)
        scroll = QScrollArea()
        scroll.setObjectName("detailsScroll")
        scroll.setWidgetResizable(True)
        scroll.setWidget(details)

        self.open_button = QPushButton("Open job")
        self.open_button.setObjectName("primary")
        self.open_button.clicked.connect(self.open_job)
        self.apply_button = QPushButton("I applied")
        self.apply_button.clicked.connect(self.apply_job)
        self.hide_button = QPushButton("Hide")
        self.hide_button.clicked.connect(self.hide_job)
        self.waiting_button = QPushButton("Waiting")
        self.waiting_button.clicked.connect(lambda: self.set_status("applied"))
        self.accept_button = QPushButton("Accepted")
        self.accept_button.clicked.connect(lambda: self.set_status("accepted"))
        self.reject_button = QPushButton("Rejected")
        self.reject_button.clicked.connect(lambda: self.set_status("rejected"))
        self.unapply_button = QPushButton("Back to found")
        self.unapply_button.clicked.connect(self.unapply_job)
        self.status_buttons = {"applied": self.waiting_button, "accepted": self.accept_button,
                               "rejected": self.reject_button}
        self.found_buttons = (self.apply_button, self.hide_button)
        self.applied_buttons = (self.waiting_button, self.accept_button, self.reject_button, self.unapply_button)
        for button in self.applied_buttons:
            button.hide()  # otherwise the first layout sizes the card for all buttons at once
        self.d_stale.hide()
        self.notes_box.hide()
        footer = QWidget()
        footer.setObjectName("footer")
        buttons = QHBoxLayout(footer)
        buttons.setContentsMargins(20, 12, 20, 12)
        buttons.addWidget(self.open_button)
        for button in self.found_buttons + self.applied_buttons:
            buttons.addWidget(button)
        buttons.addStretch(1)

        details_page = QWidget()
        details_page.setObjectName("detailsPage")
        page_box = QVBoxLayout(details_page)
        page_box.setContentsMargins(0, 0, 0, 0)
        page_box.setSpacing(0)
        page_box.addWidget(scroll, 1)
        page_box.addWidget(footer)

        empty_page = QWidget()
        empty_page.setObjectName("emptyPage")
        empty = QLabel("Select a job on the left", alignment=Qt.AlignCenter)
        empty.setObjectName("empty")
        QVBoxLayout(empty_page).addWidget(empty)

        self.pages = QStackedWidget()  # 0: nothing selected, 1: job analysis
        self.pages.addWidget(empty_page)
        self.pages.addWidget(details_page)
        card = QFrame()
        card.setObjectName("card")
        card_box = QVBoxLayout(card)
        card_box.setContentsMargins(1, 1, 1, 1)  # do not cover the card border
        card_box.addWidget(self.pages)
        self.show_details(None)
        return card

    def _fill_list(self, key: str, mark: str, items: list[str]) -> None:
        """Fill a "you have / missing / risks" list with rows that have a colored marker."""
        header, caption, rows = self.detail_lists[key]
        header.setText(f"{caption} · {len(items)}" if items else caption)
        while rows.count():
            line = rows.takeAt(0).layout()
            while line.count():
                line.takeAt(0).widget().setParent(None)  # remove from the window now, not after deleteLater
        color = style.LIST_COLORS[key]
        if not items and key == "risks":
            items, mark, color = ["No blockers found"], "✓", style.LIST_COLORS["have"]
        elif not items:
            items, mark = [EMPTY_LIST[key]], ""
        for text in items:
            marker = QLabel(mark)
            marker.setFixedWidth(14)
            marker.setStyleSheet(f"color: {color}; font-weight: 700;")
            label = _label("" if mark else "muted")
            label.setText(text)
            line = QHBoxLayout()
            line.setSpacing(8)
            line.addWidget(marker, 0, Qt.AlignTop)
            line.addWidget(label, 1)
            rows.addLayout(line)

    def _previous_application(self, row: dict) -> dict | None:
        """The application to a job with the same company and title (a reposted job) or None."""
        return self.applied_by_key.get(sources.same_job_key(row["company"], row["title"]))

    def load_rows(self) -> None:
        """Re-read found jobs (scored under the current CV) and applications from the database."""
        cv = read_cv()
        self.rows = db.list_jobs(cv[1], config.MIN_SCORE) if cv else []
        self.applied = db.list_applied()
        # reversed: with several applications under one key, the newest stays
        self.applied_by_key = {sources.same_job_key(r["company"], r["title"]): r for r in reversed(self.applied)}
        self.new_urls = db.unseen_urls()
        self.render()
        self.render_applied()

    def render(self) -> None:
        """Redraw found jobs keeping the selection; leave an application in the card alone."""
        selected = self.current["url"] if self.current and "status" not in self.current else None

        def values(row):
            title = (REPOST_MARK if self._previous_application(row) else "") + row["title"]
            title_item = QTableWidgetItem(title)
            if row["url"] in self.new_urls:
                title_item.setText(NEW_MARK + title)
                font = title_item.font()
                font.setBold(True)
                title_item.setFont(font)
            return [_score_item(row["score"]), title_item, row["company"], row["city"], row["published"]]

        _fill_table(self.table, self.rows, values, selected)
        new = sum(1 for row in self.rows if row["url"] in self.new_urls)
        self.found_tab.setText(f"Found · {len(self.rows)}" + (f" (+{new})" if new else ""))
        if selected and selected not in (row["url"] for row in self.rows):
            self.show_details(None)

    def render_applied(self) -> None:
        """Redraw applications keeping the selection; leave a found job in the card alone."""
        selected = self.current["url"] if self.current and "status" in self.current else None

        today = date.today()

        def values(row):
            status = QTableWidgetItem(STATUS_TEXT[row["status"]])
            status.setForeground(QColor(style.STATUS_COLORS[row["status"]][1]))
            waiting = QTableWidgetItem("—")
            if row["status"] == "applied":
                days = days_waiting(row["applied_at"], today)
                waiting.setText(str(days))
                if days > config.STALE_DAYS:
                    waiting.setForeground(QColor(style.COLORS["notice_text"]))
            return [row["applied_at"], row["title"], row["company"], status, waiting, _score_item(row["score"])]

        _fill_table(self.applied_table, self.applied, values, selected)
        self.applied_tab.setText(f"My applications · {len(self.applied)}")
        if selected and selected not in (row["url"] for row in self.applied):
            self.show_details(None)

    def show_tab(self, index: int) -> None:
        """Switch the list on the left: 0 for found jobs, 1 for my applications."""
        self.lists.setCurrentIndex(index)
        self.tabs.button(index).setChecked(True)
        for table in (self.table, self.applied_table):
            table.clearSelection()
        self.show_details(None)

    def on_select(self) -> None:
        indexes = self.table.selectionModel().selectedRows()
        self.show_details(self.rows[indexes[0].row()] if indexes else None)

    def on_select_applied(self) -> None:
        indexes = self.applied_table.selectionModel().selectedRows()
        self.show_details(self.applied[indexes[0].row()] if indexes else None)

    def show_details(self, row: dict | None) -> None:
        self.save_notes()  # do not lose the previous application's note
        self.current = row
        self.pages.setCurrentIndex(0 if row is None else 1)
        if row is None:
            self.notes_url = None
            return
        evaluation = row["evaluation"]
        background, color = style.score_colors(row["score"])
        self.d_title.setText(row["title"])
        self.d_company.setText(row["company"])
        for key, label in self.facts.items():
            label.setText(row[key])
        self.badge.setStyleSheet(f"QFrame#badge {{ background: {background}; border-radius: 10px; }}")
        self.badge_number.setText(str(row["score"]))
        self.badge_number.setStyleSheet(f"background: transparent; color: {color}; font-size: 20pt;"
                                        " font-weight: 700;")
        self.badge_caption.setStyleSheet(f"background: transparent; color: {color}; font-size: 8pt;")
        self.d_summary.setText(evaluation.get("summary") or "—")
        self.d_summary.setStyleSheet(f"background: {style.COLORS['alt']}; border-left: 3px solid {color};"
                                     " border-radius: 4px; padding: 10px 12px;")
        for key, _, mark in LISTS:
            self._fill_list(key, mark, evaluation.get(key) or [])

        is_application = "status" in row
        self.d_status.setVisible(is_application)
        self.notes_box.setVisible(is_application)
        stale = False
        if is_application:
            text = f"Applied {row['applied_at']} · {STATUS_TEXT[row['status']]}"
            pill_background, pill_color = style.STATUS_COLORS[row["status"]]
            if row["status"] == "applied":
                days = days_waiting(row["applied_at"], date.today())
                text += f" · {plural_days(days)}"
                stale = days > config.STALE_DAYS
                if stale:
                    pill_background, pill_color = style.COLORS["notice_bg"], style.COLORS["notice_text"]
            self.d_status.setText(text)
            self.d_status.setStyleSheet(f"background: {pill_background}; color: {pill_color};"
                                        " border-radius: 6px; padding: 6px 12px; font-weight: 600; margin-top: 12px;")
            self.notes_url = row["url"]
            self.notes.blockSignals(True)  # filling in text is not an edit, no save timer needed
            self.notes.setPlainText(row["notes"])
            self.notes.blockSignals(False)
        else:
            self.notes_url = None
        self.d_stale.setVisible(stale)
        previous = None if is_application else self._previous_application(row)
        self.d_notice.setVisible(previous is not None)
        if previous:
            self.d_notice.setText(f'You already applied to "{previous["title"]}" at {previous["company"]}'
                                  f' on {previous["applied_at"]} — status: {STATUS_TEXT[previous["status"]].lower()}')
        for button in self.found_buttons:
            button.setVisible(not is_application)
        self.unapply_button.setVisible(is_application)
        for status, button in self.status_buttons.items():
            button.setVisible(is_application and status != row["status"])

    def refresh(self) -> None:
        self.refresh_button.setEnabled(False)
        self.load_rows()  # if the CV changed, old scores leave the list
        self.worker.start()

    def on_progress(self, done: int, total: int) -> None:
        self.progress.setMaximum(total)
        self.progress.setValue(done)
        self.progress.show()
        self.status_label.setText(f"Evaluated {done} of {total}")

    def on_evaluated(self, row: dict) -> None:
        if row["score"] < config.MIN_SCORE:
            return
        self.rows.append(row)
        self.rows.sort(key=lambda r: (r["score"], r["published"]), reverse=True)
        self.new_urls = db.unseen_urls()  # the job may have reached the database after the list was loaded
        self.render()

    def on_finished(self) -> None:
        self.progress.hide()
        self.refresh_button.setEnabled(True)
        self.load_rows()  # drop jobs that vanished from the source or were filtered out by location

    def show_cv(self) -> None:
        """Show the "My CV" window with the current file; one window for the whole app."""
        # Imported here, not at the top: cv_window itself takes _label from this module
        from job_finder.cv_window import CvWindow
        if self.cv_window is None:
            self.cv_window = CvWindow(self)
        self.cv_window.reload()
        self.cv_window.show()
        self.cv_window.raise_()
        self.cv_window.activateWindow()

    def open_job(self) -> None:
        QDesktopServices.openUrl(QUrl(self.current["url"]))

    def hide_job(self) -> None:
        url = self.current["url"]
        db.hide(url)
        self.rows = [row for row in self.rows if row["url"] != url]
        self.show_details(None)
        self.render()

    def apply_job(self) -> None:
        """I applied: the job moves from found to the "My applications" tab."""
        db.apply(self.current["url"])
        self.show_details(None)
        self.load_rows()

    def set_status(self, status: str) -> None:
        """Mark the application outcome; the card stays on this application and shows the new status."""
        url = self.current["url"]
        db.set_status(url, status)
        self.load_rows()
        self.show_details(next(row for row in self.applied if row["url"] == url))

    def unapply_job(self) -> None:
        """Back to found, in case "I applied" was clicked by mistake."""
        db.unapply(self.current["url"])
        self.show_details(None)
        self.load_rows()

    def save_notes(self) -> None:
        """Save the note of the application open in the card if the text changed."""
        self.notes_timer.stop()
        if self.notes_url is None:
            return
        row = next((r for r in self.applied if r["url"] == self.notes_url), None)
        text = self.notes.toPlainText()
        if row is None or row["notes"] == text:
            return
        db.set_notes(self.notes_url, text)
        row["notes"] = text

    def closeEvent(self, event) -> None:
        self.save_notes()
        db.mark_all_seen()  # on the next start only jobs arriving after this will be new
        if self.worker.model_loaded:
            llm.release(wait=False)  # do not wait: the window must close right away
        event.accept()
