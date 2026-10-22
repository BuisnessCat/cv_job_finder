"""The first-run wizard and the Settings window (spec section 15): the same three pages, as steps or by a side menu."""
from dataclasses import replace
from functools import partial
from pathlib import Path

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QDialog, QFileDialog, QFrame, QGridLayout,
                               QHBoxLayout, QLabel, QLineEdit, QListWidget, QMessageBox, QProgressBar, QPushButton,
                               QScrollArea, QStackedWidget, QToolButton, QVBoxLayout, QWidget)

from job_finder import db, settings, skills, style
from job_finder.flow_layout import FlowLayout
from job_finder.ready_window import ReadyPanel
from job_finder.settings import Settings
from job_finder.window import _label

SECONDS_PER_JOB = 8  # one model answer on a mid-range GPU, for the "about N min" estimate
PAGES = {  # page: title, one-line hint
    "cv": ("Your CV", "The file the AI compares jobs with, and the skills a job must mention to be scored."),
    "search": ("What you're looking for", "Where you want to work and at what level."),
    "languages": ("Languages", "The AI checks the language requirements of each job against these."),
}
WELCOME = ("Job Finder collects fresh jobs from several sites, keeps the ones that mention your skills and has a "
           "local AI model score each of them against your CV.\n\n"
           "Answer a few questions, it takes about a minute. You can change everything later in Settings.")
# Wizard steps after Welcome: the page and the required fields that keep "Next" disabled until filled
STEPS = [("", ()), ("cv", ("cv_path", "skills", "main_skill")), ("search", ("levels",)), ("languages", ("languages",))]
MISSING_TEXT = {"cv_path": "a CV file", "skills": "skills", "main_skill": "the main skill", "levels": "a level",
                "languages": "a language"}


def _text(name: str, text: str) -> QLabel:
    label = _label(name)
    label.setText(text)
    return label


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


def _scroll(widget: QWidget) -> QScrollArea:
    scroll = QScrollArea()
    scroll.setObjectName("detailsScroll")
    scroll.setWidgetResizable(True)
    scroll.setWidget(widget)
    return scroll


def _buttons_without_enter(dialog: QDialog) -> None:
    # Enter in a text field (adding a skill) must not press "Next" or "Save"
    for button in dialog.findChildren(QPushButton):
        button.setAutoDefault(False)


class LanguageRow(QWidget):
    """One language: a name (from the list or typed in), its level and a button that removes the row."""

    def __init__(self, name: str, level: str):
        super().__init__()
        self.name_box = QComboBox()
        self.name_box.setEditable(True)
        self.name_box.addItems(settings.LANGUAGES)
        self.name_box.lineEdit().setPlaceholderText("Language")
        self.name_box.setCurrentIndex(-1)
        self.name_box.setEditText(name)
        self.name_box.setFixedWidth(180)
        self.level_box = QComboBox()
        self.level_box.addItems(settings.LANGUAGE_LEVELS)
        self.level_box.setPlaceholderText("Level")
        self.level_box.setCurrentIndex(settings.LANGUAGE_LEVELS.index(level) if level in settings.LANGUAGE_LEVELS
                                       else -1)
        self.level_box.setFixedWidth(100)
        self.remove_button = QToolButton()
        self.remove_button.setText("×")
        self.remove_button.setObjectName("rowX")
        self.remove_button.setToolTip("Remove this language")
        box = QHBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.addWidget(self.name_box)
        box.addWidget(self.level_box)
        box.addWidget(self.remove_button)
        box.addStretch(1)


class SettingsForm(QObject):
    """The settings fields; the wizard shows its pages as steps, the Settings window by a side menu."""
    changed = Signal()  # a field was edited: the dialogs check again what is still missing

    def __init__(self, parent=None):
        super().__init__(parent)
        self.saved = Settings()  # fields the form doesn't show (the thresholds) are kept from here
        self.cv_path = ""
        self.cv_text = ""  # for guessing the main skill
        self.cv_readable = False
        self.cv_input = QLineEdit(readOnly=True, placeholderText="No file chosen")
        self.cv_button = QPushButton("Choose file…")
        self.cv_button.clicked.connect(self.choose_cv)
        self.cv_error = _label("cvError")  # why the chosen file can't be read
        self.cv_error.hide()
        self.file_box = QWidget()  # the error sits in the same grid cell: a hidden row would still leave a gap
        file_layout = QVBoxLayout(self.file_box)
        file_layout.setContentsMargins(0, 0, 0, 0)
        file_layout.addWidget(_row(self.cv_input, self.cv_button, stretch=0))
        file_layout.addWidget(self.cv_error)

        self._skills: list[str] = []
        self.chips_box = QWidget()
        self.chips = FlowLayout(self.chips_box)
        self.skill_input = QLineEdit(placeholderText="+ Add skill")
        self.skill_input.setObjectName("chipInput")
        self.skill_input.setFixedWidth(120)
        self.skill_input.returnPressed.connect(self.add_skill)
        self.main_skill_box = QComboBox()
        self.main_skill_box.setFixedWidth(240)
        self.main_skill_box.currentTextChanged.connect(self.changed)

        self.city_box = QComboBox()
        self.city_box.addItems(settings.CITIES)
        self.city_box.setFixedWidth(240)
        self.remote_check = QCheckBox("Remote is fine")
        self.level_buttons = QButtonGroup(self)
        self.level_buttons.setExclusive(False)  # several levels at once
        last = len(settings.LEVELS) - 1
        for index, level in enumerate(settings.LEVELS):
            button = QPushButton(level.capitalize())
            button.setCheckable(True)
            button.setObjectName("segmentLeft" if index == 0 else "segmentRight" if index == last else "segmentMiddle")
            self.level_buttons.addButton(button, index)
        self.level_buttons.buttonToggled.connect(self._level_toggled)
        level_row = _row(*self.level_buttons.buttons())
        level_row.layout().setSpacing(0)

        self.language_rows: list[LanguageRow] = []
        self.languages_box = QWidget()
        languages_layout = QVBoxLayout(self.languages_box)
        languages_layout.setContentsMargins(0, 0, 0, 0)
        languages_layout.setSpacing(6)
        self.rows_layout = QVBoxLayout()
        self.rows_layout.setSpacing(6)
        languages_layout.addLayout(self.rows_layout)
        self.add_language_button = QPushButton("+ Add language")
        self.add_language_button.setObjectName("link")
        self.add_language_button.clicked.connect(self.add_empty_language)
        languages_layout.addWidget(self.add_language_button, 0, Qt.AlignLeft)

        self.rows = {  # page: (caption, widget) rows on its grid
            "cv": [("File", self.file_box), ("Skills", self.chips_box), ("Main skill", self.main_skill_box),
                   ("", _text("muted", "Searched for on the remote job sites"))],
            "search": [("City", self.city_box), ("", self.remote_check), ("Level", level_row),
                       ("", _text("muted", "You can pick several"))],
            "languages": [("Spoken", self.languages_box)],
        }

    def page(self, name: str) -> QWidget:
        """A page: title, hint and its fields on a grid, so every field lines up."""
        title, hint = PAGES[name]
        page = QWidget()
        page.setObjectName("details")
        box = QVBoxLayout(page)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(4)
        box.addWidget(_text("h1", title))
        box.addWidget(_text("muted", hint))
        box.addSpacing(16)
        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(10)
        grid.setColumnMinimumWidth(0, 90)
        grid.setColumnStretch(1, 1)
        for row, (caption, widget) in enumerate(self.rows[name]):
            label = _text("metaKey", caption)
            if widget in (self.file_box, self.chips_box, self.languages_box):  # may grow: line up with the top line
                label.setContentsMargins(0, 7, 0, 0)
                grid.addWidget(label, row, 0, Qt.AlignTop)
            else:
                grid.addWidget(label, row, 0, Qt.AlignVCenter)
            grid.addWidget(widget, row, 1)
        box.addLayout(grid)
        box.addStretch(1)
        return page

    def set_values(self, s: Settings) -> None:
        self.saved = s
        self.cv_path = s.cv_path
        self.cv_input.setText(s.cv_path)
        if s.cv_path:
            self._read_cv()  # a moved or deleted file shows its error right away
        self._set_skills(s.skills, s.main_skill)  # the saved skills, not the ones found in the CV again
        self.city_box.setCurrentText(s.city)
        self.remote_check.setChecked(s.remote)
        self.level_buttons.blockSignals(True)
        for index, level in enumerate(settings.LEVELS):
            self.level_buttons.button(index).setChecked(level in s.levels)
        self.level_buttons.blockSignals(False)
        for row in list(self.language_rows):
            self.remove_language(row)
        for name, level in s.languages.items():
            self.add_language(name, level)
        self.changed.emit()

    def values(self) -> Settings:
        languages = {}
        for row in self.language_rows:  # the same language twice: the last row wins
            languages[settings.language_name(row.name_box.currentText())] = row.level_box.currentText()
        return replace(self.saved, cv_path=self.cv_path, skills=self.skill_chips(),
                       main_skill=self.main_skill_box.currentText(),
                       city=self.city_box.currentText(), remote=self.remote_check.isChecked(),
                       levels=[level for index, level in enumerate(settings.LEVELS)
                               if self.level_buttons.button(index).isChecked()],
                       languages=languages)

    def missing(self) -> list[str]:
        """Required fields still empty; a CV file that can't be read counts as not chosen."""
        empty = settings.missing(self.values())
        if self.cv_path and not self.cv_readable:
            empty.insert(0, "cv_path")
        return empty

    # Your CV

    def choose_cv(self) -> None:
        start = str(Path(self.cv_path).parent) if self.cv_path else str(Path.home())
        path, _ = QFileDialog.getOpenFileName(self.cv_button.window(), "Choose your CV", start,
                                              "CV (*.md *.txt *.pdf)")
        if path:
            self.set_cv(path)

    def set_cv(self, path: str) -> None:
        """A newly chosen CV: read it and offer the skills found in it (asks first if there are skills already)."""
        self.cv_path = path
        self.cv_input.setText(path)
        if self._read_cv():
            found = settings.detect_skills(self.cv_text)
            # Edited skills are not thrown away silently, e.g. when a moved CV is picked again
            if found and set(found) != set(self._skills) and (not self._skills or self.confirm_replace_skills()):
                self._set_skills(found, self.main_skill_box.currentText())
        self.changed.emit()

    def _read_cv(self) -> bool:
        try:
            self.cv_text = settings.read_cv_text(self.cv_path)
        except settings.CvError as error:
            self.cv_error.setText(f"Can't read this file: {error}")
            self.cv_error.show()
            self.cv_readable = False
            return False
        self.cv_error.hide()
        self.cv_readable = True
        return True

    def skill_chips(self) -> list[str]:
        return list(self._skills)

    def confirm_replace_skills(self) -> bool:
        answer = QMessageBox.question(self.cv_button.window(), "Skills",
                                      "Replace your skills with the ones found in the new file?",
                                      QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        return answer == QMessageBox.Yes

    def missing_text(self) -> str:
        """What is still needed, in words; for languages, whether a name or a level is missing."""
        parts = []
        for name in self.missing():
            rows = [(row.name_box.currentText().strip(), row.level_box.currentText()) for row in self.language_rows]
            if name != "languages" or not rows:
                parts.append(MISSING_TEXT[name])
                continue
            if any(not language for language, _ in rows):
                parts.append("a language name")
            if any(language and not level for language, level in rows):
                parts.append("language levels")
        return "Still needed: " + ", ".join(parts) if parts else ""

    def add_skill(self) -> None:
        name = settings.skill_name(self.skill_input.text())
        self.skill_input.clear()
        if name and name.lower() not in (skill.lower() for skill in self._skills):
            self._set_skills([*self._skills, name], self.main_skill_box.currentText())
            self.changed.emit()

    def remove_skill(self, name: str, _checked: bool = False) -> None:
        self._set_skills([skill for skill in self._skills if skill != name], self.main_skill_box.currentText())
        self.changed.emit()

    def _set_skills(self, names: list[str], main: str) -> None:
        """Show the skills as chips and offer them as the main skill: keep main if it is still there, else guess."""
        self._skills = list(names)
        while self.chips.count():
            widget = self.chips.takeAt(0).widget()
            if widget is not self.skill_input:
                widget.hide()
                widget.deleteLater()  # not right away: the chip's own button may be the one clicked
        for name in self._skills:
            self.chips.addWidget(self._chip(name))
        self.chips.addWidget(self.skill_input)
        self.main_skill_box.blockSignals(True)
        self.main_skill_box.clear()
        self.main_skill_box.addItems(self._skills)
        self.main_skill_box.setCurrentText(main if main in self._skills
                                           else settings.guess_main_skill(self._skills, self.cv_text))
        self.main_skill_box.blockSignals(False)

    def _chip(self, name: str) -> QFrame:
        chip = QFrame()
        chip.setObjectName("chip")
        box = QHBoxLayout(chip)
        box.setContentsMargins(10, 2, 2, 2)
        box.setSpacing(0)
        box.addWidget(QLabel(name))
        remove = QToolButton()
        remove.setText("×")
        remove.setObjectName("chipX")
        remove.setToolTip(f"Remove {name}")
        remove.clicked.connect(partial(self.remove_skill, name))
        box.addWidget(remove)
        return chip

    # What you're looking for

    def _level_toggled(self, button: QPushButton, checked: bool) -> None:
        if not checked and not any(b.isChecked() for b in self.level_buttons.buttons()):
            button.setChecked(True)  # at least one level stays chosen
            return
        self.changed.emit()

    # Languages

    def add_empty_language(self) -> None:
        self.add_language("", "")

    def add_language(self, name: str, level: str) -> None:
        row = LanguageRow(name, level)
        row.name_box.currentTextChanged.connect(self.changed)
        row.level_box.currentIndexChanged.connect(self.changed)
        row.remove_button.clicked.connect(partial(self.remove_language, row))
        self.language_rows.append(row)
        self.rows_layout.addWidget(row)
        self.changed.emit()

    def remove_language(self, row: LanguageRow, _checked: bool = False) -> None:
        self.language_rows.remove(row)
        row.hide()
        row.deleteLater()  # not right away: its own button may be the one clicked
        self.changed.emit()


class Wizard(QDialog):
    """First run: Welcome, (AI model), Your CV, What you're looking for, Languages; one column with a progress bar.
    model: LM Studio or this model is missing, so a step to get them comes after Welcome."""

    def __init__(self, s: Settings, model: str | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Job Finder — setup")
        self.setStyleSheet(style.STYLESHEET)
        self.resize(660, 600)
        self.step = 0
        self.steps = [STEPS[0], *([("model", ())] if model else []), *STEPS[1:]]
        self.form = SettingsForm(self)
        self.step_label = _label("muted")
        self.bar = QProgressBar()
        self.bar.setRange(0, len(self.steps))
        self.bar.setTextVisible(False)
        welcome = QWidget()
        welcome.setObjectName("details")
        welcome_box = QVBoxLayout(welcome)
        welcome_box.setContentsMargins(0, 0, 0, 0)
        welcome_box.setSpacing(10)
        welcome_box.addWidget(_text("h1", "Welcome to Job Finder"))
        welcome_box.addWidget(_text("muted", WELCOME))
        welcome_box.addStretch(1)
        self.pages = QStackedWidget()
        self.pages.setObjectName("details")
        self.pages.addWidget(welcome)
        if model:
            self.pages.addWidget(ReadyPanel(model, "AI model"))
        for name, _ in STEPS[1:]:
            self.pages.addWidget(self.form.page(name))
        self.has_scores = db.has_evaluations()
        self.rescore_note = _text("muted", "You already have scored jobs: they will all be scored again with "
                                           "these settings.")

        self.back_button = QPushButton("Back")
        self.back_button.clicked.connect(self.go_back)
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
        layout.addWidget(_scroll(self.pages), 1)
        layout.addWidget(self.rescore_note)
        layout.addLayout(buttons)
        _buttons_without_enter(self)

        self.form.changed.connect(self.update_buttons)
        self.form.set_values(s)
        self.show_step(0)

    def show_step(self, step: int) -> None:
        self.step = step
        last = step == len(self.steps) - 1
        self.pages.setCurrentIndex(step)
        self.step_label.setText(f"Step {step + 1} of {len(self.steps)}")
        self.bar.setValue(step + 1)
        self.back_button.setVisible(step > 0)
        self.next_button.setText("Start search" if last else "Next")
        self.rescore_note.setVisible(last and self.has_scores)
        self.update_buttons()

    def update_buttons(self) -> None:
        self.next_button.setEnabled(not set(self.steps[self.step][1]) & set(self.form.missing()))

    def go_back(self) -> None:
        self.show_step(self.step - 1)

    def go_next(self) -> None:
        if self.step == len(self.steps) - 1:
            self.accept()
        else:
            self.show_step(self.step + 1)

    def values(self) -> Settings:
        return self.form.values()


class SettingsDialog(QDialog):
    """Settings: a side menu with the three pages; Save asks first if all jobs have to be scored again."""

    def __init__(self, s: Settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setStyleSheet(style.STYLESHEET)
        self.resize(780, 560)
        self.saved = s
        self.form = SettingsForm(self)
        self.nav = QListWidget()
        self.nav.setObjectName("nav")
        self.nav.setFixedWidth(210)
        self.pages = QStackedWidget()
        self.pages.setObjectName("details")
        for name, (title, _) in PAGES.items():
            self.nav.addItem(title)
            self.pages.addWidget(self.form.page(name))
        self.nav.currentRowChanged.connect(self.pages.setCurrentIndex)
        self.nav.setCurrentRow(0)

        self.missing_label = _label("muted")  # "Still needed: …" while Save is disabled
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.reject)
        self.save_button = QPushButton("Save")
        self.save_button.setObjectName("primary")
        self.save_button.clicked.connect(self.save)
        buttons = QHBoxLayout()
        buttons.addWidget(self.missing_label, 1)
        buttons.addWidget(self.cancel_button)
        buttons.addWidget(self.save_button)

        right = QVBoxLayout()
        right.setContentsMargins(28, 22, 20, 16)
        right.setSpacing(12)
        right.addWidget(_scroll(self.pages), 1)
        right.addLayout(buttons)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.nav)
        layout.addLayout(right, 1)
        _buttons_without_enter(self)

        self.form.changed.connect(self.update_buttons)
        self.form.set_values(s)

    def update_buttons(self) -> None:
        missing = self.form.missing()
        self.save_button.setEnabled(not missing)
        self.missing_label.setText(self.form.missing_text())

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


def first_run(cv: Path, model: str | None = None) -> bool:
    """Show the wizard when settings are missing or incomplete; False if it was closed before the end. model: LM
    Studio or this model is missing, the wizard helps to get them."""
    saved = settings.load()
    if saved is not None and not settings.missing(saved):
        return True
    wizard = Wizard(saved or settings.initial(cv), model)
    if wizard.exec() != QDialog.Accepted:
        return False
    settings.save(wizard.values())
    return True
