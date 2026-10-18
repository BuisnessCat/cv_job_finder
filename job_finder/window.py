"""Main window: found jobs and applications, a card with the selected job's analysis."""
import time
from datetime import date

from PySide6.QtCore import QEvent, Qt, QTimer, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QIcon
from PySide6.QtNetwork import QLocalServer
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QButtonGroup, QDialog, QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QMainWindow, QMenu, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QScrollArea, QSplitter,
    QStackedWidget, QSystemTrayIcon, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from job_finder import busy, config, db, freshness, insights, llm, settings, sources, style
from job_finder.settings import Settings
from job_finder.worker import Worker, read_cv

COLUMNS = ["Score", "Job", "Company", "Location", "Posted"]
APPLIED_COLUMNS = ["Applied", "Job", "Company", "Status", "Days waiting", "Score"]
LISTS = [("have", "YOU HAVE", "✓"), ("missing", "MISSING", "✕"), ("risks", "RISKS", "!")]
EMPTY_LIST = {"have": "—", "missing": "Nothing major"}
STATUS_TEXT = {"applied": "Waiting", "accepted": "Accepted", "rejected": "Rejected"}
REPOST_MARK = "↻ "  # before the title of a found job you already applied to
NEW_MARK = "• "  # before the title of a job that appeared after the window was last closed
BAR_WIDTH = 220  # the longest bar on the Insights tab
RETRY_MINUTES = 15  # the automatic refresh waits this long while a full-screen game runs
TRAY_HINT = (f"Job Finder keeps running in the tray and looks for new jobs every {config.AUTO_REFRESH_HOURS} hours. "
             "To close it, right-click the icon and choose Quit.")


def _search_changed(old: Settings, new: Settings) -> bool:
    """What is downloaded, filtered or how it is scored changed, not only a threshold: a new search is needed."""
    return settings.scoring_changed(old, new) or (old.main_skill, old.skills) != (new.main_skill, new.skills)


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

def _bar_row(name: str, count: int, yours: int, scale: int, mine: bool = False) -> QWidget:
    """Insights row: name, a bar (green part counted as yours, red part missing) and the number of jobs."""
    row = QWidget()
    line = QHBoxLayout(row)
    line.setContentsMargins(0, 0, 0, 0)
    line.setSpacing(10)
    label = QLabel(("✓ " if mine else "") + name)
    label.setObjectName("barName")
    label.setFixedWidth(180)
    if mine:
        label.setStyleSheet(f"color: {style.LIST_COLORS['have']};")
    track = QFrame()
    track.setFixedSize(max(2, round(BAR_WIDTH * count / scale)), 10)
    parts = QHBoxLayout(track)
    parts.setContentsMargins(0, 0, 0, 0)
    parts.setSpacing(0)
    for color, size in ((style.LIST_COLORS["have"], yours), (style.LIST_COLORS["missing"], count - yours)):
        if size > 0:
            part = QFrame()
            part.setStyleSheet(f"background: {color}; border-radius: 3px;")
            parts.addWidget(part, size)
    number = QLabel(str(count))
    number.setObjectName("barCount")
    line.addWidget(label)
    line.addWidget(track)
    line.addWidget(number)
    line.addStretch(1)
    return row


class MainWindow(QMainWindow):
    clock = staticmethod(time.monotonic)  # for the time-left estimate; tests replace it
    tray_available = staticmethod(QSystemTrayIcon.isSystemTrayAvailable)  # tests replace it
    exit_app = staticmethod(QApplication.quit)  # ends the event loop after Quit; tests replace it

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Job Finder")
        self.resize(1200, 750)
        self.rows: list[dict] = []        # found jobs scored above the threshold
        self.visible: list[dict] = []     # found jobs that pass the filters, in table order
        self.applied: list[dict] = []     # applications, newest first
        self.applied_by_key: dict[tuple[str, str], dict] = {}  # latest application by "company + title"
        self.new_urls: set[str] = set()  # unseen: appeared after the window was last closed
        self.current: dict | None = None  # selected row: a found job or an application (has a status key)
        self.refreshing = False  # a refresh (download or scoring) is running
        self.refresh_again = False  # the search changed during a refresh: one more pass after it
        self.scored_urls: set[str] = set()  # jobs scored during the current refresh, for the notification
        self.started = 0.0  # when the current scoring pass began, by clock()
        self.description_open = False  # the card's description stays open from job to job
        self.settings: Settings | None = None  # re-read with the list; None before the first-run wizard

        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.setObjectName("primary")
        self.refresh_button.clicked.connect(self.refresh)
        self.found_tab = QPushButton()
        self.found_tab.setObjectName("segmentLeft")
        self.applied_tab = QPushButton()
        self.applied_tab.setObjectName("segmentMiddle")
        self.insights_tab = QPushButton("Insights")
        self.insights_tab.setObjectName("segmentRight")
        self.tabs = QButtonGroup(self)  # "Found | My applications | Insights": exactly one button is checked
        for index, button in enumerate((self.found_tab, self.applied_tab, self.insights_tab)):
            button.setCheckable(True)
            self.tabs.addButton(button, index)
        self.found_tab.setChecked(True)
        self.tabs.idClicked.connect(self.show_tab)
        tabs = QHBoxLayout()
        tabs.setSpacing(0)
        tabs.addWidget(self.found_tab)
        tabs.addWidget(self.applied_tab)
        tabs.addWidget(self.insights_tab)
        self.status_label = _label()
        self.progress = QProgressBar()
        self.progress.setMaximumWidth(250)
        self.progress.hide()
        self.cv_button = QPushButton("My CV")
        self.cv_button.clicked.connect(self.show_cv)
        self.cv_window = None  # the "My CV" window is created on first click
        self.settings_button = QPushButton("Settings")
        self.settings_button.clicked.connect(self.open_settings)
        top = QHBoxLayout()
        top.addWidget(self.refresh_button)
        top.addSpacing(style.GAP)
        top.addLayout(tabs)
        top.addSpacing(style.GAP)
        top.addWidget(self.status_label, 1)
        top.addWidget(self.progress)
        top.addWidget(self.cv_button)
        top.addWidget(self.settings_button)

        self.table = _make_table(COLUMNS, 0)
        # A long list of remote regions must not squeeze the title: fixed width, the rest is elided (full text in the card)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Interactive)
        self.table.setColumnWidth(3, 150)
        self.table.itemSelectionChanged.connect(self.on_select)
        self.applied_table = _make_table(APPLIED_COLUMNS, 5)
        self.applied_table.itemSelectionChanged.connect(self.on_select_applied)
        self.lists = QStackedWidget()  # 0: found, 1: applications
        self.lists.addWidget(self._build_found())
        self.lists.addWidget(self.applied_table)
        self._build_undo()

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
        self.views = QStackedWidget()  # 0: list and card, 1: insights
        self.views.addWidget(splitter)
        self.views.addWidget(self._build_insights())
        layout.addWidget(self.views, 1)
        self.setCentralWidget(central)
        self.setStyleSheet(style.STYLESHEET)

        self.worker = Worker()
        self.worker.status.connect(self.status_label.setText)
        self.worker.progress.connect(self.on_progress)
        self.worker.evaluated.connect(self.on_evaluated)
        self.worker.finished.connect(self.on_finished)

        self.jobs_message = False  # the last tray message was about new jobs (clicking it opens the window)
        self.refresh_action = None  # "Refresh now" in the tray menu
        self.quitting = False  # Quit from the tray: closing the window really closes the app
        self.tray_hint_shown = False
        self.tray = self._build_tray() if self.tray_available() else None
        self.auto_timer = QTimer(self)  # look for new jobs every few hours, also from the tray
        self.auto_timer.setInterval(config.AUTO_REFRESH_HOURS * 3600 * 1000)
        self.auto_timer.timeout.connect(self.auto_refresh)
        self.auto_timer.start()
        self.retry_timer = QTimer(self)  # a full-screen game was running: try again a bit later
        self.retry_timer.setSingleShot(True)
        self.retry_timer.setInterval(RETRY_MINUTES * 60 * 1000)
        self.retry_timer.timeout.connect(self.auto_refresh)

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
        self.facts, self.fact_names = {}, {}
        for i, (key, caption) in enumerate([("city", "Location"), ("published", "Published"),
                                            ("source", "Source"), ("salary", "Salary")]):
            name = self.fact_names[key] = _label("metaKey")
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
        self.d_closed = _label("muted")  # "No longer listed on …", applications only
        self.d_closed.setContentsMargins(0, 6, 0, 0)
        self.d_closed.hide()
        box.addWidget(self.d_closed)
        self.d_gone = _label("staleHint")  # "No longer listed on … since …", found jobs gone from their source
        self.d_gone.hide()
        box.addWidget(self.d_gone)
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
        description_head = QHBoxLayout()
        description_head.addWidget(_caption("DESCRIPTION"))
        description_head.addStretch(1)
        self.description_button = QPushButton("Show description")
        self.description_button.clicked.connect(self.toggle_description)
        description_head.addWidget(self.description_button)
        self.d_description = _label()
        self.d_description.hide()
        box.addSpacing(18)
        box.addLayout(description_head)
        box.addSpacing(8)
        box.addWidget(self.d_description)
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

    def _build_found(self) -> QFrame:
        """Found list in its own card: filter header, the table (or "No jobs match the filters"), the shown count."""
        self.search = QLineEdit()
        self.search.setObjectName("search")
        self.search.setPlaceholderText("Search title, company or location")
        self.search.textChanged.connect(self.render)
        self.freshness_buttons = QButtonGroup(self)
        self.order_buttons = QButtonGroup(self)
        header = QWidget()
        head = QHBoxLayout(header)
        head.setContentsMargins(12, 10, 12, 10)
        head.setSpacing(10)
        head.addWidget(self.search, 1)
        for group, labels, default in [
                (self.freshness_buttons, [(label, tip) for label, tip, _ in freshness.FRESHNESS], 2),
                (self.order_buttons, [(label, "") for label in freshness.ORDERS], 0)]:
            segment = QHBoxLayout()
            segment.setSpacing(0)
            for index, (label, tip) in enumerate(labels):
                button = QPushButton(label)
                button.setCheckable(True)
                button.setToolTip(tip)
                last = len(labels) - 1
                button.setObjectName("segmentLeft" if index == 0 else "segmentRight" if index == last else "segmentMiddle")
                group.addButton(button, index)
                segment.addWidget(button)
            group.button(default).setChecked(True)
            group.idClicked.connect(self.render)
            head.addLayout(segment)
        self.no_match = QLabel("No jobs match the filters", alignment=Qt.AlignCenter)
        self.no_match.setObjectName("empty")
        self.found_pages = QStackedWidget()  # 0: the table, 1: nothing passes the filters
        self.found_pages.addWidget(self.table)
        self.found_pages.addWidget(self.no_match)
        self.shown_label = _label("muted")
        self.shown_label.setContentsMargins(14, 6, 14, 8)
        self.shown_label.hide()
        card = QFrame()
        card.setObjectName("foundCard")
        self.found_card = card
        box = QVBoxLayout(card)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(0)
        box.addWidget(header)
        box.addWidget(self.found_pages, 1)
        box.addWidget(self.shown_label)
        return card

    def _build_undo(self) -> None:
        """The toast shown for 10 s after "Hide": "Hidden: <title>" and a green Undo, over the bottom of the list."""
        self.undo_url: str | None = None
        self.undo_title = ""
        # A free child of the Found card: it hides with the card on other tabs and stays above the table
        self.undo_toast = QFrame(self.found_card)
        self.undo_toast.setObjectName("toast")
        line = QHBoxLayout(self.undo_toast)
        line.setContentsMargins(14, 6, 6, 6)
        line.setSpacing(12)
        self.undo_label = QLabel()
        self.undo_button = QPushButton("Undo")
        self.undo_button.setObjectName("primary")
        self.undo_button.clicked.connect(self.undo)
        line.addWidget(self.undo_label)
        line.addWidget(self.undo_button)
        self.undo_toast.hide()
        self.undo_timer = QTimer(self)
        self.undo_timer.setSingleShot(True)
        self.undo_timer.setInterval(10_000)
        self.undo_timer.timeout.connect(self.undo_toast.hide)
        self.found_card.installEventFilter(self)  # keep the toast in place when the card is resized

    def _show_undo(self, row: dict) -> None:
        self.undo_url = row["url"]
        self.undo_title = row["title"]
        self._place_undo()
        self.undo_toast.raise_()
        self.undo_toast.show()
        self.undo_timer.start()  # a newer hide restarts the 10 s and replaces the older undo

    def _place_undo(self) -> None:
        """Fit the toast into the card: elide a long title, centre it near the bottom."""
        card = self.found_card
        width = max(80, card.width() - 160)
        title = self.undo_label.fontMetrics().elidedText(self.undo_title, Qt.ElideRight, width)
        self.undo_label.setText(f"Hidden: {title}")
        self.undo_toast.adjustSize()
        self.undo_toast.move(max(0, (card.width() - self.undo_toast.width()) // 2),
                             max(0, card.height() - self.undo_toast.height() - 16))

    def eventFilter(self, watched, event) -> bool:
        if watched is self.found_card and event.type() == QEvent.Resize and self.undo_toast.isVisible():
            self._place_undo()
        return super().eventFilter(watched, event)

    def undo(self) -> None:
        """Bring back the job hidden last and select it if the filters show it."""
        self.undo_timer.stop()
        self.undo_toast.hide()
        if self.undo_url is None:
            return
        url, self.undo_url = self.undo_url, None
        db.unhide(url)
        self.load_rows()
        for index, row in enumerate(self.visible):
            if row["url"] == url:
                self.table.selectRow(index)
                break

    def confirm_close(self) -> bool:
        """Ask before closing while a refresh runs; True means close."""
        box = QMessageBox(QMessageBox.Question, "Job Finder",
                          "A refresh is in progress. Close anyway? Jobs scored so far are saved.", parent=self)
        close = box.addButton("Close", QMessageBox.AcceptRole)
        box.addButton("Keep open", QMessageBox.RejectRole)
        box.exec()
        return box.clickedButton() is close

    def _build_insights(self) -> QWidget:
        """Insights tab: two cards of requirement bars and a note below (spec section 13)."""
        page = QWidget()
        page.setObjectName("insightsPage")
        box = QVBoxLayout(page)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(style.GAP)
        self.insights_message = QLabel(alignment=Qt.AlignCenter)
        self.insights_message.setObjectName("empty")
        self.insights_cards = QWidget()
        cards = QHBoxLayout(self.insights_cards)
        cards.setContentsMargins(0, 0, 0, 0)
        cards.setSpacing(style.GAP)
        self.missing_rows = QVBoxLayout()
        self.required_rows = QVBoxLayout()
        for title, subtitle, rows in [
                ("MOST OFTEN MISSING", "In how many jobs the model listed it under Missing", self.missing_rows),
                ("MOST OFTEN REQUIRED", "Green: counted as yours · red: missing", self.required_rows)]:
            card = QFrame()
            card.setObjectName("card")
            inner = QVBoxLayout(card)
            inner.setContentsMargins(20, 18, 20, 18)
            inner.setSpacing(8)
            inner.addWidget(_caption(title))
            note = _label("muted")
            note.setText(subtitle)
            inner.addWidget(note)
            inner.addSpacing(6)
            rows.setSpacing(6)
            inner.addLayout(rows)
            inner.addStretch(1)
            cards.addWidget(card)
        self.insights_note = _label("muted")
        box.addWidget(self.insights_message, 1)
        box.addWidget(self.insights_cards, 1)
        box.addWidget(self.insights_note)
        # In a scroll area: twenty fixed-width rows must not raise the whole window's minimum size
        scroll = QScrollArea()
        scroll.setObjectName("insightsScroll")
        scroll.setWidgetResizable(True)
        scroll.setWidget(page)
        return scroll

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
        self.settings = settings.load()
        cv = read_cv(self.settings)
        # Also jobs their source stopped listing in the last week: muted, with a note to check the link
        self.rows = db.list_jobs(cv[1], self.settings.min_score, config.GONE_DAYS) if cv else []
        self.applied = db.list_applied()
        for row in self.applied:  # "probably filled" only if still searched for: after a city change it isn't fetched
            row["closed"] = row["closed"] and (self.settings is None
                                               or sources.still_fetched(row["source"], row["city"], self.settings))
        # reversed: with several applications under one key, the newest stays
        self.applied_by_key = {sources.same_job_key(r["company"], r["title"]): r for r in reversed(self.applied)}
        self.new_urls = db.unseen_urls()
        self.render()
        self.render_applied()

    def render(self) -> None:
        """Redraw found jobs keeping the selection; leave an application in the card alone."""
        selected = self.current["url"] if self.current and "status" not in self.current else None

        today = date.today()
        limits = self.settings or Settings()
        days = freshness.FRESHNESS[self.freshness_buttons.checkedId()][2]
        order = freshness.ORDERS[self.order_buttons.checkedId()]
        self.visible = freshness.visible_rows(self.rows, self.search.text(), days, order, today)

        def values(row):
            title = (REPOST_MARK if self._previous_application(row) else "") + row["title"]
            title_item = QTableWidgetItem(title)
            if row["url"] in self.new_urls:
                title_item.setText(NEW_MARK + title)
                font = title_item.font()
                font.setBold(True)
                title_item.setFont(font)
            day = freshness.job_date(row["published"], row.get("first_seen", ""))
            posted = freshness.age_text(day, today)
            if freshness.is_reposted(row["published"], row.get("first_seen", "")):
                posted += " · reposted"
            gone = bool(row.get("gone_at"))
            if gone:
                posted += " · no longer listed"
            items = [title_item, QTableWidgetItem(row["company"]), QTableWidgetItem(row["city"]),
                     QTableWidgetItem(posted)]
            age = freshness.age_days(day, today)
            if gone or (age is not None and age > limits.stale_job_days):  # old or gone: muted, the score keeps its colour
                for item in items:
                    item.setForeground(QColor(style.COLORS["muted"]))
            return [_score_item(row["score"]), *items]

        _fill_table(self.table, self.visible, values, selected)
        new = sum(1 for row in self.visible if row["url"] in self.new_urls)
        self.found_tab.setText(f"Found · {len(self.visible)}" + (f" (+{new})" if new else ""))
        self.shown_label.setText(f"{len(self.visible)} of {len(self.rows)} shown")
        self.shown_label.setVisible(len(self.visible) < len(self.rows))
        self.found_pages.setCurrentIndex(1 if self.rows and not self.visible else 0)
        if selected and selected not in (row["url"] for row in self.visible):
            self.show_details(None)

    def render_applied(self) -> None:
        """Redraw applications keeping the selection; leave a found job in the card alone."""
        selected = self.current["url"] if self.current and "status" in self.current else None

        today = date.today()
        limits = self.settings or Settings()

        def values(row):
            status = QTableWidgetItem(STATUS_TEXT[row["status"]])
            status.setForeground(QColor(style.STATUS_COLORS[row["status"]][1]))
            waiting = QTableWidgetItem("—")
            if row["status"] == "applied":
                days = days_waiting(row["applied_at"], today)
                waiting.setText(str(days))
                if days > limits.stale_days:
                    waiting.setForeground(QColor(style.COLORS["notice_text"]))
            title = QTableWidgetItem(("⊘ " if row["closed"] else "") + row["title"])
            if row["closed"]:  # taken down from a source that returns its whole list
                title.setForeground(QColor(style.COLORS["muted"]))
            return [row["applied_at"], title, row["company"], status, waiting, _score_item(row["score"])]

        _fill_table(self.applied_table, self.applied, values, selected)
        self.applied_tab.setText(f"My applications · {len(self.applied)}")
        if selected and selected not in (row["url"] for row in self.applied):
            self.show_details(None)

    def render_insights(self) -> None:
        """Recount the Insights tab from the analyses of all evaluated jobs (spec section 13)."""
        self.settings = settings.load()  # they may have been saved since the list was loaded
        cv = read_cv(self.settings)
        evaluations = db.evaluations(cv[1]) if cv else []
        message = ("Can't read your CV — check it in Settings" if cv is None
                   else "Nothing evaluated yet" if not evaluations else "")
        self.insights_message.setText(message)
        self.insights_message.setVisible(bool(message))
        self.insights_cards.setVisible(not message)
        self.insights_note.setVisible(not message)
        if message:
            return
        result = insights.analyze(evaluations, self.settings.skills)
        lists = [(self.missing_rows, [(name, count, 0) for name, count in result.missing], set()),
                 (self.required_rows, result.required, result.in_cv)]
        for rows, items, mine in lists:
            while rows.count():
                rows.takeAt(0).widget().setParent(None)  # remove now, not after deleteLater
            scale = max((count for _, count, _ in items), default=1)
            for name, count, yours in items:
                rows.addWidget(_bar_row(name, count, yours, scale, name in mine))
            if not items:
                empty = _label("muted")
                empty.setText("—")
                rows.addWidget(empty)
        jobs = "job" if result.total == 1 else "jobs"
        items = "item" if result.unknown == 1 else "items"
        self.insights_note.setText(f"Based on {result.total} evaluated {jobs} · {result.unknown} missing {items}"
                                   " not recognised")

    def show_tab(self, index: int) -> None:
        """Switch the view: 0 found jobs, 1 my applications, 2 insights."""
        self.tabs.button(index).setChecked(True)
        for table in (self.table, self.applied_table):
            table.clearSelection()
        self.show_details(None)
        if index == 2:
            self.render_insights()
            self.views.setCurrentIndex(1)
        else:
            self.lists.setCurrentIndex(index)
            self.views.setCurrentIndex(0)

    def on_select(self) -> None:
        indexes = self.table.selectionModel().selectedRows()
        self.show_details(self.visible[indexes[0].row()] if indexes else None)

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
            label.setText(row.get(key) or "")
        has_salary = bool(row.get("salary"))  # only some sites give one
        self.facts["salary"].setVisible(has_salary)
        self.fact_names["salary"].setVisible(has_salary)
        if row["published"]:  # the site's date and its age; a reposted job also shows when it was first seen
            today = date.today()
            published = f"{row['published']} ({freshness.age_text(row['published'], today)})"
            if freshness.is_reposted(row["published"], row.get("first_seen", "")):
                published += f" · first seen {freshness.age_text(row['first_seen'], today)}"
            self.facts["published"].setText(published)
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
                limits = self.settings or Settings()
                stale = days > limits.stale_days
                self.d_stale.setText(f"No reply for over {limits.stale_days} days — time to follow up or close it")
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
        gone = not is_application and bool(row.get("gone_at"))
        self.d_gone.setVisible(gone)
        if gone:
            self.d_gone.setText(f"No longer listed on {row['source']} since {row['gone_at']}: it may be filled, "
                                "or the site just dropped it. Open the job to check.")
        closed = is_application and row["closed"]
        self.d_closed.setVisible(closed)
        if closed:
            self.d_closed.setText(f"No longer listed on {row['source']} — probably filled")
        self.d_description.setText(db.description(row["url"]))
        self.d_description.setVisible(self.description_open)
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

    def toggle_description(self) -> None:
        self.description_open = not self.description_open
        self.d_description.setVisible(self.description_open)
        self.description_button.setText("Collapse" if self.description_open else "Show description")

    def refresh(self) -> None:
        if self.refreshing:  # one pass at a time: the timer may fire while a modal window is open
            return
        self.refreshing = True
        self.refresh_button.setEnabled(False)
        if self.refresh_action is not None:
            self.refresh_action.setEnabled(False)
        self.settings_button.setEnabled(False)  # the pass reads the settings once, at its start
        self.settings_button.setToolTip("Available when the refresh finishes")
        self.load_rows()  # if the CV changed, old scores leave the list
        self.scored_urls = set()
        self.worker.start()

    def on_progress(self, done: int, total: int) -> None:
        self.progress.setMaximum(total)
        self.progress.setValue(done)
        self.progress.show()
        if done == 0:
            self.started = self.clock()
        left = freshness.time_left_text(self.clock() - self.started, done, total) if done else ""
        self.status_label.setText(f"Evaluated {done} of {total}" + (f" · {left}" if left else ""))

    def on_evaluated(self, row: dict) -> None:
        if row["score"] < (self.settings or Settings()).min_score:
            return
        self.rows.append(row)  # render() puts it in place according to the filters and order
        self.new_urls = db.unseen_urls()  # the job may have reached the database after the list was loaded
        self.scored_urls.add(row["url"])
        self.render()

    def notify_score(self) -> int:
        return max(config.NOTIFY_SCORE, (self.settings or Settings()).min_score)

    def on_finished(self) -> None:
        self.refreshing = False
        self.progress.hide()
        self.refresh_button.setEnabled(True)
        if self.refresh_action is not None:
            self.refresh_action.setEnabled(True)
        self.settings_button.setEnabled(True)
        self.settings_button.setToolTip("")
        self.load_rows()  # drop jobs that vanished from the source or were filtered out by location
        if self.views.currentIndex() == 1:
            self.render_insights()  # the numbers changed while the tab was open
        # New = still unseen after the pass: jobs that were in the list when the window was hidden are seen
        good = {row["url"] for row in self.rows if row["url"] in self.scored_urls and row["url"] in self.new_urls
                and row["score"] >= self.notify_score()}
        self.scored_urls = set()
        if good and self.tray is not None and not self.isActiveWindow():  # hidden, minimized or behind
            jobs = "job" if len(good) == 1 else "jobs"
            self.jobs_message = True
            self.tray.showMessage("Job Finder", f"{len(good)} new {jobs} with a score of {self.notify_score()}+",
                                  QSystemTrayIcon.Information, 10000)
        if self.worker.paused:
            self.retry_timer.start()  # a full-screen game started during scoring: the rest comes later
        if self.refresh_again:
            self.refresh_again = False
            self.refresh()

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

    def open_settings(self) -> None:
        """The Settings window; after Save the list follows the new settings and a new search starts if needed."""
        # Imported here, not at the top: settings_window itself takes _label from this module
        from job_finder import settings_window
        old = self.settings
        dialog = settings_window.SettingsDialog(old or Settings(), self)
        accepted = dialog.exec() == QDialog.Accepted
        dialog.deleteLater()  # a child of the main window: otherwise every opened window stays in memory
        if not accepted:
            return
        self.load_rows()
        if self.cv_window is not None and self.cv_window.isVisible():
            self.cv_window.reload()  # the CV file may have changed; a closed window is read when it opens
        if old is None or _search_changed(old, self.settings):
            if self.refreshing:
                self.refresh_again = True  # the running pass read the old settings
            else:
                self.refresh()

    def open_job(self) -> None:
        QDesktopServices.openUrl(QUrl(self.current["url"]))

    def hide_job(self) -> None:
        url = self.current["url"]
        db.hide(url)
        self._show_undo(self.current)
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

    def _build_tray(self) -> QSystemTrayIcon:
        tray = QSystemTrayIcon(QIcon(str(config.ICON_PATH)), self)
        tray.setToolTip("Job Finder")
        menu = QMenu(self)
        menu.addAction("Open Job Finder", self.show_window)
        self.refresh_action = menu.addAction("Refresh now", self.refresh_now)
        menu.addSeparator()
        menu.addAction("Quit", self.quit_app)
        tray.setContextMenu(menu)
        tray.activated.connect(self.on_tray_activated)
        tray.messageClicked.connect(self.on_message_clicked)
        tray.show()
        QApplication.instance().setQuitOnLastWindowClosed(False)  # hidden in the tray, only Quit ends the app
        return tray

    def on_message_clicked(self) -> None:
        if self.jobs_message:  # not the "keeps running in the tray" hint: that window was just closed
            self.show_window()

    def listen_for_launches(self, name: str) -> None:
        """A second launch of the app (the shortcut clicked again) asks this one to show its window."""
        QLocalServer.removeServer(name)  # a name left behind by a run that crashed
        self.launch_server = QLocalServer(self)
        self.launch_server.newConnection.connect(self.on_launch)
        self.launch_server.listen(name)

    def on_launch(self) -> None:
        while self.launch_server.hasPendingConnections():
            connection = self.launch_server.nextPendingConnection()
            connection.disconnectFromServer()
            connection.deleteLater()
        self.show_window()

    def on_tray_activated(self, reason) -> None:
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self.show_window()

    def show_window(self) -> None:
        self.load_rows()  # the "new" marks were cleared when the window was hidden
        self.setWindowState(self.windowState() & ~Qt.WindowMinimized)  # a maximized window comes back maximized
        self.show()
        self.raise_()
        self.activateWindow()

    def refresh_now(self) -> None:
        self.refresh()  # does nothing while a refresh runs

    def auto_refresh(self) -> None:
        """The periodic refresh; while a full-screen game or presentation runs it waits a bit and tries again."""
        if self.refreshing:
            return
        if busy.windows_busy():
            self.retry_timer.start()
            return
        self.refresh()

    def quit_app(self) -> None:
        """Quit from the tray menu: the same questions as closing the window before the tray existed."""
        self.quitting = True
        if self.close():
            if self.tray is not None:
                self.tray.hide()
            self.exit_app()

    def hide_to_tray(self) -> None:
        self.save_notes()
        db.mark_all_seen()  # like closing the window used to: what was in the list is no longer new
        self.hide()
        if not self.tray_hint_shown:
            self.tray_hint_shown = True
            self.jobs_message = False
            self.tray.showMessage("Job Finder", TRAY_HINT, QSystemTrayIcon.Information, 8000)

    def closeEvent(self, event) -> None:
        if self.tray is not None and not self.quitting:
            event.ignore()  # the app keeps running in the tray and looks for new jobs
            self.hide_to_tray()
            return
        if self.refreshing and not self.confirm_close():
            self.quitting = False  # "Cancel": the app stays as it was
            event.ignore()
            return
        self.save_notes()
        db.mark_all_seen()  # on the next start only jobs arriving after this will be new
        if self.worker.model_loaded:
            llm.release(wait=False)  # do not wait: the window must close right away
        event.accept()
