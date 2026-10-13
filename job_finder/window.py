"""Главное окно: таблица подходящих вакансий и детали оценки."""
from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView, QHBoxLayout, QHeaderView, QLabel, QMainWindow, QProgressBar,
    QPushButton, QScrollArea, QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from job_finder import config, db, llm, style
from job_finder.worker import Worker, read_cv

COLUMNS = ["Оценка", "Вакансия", "Компания", "Город", "Дата"]
SECTIONS = [("summary", "ПОЧЕМУ"), ("have", "ЕСТЬ"), ("missing", "НЕ ХВАТАЕТ"), ("risks", "МОЖЕТ ОТСЕЧЬ")]


def _label(name: str = "") -> QLabel:
    """Подпись с обычным текстом; name — имя для стилей из style.py."""
    label = QLabel()
    label.setObjectName(name)
    label.setTextFormat(Qt.PlainText)  # только обычный текст, без HTML
    label.setWordWrap(True)
    label.setTextInteractionFlags(Qt.TextSelectableByMouse)
    return label


def _bullets(items: list[str]) -> str:
    return "\n".join(f"• {item}" for item in items) if items else "—"


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Подбор вакансий")
        self.resize(1200, 750)
        self.rows: list[dict] = []        # строки таблицы в порядке показа
        self.current: dict | None = None  # выбранная строка

        self.refresh_button = QPushButton("Обновить")
        self.refresh_button.setObjectName("primary")
        self.refresh_button.clicked.connect(self.refresh)
        self.status_label = _label()
        self.progress = QProgressBar()
        self.progress.setMaximumWidth(250)
        self.progress.hide()
        top = QHBoxLayout()
        top.addWidget(self.refresh_button)
        top.addWidget(self.status_label, 1)
        top.addWidget(self.progress)

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(34)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.itemSelectionChanged.connect(self.on_select)

        splitter = QSplitter()
        splitter.addWidget(self.table)
        splitter.addWidget(self._build_details())
        splitter.setSizes([700, 500])

        central = QWidget()
        central.setObjectName("central")
        layout = QVBoxLayout(central)
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
        QTimer.singleShot(0, self.refresh)  # обновление сразу после показа окна

    def _build_details(self) -> QWidget:
        self.d_title = _label("title")
        self.d_meta = _label("meta")
        self.d_score = _label()  # цветная плашка, цвет задаётся в show_details
        self.d_score.setWordWrap(False)
        self.d_texts = {}
        box = QVBoxLayout()
        box.addWidget(self.d_title)
        box.addWidget(self.d_meta)
        box.addWidget(self.d_score, 0, Qt.AlignLeft)
        for key, caption in SECTIONS:
            header = _label("section")
            header.setText(caption)
            self.d_texts[key] = _label()
            box.addWidget(header)
            box.addWidget(self.d_texts[key])
        box.addStretch(1)
        self.details = QWidget()
        self.details.setObjectName("details")
        self.details.setLayout(box)
        scroll = QScrollArea()
        scroll.setObjectName("detailsScroll")
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.details)

        self.open_button = QPushButton("Открыть вакансию")
        self.open_button.clicked.connect(self.open_job)
        self.hide_button = QPushButton("Скрыть")
        self.hide_button.clicked.connect(self.hide_job)
        buttons = QHBoxLayout()
        buttons.addWidget(self.open_button)
        buttons.addWidget(self.hide_button)
        buttons.addStretch(1)

        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.addWidget(scroll, 1)
        layout.addLayout(buttons)
        self.show_details(None)
        return panel

    def load_rows(self) -> None:
        """Перечитать из базы оценки по текущему резюме."""
        cv = read_cv()
        self.rows = db.list_jobs(cv[1], config.MIN_SCORE) if cv else []
        self.render()

    def render(self) -> None:
        """Перерисовать таблицу, сохранив выделение."""
        selected = self.current["url"] if self.current else None
        self.table.blockSignals(True)
        self.table.clearSelection()
        self.table.setRowCount(len(self.rows))
        for i, row in enumerate(self.rows):
            values = [str(row["score"]), row["title"], row["company"], row["city"], row["published"]]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 0:
                    item.setTextAlignment(Qt.AlignCenter)
                    item.setForeground(QColor(style.score_colors(row["score"])[1]))
                    font = item.font()
                    font.setBold(True)
                    item.setFont(font)
                self.table.setItem(i, column, item)
            if row["url"] == selected:
                self.table.selectRow(i)
        self.table.blockSignals(False)
        if selected and selected not in (row["url"] for row in self.rows):
            self.show_details(None)

    def on_select(self) -> None:
        indexes = self.table.selectionModel().selectedRows()
        self.show_details(self.rows[indexes[0].row()] if indexes else None)

    def show_details(self, row: dict | None) -> None:
        self.current = row
        self.details.setVisible(row is not None)
        self.open_button.setEnabled(row is not None)
        self.hide_button.setEnabled(row is not None)
        if row is None:
            return
        evaluation = row["evaluation"]
        self.d_title.setText(row["title"])
        self.d_meta.setText(f"{row['company']} · {row['city']} · {row['published']}\nИсточник: {row['source']}")
        self.d_score.setText(f"Оценка: {row['score']} из 10")
        background, color = style.score_colors(row["score"])
        self.d_score.setStyleSheet(f"background: {background}; color: {color}; border-radius: 6px;"
                                   " padding: 4px 10px; font-size: 11pt; font-weight: 600;")
        self.d_texts["summary"].setText(evaluation.get("summary") or "—")
        for key in ("have", "missing", "risks"):
            self.d_texts[key].setText(_bullets(evaluation.get(key) or []))

    def refresh(self) -> None:
        self.refresh_button.setEnabled(False)
        self.load_rows()  # если резюме изменилось, старые оценки уходят из списка
        self.worker.start()

    def on_progress(self, done: int, total: int) -> None:
        self.progress.setMaximum(total)
        self.progress.setValue(done)
        self.progress.show()
        self.status_label.setText(f"Оценено {done} из {total}")

    def on_evaluated(self, row: dict) -> None:
        if row["score"] < config.MIN_SCORE:
            return
        self.rows.append(row)
        self.rows.sort(key=lambda r: (r["score"], r["published"]), reverse=True)
        self.render()

    def on_finished(self) -> None:
        self.progress.hide()
        self.refresh_button.setEnabled(True)

    def open_job(self) -> None:
        QDesktopServices.openUrl(QUrl(self.current["url"]))

    def hide_job(self) -> None:
        url = self.current["url"]
        db.hide(url)
        self.rows = [row for row in self.rows if row["url"] != url]
        self.show_details(None)
        self.render()

    def closeEvent(self, event) -> None:
        if self.worker.model_loaded:
            llm.release(wait=False)  # не ждём: окно должно закрыться сразу
        event.accept()
