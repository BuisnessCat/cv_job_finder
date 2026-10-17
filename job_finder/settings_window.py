"""The first-run wizard and the Settings window (spec section 15): the same fields, as steps or on one page."""
from pathlib import Path

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QCheckBox, QComboBox, QDialog, QFileDialog, QFrame,
                               QGridLayout, QHBoxLayout, QLineEdit, QListWidget, QMessageBox, QProgressBar,
                               QPushButton, QRadioButton, QScrollArea, QSpinBox, QStackedWidget, QVBoxLayout, QWidget)

from job_finder import db, settings, skills, style
from job_finder.settings import Settings
from job_finder.window import _label

SECONDS_PER_JOB = 8  # one model answer on a mid-range GPU, for the "about N min" estimate
SECTIONS = {"cv": "YOUR CV", "search": "WHAT YOU'RE LOOKING FOR", "about": "ABOUT YOU", "advanced": "ADVANCED"}
WELCOME = ("Job Finder collects fresh jobs from several sites, keeps the ones that mention your skills and has a "
           "local AI model score each of them against your CV.\n\n"
           "Answer a few questions, it takes about a minute. You can change everything later in Settings.")
# Wizard steps: title, hint, form sections, required fields that keep "Next" disabled until filled
STEPS = [
    ("Welcome to Job Finder", WELCOME, [], ()),
    ("Your CV", "Pick the file with your CV (.md, .txt or .pdf). The app finds the skills in it: remove what's "
                "wrong and add what's missing. Only jobs that mention at least one of these skills are scored.",
     ["cv"], ("cv_path", "skills")),
    ("What you're looking for", "Where to look and for what kind of role.", ["search"], ("keywords",)),
    ("About you", "The AI takes this into account when it scores a job.", ["about"],
     ("english", "czech", "needs_permit")),
]


def _row(*widgets, stretch: int | None = None) -> QWidget:
    """Widgets side by side; stretch: the index of the one that takes the free space (none: space at the end)."""
    row = QWidget()
    box = QHBoxLayout(row)
    box.setContentsMargins(0, 0, 0, 0)
    for index, widget in enumerate(widgets):
        box.addWidget(widget, 1 if index == stretch else 0)
    if stretch is None:
        box.addStretch(1)
    return row


def _text(name: str, text: str):
    label = _label(name)
    label.setText(text)
    return label


def _buttons_without_enter(dialog: QDialog) -> None:
    # Enter in a text field (adding a skill) must not press "Next" or "Save"
    for button in dialog.findChildren(QPushButton):
        button.setAutoDefault(False)


class SettingsForm(QObject):
    """The settings fields; the wizard and the Settings window lay them out in grids by section."""
    changed = Signal()  # a field was edited: the dialogs check again what is still missing

    def __init__(self, parent=None):
        super().__init__(parent)
        self.cv_path = ""
        self.cv_readable = False
        self.cv_input = QLineEdit(readOnly=True, placeholderText="No file chosen")
        self.cv_button = QPushButton("Choose file…")
        self.cv_button.clicked.connect(self.choose_cv)
        self.cv_error = _label("cvError")  # why the chosen file can't be read
        self.cv_error.hide()
        self.skills_list = QListWidget()
        self.skills_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.skills_list.setFixedHeight(150)
        self.skill_input = QLineEdit(placeholderText="Add a skill")
        self.skill_input.returnPressed.connect(self.add_skill)
        self.add_skill_button = QPushButton("Add")
        self.add_skill_button.clicked.connect(self.add_skill)
        self.remove_skill_button = QPushButton("Remove selected")
        self.remove_skill_button.clicked.connect(self.remove_skills)
        self.skills_box = QWidget()
        skills_layout = QVBoxLayout(self.skills_box)
        skills_layout.setContentsMargins(0, 0, 0, 0)
        skills_layout.addWidget(self.skills_list)
        skills_layout.addWidget(_row(self.skill_input, self.add_skill_button, self.remove_skill_button, stretch=0))

        self.city_box = QComboBox()
        self.city_box.addItems(settings.CITIES)
        self.remote_check = QCheckBox("Remote is fine")
        self.keywords_input = QLineEdit(placeholderText="python, fastapi")
        self.keywords_input.textChanged.connect(self.changed)
        self.level_buttons = QButtonGroup(self)
        level_widgets = []
        for index, (level, text) in enumerate(zip(settings.LEVELS, ["Junior", "Mid"])):
            button = QPushButton(text)
            button.setCheckable(True)
            button.setObjectName("segmentLeft" if index == 0 else "segmentRight")
            self.level_buttons.addButton(button, index)
            level_widgets.append(button)
        level_row = _row(*level_widgets)
        level_row.layout().setSpacing(0)

        self.english_box, self.czech_box = self._language_box(), self._language_box()
        self.permit_yes = QRadioButton("I need one for Czechia")
        self.permit_no = QRadioButton("Not needed")
        self.permit_buttons = QButtonGroup(self)
        for button in (self.permit_yes, self.permit_no):
            self.permit_buttons.addButton(button)
        self.permit_buttons.buttonToggled.connect(self.changed)

        self.min_score_box = self._number(1, 10, "")
        self.stale_days_box = self._number(1, 365, " days")
        self.stale_job_days_box = self._number(1, 365, " days")

        self.rows = {  # section: (caption, widget) rows
            "cv": [("File", _row(self.cv_input, self.cv_button, stretch=0)), ("", self.cv_error),
                   ("Skills", self.skills_box)],
            "search": [("City", self.city_box), ("", self.remote_check), ("Keywords", self.keywords_input),
                       ("", _text("muted", "1–3, separated by commas: used to search the remote job sites")),
                       ("Your level", level_row)],
            "about": [("English", self.english_box), ("Czech", self.czech_box),
                      ("Work permit", _row(self.permit_yes, self.permit_no))],
            "advanced": [("Minimum score", self.min_score_box), ("Follow-up reminder after", self.stale_days_box),
                         ("Grey out jobs older than", self.stale_job_days_box)],
        }

    def _language_box(self) -> QComboBox:
        box = QComboBox()
        box.addItems(settings.LANGUAGE_LEVELS)
        box.setPlaceholderText("Choose…")
        box.setCurrentIndex(-1)
        box.currentIndexChanged.connect(self.changed)
        return box

    @staticmethod
    def _number(low: int, high: int, suffix: str) -> QSpinBox:
        box = QSpinBox()
        box.setRange(low, high)
        box.setSuffix(suffix)
        return box

    def grid(self, sections: list[str], titles: bool) -> QWidget:
        """The fields of these sections on one grid, so every field lines up; titles: section headings."""
        page = QWidget()
        page.setObjectName("details")
        grid = QGridLayout(page)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(10)
        grid.setColumnStretch(1, 1)
        row = 0
        for name in sections:
            if titles:
                if row:
                    grid.setRowMinimumHeight(row, 8)
                    row += 1
                grid.addWidget(_text("section", SECTIONS[name]), row, 0, 1, 2)
                row += 1
            for caption, widget in self.rows[name]:
                align = Qt.AlignTop if widget is self.skills_box else Qt.AlignVCenter
                grid.addWidget(_text("metaKey", caption), row, 0, align)
                grid.addWidget(widget, row, 1)
                row += 1
        grid.setRowStretch(row, 1)
        return page

    def set_values(self, s: Settings) -> None:
        self.cv_path = s.cv_path
        self.cv_input.setText(s.cv_path)
        if s.cv_path:
            self._read_cv()  # a moved or deleted file shows its error right away
        self._set_skills(s.skills)
        self.city_box.setCurrentText(s.city)
        self.remote_check.setChecked(s.remote)
        self.keywords_input.setText(", ".join(s.keywords))
        self.level_buttons.button(settings.LEVELS.index(s.level)).setChecked(True)
        for box, level in ((self.english_box, s.english), (self.czech_box, s.czech)):
            box.setCurrentIndex(settings.LANGUAGE_LEVELS.index(level) if level in settings.LANGUAGE_LEVELS else -1)
        self.permit_buttons.setExclusive(False)  # an exclusive group can't uncheck both
        self.permit_yes.setChecked(s.needs_permit is True)
        self.permit_no.setChecked(s.needs_permit is False)
        self.permit_buttons.setExclusive(True)
        self.min_score_box.setValue(s.min_score)
        self.stale_days_box.setValue(s.stale_days)
        self.stale_job_days_box.setValue(s.stale_job_days)
        self.changed.emit()

    def values(self) -> Settings:
        permit = True if self.permit_yes.isChecked() else False if self.permit_no.isChecked() else None
        return Settings(cv_path=self.cv_path, skills=self.skills(), city=self.city_box.currentText(),
                        remote=self.remote_check.isChecked(),
                        keywords=[word.strip() for word in self.keywords_input.text().split(",") if word.strip()],
                        level=settings.LEVELS[self.level_buttons.checkedId()],
                        english=self.english_box.currentText(), czech=self.czech_box.currentText(),
                        needs_permit=permit, min_score=self.min_score_box.value(),
                        stale_days=self.stale_days_box.value(), stale_job_days=self.stale_job_days_box.value())

    def missing(self) -> list[str]:
        """Required fields still empty; a CV file that can't be read counts as not chosen."""
        empty = settings.missing(self.values())
        if self.cv_path and not self.cv_readable:
            empty.insert(0, "cv_path")
        return empty

    def skills(self) -> list[str]:
        return [self.skills_list.item(i).text() for i in range(self.skills_list.count())]

    def _set_skills(self, names: list[str]) -> None:
        self.skills_list.clear()
        self.skills_list.addItems(names)

    def choose_cv(self) -> None:
        start = str(Path(self.cv_path).parent) if self.cv_path else str(Path.home())
        path, _ = QFileDialog.getOpenFileName(self.cv_button.window(), "Choose your CV", start,
                                              "CV (*.md *.txt *.pdf)")
        if path:
            self.set_cv(path)

    def set_cv(self, path: str) -> None:
        """A newly chosen CV: read it and replace the skills with the ones found in it."""
        self.cv_path = path
        self.cv_input.setText(path)
        text = self._read_cv()
        if text is not None:
            self._set_skills(settings.detect_skills(text))
        self.changed.emit()

    def _read_cv(self) -> str | None:
        try:
            text = settings.read_cv_text(self.cv_path)
        except settings.CvError as error:
            self.cv_error.setText(f"Can't read this file: {error}")
            self.cv_error.show()
            self.cv_readable = False
            return None
        self.cv_error.hide()
        self.cv_readable = True
        return text

    def add_skill(self) -> None:
        name = self.skill_input.text().strip()
        if name and name.lower() not in (skill.lower() for skill in self.skills()):
            self.skills_list.addItem(name)
            self.changed.emit()
        self.skill_input.clear()

    def remove_skills(self) -> None:
        for item in self.skills_list.selectedItems():
            self.skills_list.takeItem(self.skills_list.row(item))
        self.changed.emit()


class Wizard(QDialog):
    """First run: Welcome, Your CV, What you're looking for, About you; one column with a progress bar."""

    def __init__(self, s: Settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Job Finder — setup")
        self.setStyleSheet(style.STYLESHEET)
        self.resize(640, 600)
        self.step = 0
        self.form = SettingsForm(self)
        self.step_label = _label("muted")
        self.bar = QProgressBar()
        self.bar.setRange(0, len(STEPS))
        self.bar.setTextVisible(False)
        self.pages = QStackedWidget()
        for title, hint, sections, _ in STEPS:
            page = QWidget()
            page.setObjectName("details")
            box = QVBoxLayout(page)
            box.setContentsMargins(0, 0, 0, 0)
            box.setSpacing(10)
            box.addWidget(_text("h1", title))
            box.addWidget(_text("muted", hint))
            box.addSpacing(6)
            if sections:
                box.addWidget(self.form.grid(sections, titles=False))
            box.addStretch(1)
            self.pages.addWidget(page)

        self.back_button = QPushButton("Back")
        self.back_button.clicked.connect(lambda: self.show_step(self.step - 1))
        self.next_button = QPushButton("Next")
        self.next_button.setObjectName("primary")
        self.next_button.clicked.connect(self.go_next)
        buttons = QHBoxLayout()
        buttons.addWidget(self.back_button)
        buttons.addStretch(1)
        buttons.addWidget(self.next_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 20, 28, 20)
        layout.setSpacing(12)
        layout.addWidget(self.step_label)
        layout.addWidget(self.bar)
        layout.addSpacing(6)
        layout.addWidget(self.pages, 1)
        layout.addLayout(buttons)
        _buttons_without_enter(self)

        self.form.changed.connect(self.update_buttons)
        self.form.set_values(s)
        self.show_step(0)

    def show_step(self, step: int) -> None:
        self.step = step
        self.pages.setCurrentIndex(step)
        self.step_label.setText(f"Step {step + 1} of {len(STEPS)}")
        self.bar.setValue(step + 1)
        self.back_button.setVisible(step > 0)
        self.next_button.setText("Start search" if step == len(STEPS) - 1 else "Next")
        self.update_buttons()

    def update_buttons(self) -> None:
        self.next_button.setEnabled(not set(STEPS[self.step][3]) & set(self.form.missing()))

    def go_next(self) -> None:
        if self.step == len(STEPS) - 1:
            self.accept()
        else:
            self.show_step(self.step + 1)

    def values(self) -> Settings:
        return self.form.values()


class SettingsDialog(QDialog):
    """Settings: every field on one scrollable page; Save asks first if all jobs have to be scored again."""

    def __init__(self, s: Settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setStyleSheet(style.STYLESHEET)
        self.resize(640, 700)
        self.saved = s
        self.form = SettingsForm(self)
        page = self.form.grid(list(SECTIONS), titles=True)
        page.layout().setContentsMargins(20, 16, 20, 16)
        scroll = QScrollArea()
        scroll.setObjectName("detailsScroll")
        scroll.setWidgetResizable(True)
        scroll.setWidget(page)
        card = QFrame()
        card.setObjectName("card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(1, 1, 1, 1)
        card_layout.addWidget(scroll)

        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.reject)
        self.save_button = QPushButton("Save")
        self.save_button.setObjectName("primary")
        self.save_button.clicked.connect(self.save)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self.cancel_button)
        buttons.addWidget(self.save_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(style.GAP, style.GAP, style.GAP, style.GAP)
        layout.setSpacing(style.GAP)
        layout.addWidget(card, 1)
        layout.addLayout(buttons)
        _buttons_without_enter(self)

        self.form.changed.connect(self.update_buttons)
        self.form.set_values(s)

    def update_buttons(self) -> None:
        self.save_button.setEnabled(not self.form.missing())

    def save(self) -> None:
        new = self.form.values()
        if settings.scoring_changed(self.saved, new):
            jobs = sum(1 for job in db.pending_jobs("") if skills.matches(job, new.skills))  # "": no key matches
            if not self.confirm_rescore(jobs):
                return
        settings.save(new)
        self.accept()

    def confirm_rescore(self, jobs: int) -> bool:
        minutes = max(1, round(jobs * SECONDS_PER_JOB / 60))
        answer = QMessageBox.question(self, "Score again?",
                                      f"All jobs will be scored again (about {minutes} min). Save?",
                                      QMessageBox.Save | QMessageBox.Cancel, QMessageBox.Cancel)
        return answer == QMessageBox.Save


def first_run(cv: Path) -> bool:
    """Show the wizard when there are no settings yet; False if it was closed before the end (nothing is saved)."""
    if settings.load() is not None:
        return True
    wizard = Wizard(settings.initial(cv))
    if wizard.exec() != QDialog.Accepted:
        return False
    settings.save(wizard.values())
    return True
