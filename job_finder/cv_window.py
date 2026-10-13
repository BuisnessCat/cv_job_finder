"""Окно «Резюме»: актуальный master_cv.md с оформлением, путь к файлу, дата изменения и навыки для отсева."""
from datetime import datetime

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QDialog, QFrame, QGridLayout, QHBoxLayout, QPushButton, QTextBrowser, QVBoxLayout

from job_finder import config, skills, style
from job_finder.window import _label


class CvWindow(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Резюме — master_cv.md")
        self.resize(760, 820)

        info = QFrame()
        info.setObjectName("card")
        grid = QGridLayout(info)
        grid.setContentsMargins(16, 12, 16, 12)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(4)
        grid.setColumnStretch(1, 1)
        self.path_label, self.modified_label, self.skills_label = _label(), _label(), _label()
        for i, (caption, value) in enumerate([("Файл", self.path_label), ("Изменён", self.modified_label),
                                              ("Навыки для отсева", self.skills_label)]):
            name = _label("metaKey")
            name.setText(caption)
            grid.addWidget(name, i, 0, Qt.AlignTop)
            grid.addWidget(value, i, 1)

        self.body = QTextBrowser()
        self.body.setOpenExternalLinks(True)

        self.open_button = QPushButton("Открыть в редакторе")
        self.open_button.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(config.CV_PATH))))
        close_button = QPushButton("Закрыть")
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

    def reload(self) -> None:
        """Перечитать файл: окно всегда показывает текущую версию резюме."""
        self.path_label.setText(str(config.CV_PATH))
        if not config.CV_PATH.exists():
            self.modified_label.setText("—")
            self.skills_label.setText("—")
            self.body.setPlainText("Файл master_cv.md не найден. Положите его в папку проекта и откройте окно снова.")
            self.open_button.setEnabled(False)
            return
        text = config.CV_PATH.read_text(encoding="utf-8", errors="replace")
        modified = datetime.fromtimestamp(config.CV_PATH.stat().st_mtime)
        self.modified_label.setText(modified.strftime("%Y-%m-%d %H:%M"))
        self.skills_label.setText(", ".join(skills.load_skills(text)) or "раздел Skills не найден")
        self.body.setMarkdown(text)
        self.open_button.setEnabled(True)
