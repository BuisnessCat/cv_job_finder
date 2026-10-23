"""The "My CV" window: the CV from the settings (Markdown rendered, other files as text), its path, date and skills."""
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QDialog, QFrame, QGridLayout, QHBoxLayout, QPushButton, QTextBrowser, QVBoxLayout

from job_finder import settings, style
from job_finder.window import _label


class CvWindow(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.path = ""  # the CV file shown, from the settings
        self.resize(760, 820)

        info = QFrame()
        info.setObjectName("card")
        grid = QGridLayout(info)
        grid.setContentsMargins(16, 12, 16, 12)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(4)
        grid.setColumnStretch(1, 1)
        self.path_label, self.modified_label, self.skills_label = _label(), _label(), _label()
        for i, (caption, value) in enumerate([("File", self.path_label), ("Modified", self.modified_label),
                                              ("Skills used for filtering", self.skills_label)]):
            name = _label("metaKey")
            name.setText(caption)
            grid.addWidget(name, i, 0, Qt.AlignTop)
            grid.addWidget(value, i, 1)

        self.body = QTextBrowser()
        self.body.setOpenExternalLinks(True)

        self.open_button = QPushButton("Open in editor")
        self.open_button.clicked.connect(self.open_file)  # a method: a lambda with self would keep the window alive
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.close)
        buttons = QHBoxLayout()
        buttons.addWidget(self.open_button)
        buttons.addStretch(1)
        buttons.addWidget(close_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(style.GAP, style.GAP, style.GAP, style.GAP)
        layout.setSpacing(style.GAP)
        layout.addWidget(info)
        layout.addWidget(self.body, 1)
        layout.addLayout(buttons)
        self.reload()

    def open_file(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(self.path))

    def reload(self) -> None:
        """Re-read the file: the window always shows the current version of the CV."""
        s = settings.load()
        self.path = s.cv_path if s else ""
        self.setWindowTitle(f"My CV — {Path(self.path).name}" if self.path else "My CV")
        self.path_label.setText(self.path or "—")
        self.skills_label.setText(", ".join(s.skills) if s and s.skills else "—")
        try:
            text = settings.read_cv_text(self.path)
        except settings.CvError as error:
            self.modified_label.setText("—")
            self.open_button.setEnabled(False)
            copy = settings.saved_copy()
            if copy.strip():  # the scoring goes on with it
                self.path_label.setText(f"{self.path} (can't be read: {error}; showing the saved copy)")
                self.body.setPlainText(copy)
            else:
                self.body.setPlainText(f"Can't read your CV: {error}. Pick the file in Settings.")
            return
        modified = datetime.fromtimestamp(Path(self.path).stat().st_mtime)
        self.modified_label.setText(modified.strftime("%Y-%m-%d %H:%M"))
        if Path(self.path).suffix.lower() == ".md":
            self.body.setMarkdown(text)
        else:
            self.body.setPlainText(text)
        self.open_button.setEnabled(True)
