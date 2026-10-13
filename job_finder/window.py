"""Главное окно: таблица подходящих вакансий и карточка с разбором выбранной."""
from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView, QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel, QMainWindow, QProgressBar,
    QPushButton, QScrollArea, QSplitter, QStackedWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from job_finder import config, db, llm, style
from job_finder.worker import Worker, read_cv

COLUMNS = ["Оценка", "Вакансия", "Компания", "Город", "Дата"]
LISTS = [("have", "ЕСТЬ", "✓"), ("missing", "НЕ ХВАТАЕТ", "✕"), ("risks", "МОЖЕТ ОТСЕЧЬ", "!")]
EMPTY_LIST = {"have": "—", "missing": "Ничего существенного"}


def _label(name: str = "") -> QLabel:
    """Подпись с обычным текстом; name — имя для стилей из style.py."""
    label = QLabel()
    label.setObjectName(name)
    label.setTextFormat(Qt.PlainText)  # только обычный текст, без HTML
    label.setWordWrap(True)
    label.setTextInteractionFlags(Qt.TextSelectableByMouse)
    return label


def _caption(text: str) -> QLabel:
    label = _label("section")
    label.setText(text)
    return label


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
        self.cv_button = QPushButton("Резюме")
        self.cv_button.clicked.connect(self.show_cv)
        top.addWidget(self.cv_button)
        self.cv_window = None  # окно «Резюме» создаётся при первом нажатии

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
        # Заголовки — по тому же краю, что и текст в ячейках
        header.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.table.horizontalHeaderItem(0).setTextAlignment(Qt.AlignCenter)
        self.table.itemSelectionChanged.connect(self.on_select)

        splitter = QSplitter()
        splitter.setHandleWidth(style.GAP)
        splitter.addWidget(self.table)
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
        QTimer.singleShot(0, self.refresh)  # обновление сразу после показа окна

    def _build_details(self) -> QWidget:
        """Карточка деталей: шапка с оценкой, факты, «почему», списки; кнопки — в нижней полосе карточки."""
        self.d_title = _label("title")
        self.d_company = _label("company")
        self.badge = QFrame()
        self.badge.setObjectName("badge")
        self.badge.setFixedSize(64, 64)
        self.badge_number = QLabel(alignment=Qt.AlignCenter)
        self.badge_caption = QLabel("из 10", alignment=Qt.AlignCenter)
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

        facts = QGridLayout()
        facts.setHorizontalSpacing(16)
        facts.setVerticalSpacing(6)
        facts.setColumnStretch(1, 1)
        self.facts = {}
        for i, (key, caption) in enumerate([("city", "Город"), ("published", "Опубликовано"),
                                            ("source", "Источник")]):
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
        box.addSpacing(14)
        box.addLayout(facts)
        box.addSpacing(16)
        box.addWidget(divider)
        box.addSpacing(16)
        box.addWidget(_caption("ПОЧЕМУ ТАКАЯ ОЦЕНКА"))
        box.addSpacing(8)
        box.addWidget(self.d_summary)
        self.lists: dict[str, tuple[QLabel, str, QVBoxLayout]] = {}
        for key, caption, _ in LISTS:
            header = _caption(caption)
            rows = QVBoxLayout()
            rows.setSpacing(6)
            box.addSpacing(18)
            box.addWidget(header)
            box.addSpacing(8)
            box.addLayout(rows)
            self.lists[key] = (header, caption, rows)
        box.addStretch(1)

        details = QWidget()
        details.setObjectName("details")
        details.setLayout(box)
        scroll = QScrollArea()
        scroll.setObjectName("detailsScroll")
        scroll.setWidgetResizable(True)
        scroll.setWidget(details)

        self.open_button = QPushButton("Открыть вакансию")
        self.open_button.setObjectName("primary")
        self.open_button.clicked.connect(self.open_job)
        self.hide_button = QPushButton("Скрыть")
        self.hide_button.clicked.connect(self.hide_job)
        footer = QWidget()
        footer.setObjectName("footer")
        buttons = QHBoxLayout(footer)
        buttons.setContentsMargins(20, 12, 20, 12)
        buttons.addWidget(self.open_button)
        buttons.addWidget(self.hide_button)
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
        empty = QLabel("Выберите вакансию в списке слева", alignment=Qt.AlignCenter)
        empty.setObjectName("empty")
        QVBoxLayout(empty_page).addWidget(empty)

        self.pages = QStackedWidget()  # 0 — ничего не выбрано, 1 — разбор вакансии
        self.pages.addWidget(empty_page)
        self.pages.addWidget(details_page)
        card = QFrame()
        card.setObjectName("card")
        card_box = QVBoxLayout(card)
        card_box.setContentsMargins(1, 1, 1, 1)  # не закрывать рамку карточки
        card_box.addWidget(self.pages)
        self.show_details(None)
        return card

    def _fill_list(self, key: str, mark: str, items: list[str]) -> None:
        """Заполнить список «есть / не хватает / может отсечь» строками с цветным значком."""
        header, caption, rows = self.lists[key]
        header.setText(f"{caption} · {len(items)}" if items else caption)
        while rows.count():
            line = rows.takeAt(0).layout()
            while line.count():
                line.takeAt(0).widget().setParent(None)  # убрать из окна сразу, а не после deleteLater
        color = style.LIST_COLORS[key]
        if not items and key == "risks":
            items, mark, color = ["Блокеров не найдено"], "✓", style.LIST_COLORS["have"]
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
        self.pages.setCurrentIndex(0 if row is None else 1)
        if row is None:
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
        self.load_rows()  # убрать вакансии, которые пропали из источника или отсеяны по месту

    def show_cv(self) -> None:
        """Показать окно «Резюме» с актуальной версией файла; окно одно на всё приложение."""
        # Импорт здесь, а не наверху: cv_window сам берёт _label из этого модуля
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

    def closeEvent(self, event) -> None:
        if self.worker.model_loaded:
            llm.release(wait=False)  # не ждём: окно должно закрыться сразу
        event.accept()
