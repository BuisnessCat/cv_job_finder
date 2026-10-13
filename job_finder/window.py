"""Главное окно: найденные вакансии и отклики, карточка с разбором выбранной."""
from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView, QButtonGroup, QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel, QMainWindow,
    QProgressBar, QPushButton, QScrollArea, QSplitter, QStackedWidget, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from job_finder import config, db, llm, sources, style
from job_finder.worker import Worker, read_cv

COLUMNS = ["Оценка", "Вакансия", "Компания", "Город", "Дата"]
APPLIED_COLUMNS = ["Отклик", "Вакансия", "Компания", "Статус", "Оценка"]
LISTS = [("have", "ЕСТЬ", "✓"), ("missing", "НЕ ХВАТАЕТ", "✕"), ("risks", "МОЖЕТ ОТСЕЧЬ", "!")]
EMPTY_LIST = {"have": "—", "missing": "Ничего существенного"}
STATUS_TEXT = {"applied": "Ждём ответа", "accepted": "Приняли", "rejected": "Отказали"}
REPOST_MARK = "↻ "  # перед названием найденной вакансии, на которую уже был отклик


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


def _make_table(columns: list[str], center: int) -> QTableWidget:
    """Таблица в общем стиле: выбор строки целиком, без сетки; колонка center (оценка) — по центру."""
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
    # Заголовки — по тому же краю, что и текст в ячейках
    header.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    table.horizontalHeaderItem(center).setTextAlignment(Qt.AlignCenter)
    return table


def _score_item(score: int) -> QTableWidgetItem:
    """Ячейка оценки: по центру, жирная, цветом по оценке."""
    item = QTableWidgetItem(str(score))
    item.setTextAlignment(Qt.AlignCenter)
    item.setForeground(QColor(style.score_colors(score)[1]))
    font = item.font()
    font.setBold(True)
    item.setFont(font)
    return item


def _fill_table(table: QTableWidget, rows: list[dict], values, selected_url: str | None) -> None:
    """Заполнить таблицу: values(row) — ячейки строки (текст или готовые QTableWidgetItem); выделение по url."""
    table.blockSignals(True)
    table.clearSelection()
    table.setRowCount(len(rows))
    for i, row in enumerate(rows):
        for column, value in enumerate(values(row)):
            table.setItem(i, column, value if isinstance(value, QTableWidgetItem) else QTableWidgetItem(value))
        if row["url"] == selected_url:
            table.selectRow(i)
    table.blockSignals(False)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Подбор вакансий")
        self.resize(1200, 750)
        self.rows: list[dict] = []        # найденные вакансии в порядке показа
        self.applied: list[dict] = []     # отклики, новые сверху
        self.applied_by_key: dict[tuple[str, str], dict] = {}  # последний отклик по «компания + название»
        self.current: dict | None = None  # выбранная строка: найденная вакансия или отклик (есть ключ status)

        self.refresh_button = QPushButton("Обновить")
        self.refresh_button.setObjectName("primary")
        self.refresh_button.clicked.connect(self.refresh)
        self.found_tab = QPushButton()
        self.found_tab.setObjectName("segmentLeft")
        self.applied_tab = QPushButton()
        self.applied_tab.setObjectName("segmentRight")
        self.tabs = QButtonGroup(self)  # переключатель «Найденные | Мои отклики»: нажата ровно одна кнопка
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
        self.cv_button = QPushButton("Резюме")
        self.cv_button.clicked.connect(self.show_cv)
        self.cv_window = None  # окно «Резюме» создаётся при первом нажатии
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
        self.applied_table = _make_table(APPLIED_COLUMNS, 4)
        self.applied_table.itemSelectionChanged.connect(self.on_select_applied)
        self.lists = QStackedWidget()  # 0 — найденные, 1 — отклики
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
        QTimer.singleShot(0, self.refresh)  # обновление сразу после показа окна

    def _build_details(self) -> QWidget:
        """Карточка деталей: шапка с оценкой, плашки отклика, факты, «почему», списки; кнопки — внизу."""
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

        self.d_status = _label()  # плашка «Отклик ГГГГ-ММ-ДД · статус» — только у откликов
        self.d_status.setWordWrap(False)
        self.d_notice = _label("notice")  # «Вы уже подавались…» — только у перепубликованных вакансий

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
        box.addWidget(self.d_status, 0, Qt.AlignLeft)  # отступ сверху — в стиле плашки, у скрытой его нет
        box.addWidget(self.d_notice)
        box.addSpacing(14)
        box.addLayout(facts)
        box.addSpacing(16)
        box.addWidget(divider)
        box.addSpacing(16)
        box.addWidget(_caption("ПОЧЕМУ ТАКАЯ ОЦЕНКА"))
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

        self.open_button = QPushButton("Открыть вакансию")
        self.open_button.setObjectName("primary")
        self.open_button.clicked.connect(self.open_job)
        self.apply_button = QPushButton("Подался")
        self.apply_button.clicked.connect(self.apply_job)
        self.hide_button = QPushButton("Скрыть")
        self.hide_button.clicked.connect(self.hide_job)
        self.accept_button = QPushButton("Приняли")
        self.accept_button.clicked.connect(lambda: self.set_status("accepted"))
        self.reject_button = QPushButton("Отказали")
        self.reject_button.clicked.connect(lambda: self.set_status("rejected"))
        self.unapply_button = QPushButton("Вернуть в найденные")
        self.unapply_button.clicked.connect(self.unapply_job)
        self.found_buttons = (self.apply_button, self.hide_button)
        self.applied_buttons = (self.accept_button, self.reject_button, self.unapply_button)
        for button in self.applied_buttons:
            button.hide()  # иначе ширина карточки при первой раскладке считается по всем шести кнопкам
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
        header, caption, rows = self.detail_lists[key]
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

    def _previous_application(self, row: dict) -> dict | None:
        """Отклик на вакансию с той же компанией и названием (перепубликованная вакансия) или None."""
        return self.applied_by_key.get(sources.same_job_key(row["company"], row["title"]))

    def load_rows(self) -> None:
        """Перечитать из базы найденные (оценки по текущему резюме) и отклики."""
        cv = read_cv()
        self.rows = db.list_jobs(cv[1], config.MIN_SCORE) if cv else []
        self.applied = db.list_applied()
        # reversed: при нескольких откликах с одним ключом остаётся самый новый
        self.applied_by_key = {sources.same_job_key(r["company"], r["title"]): r for r in reversed(self.applied)}
        self.render()
        self.render_applied()

    def render(self) -> None:
        """Перерисовать найденные, сохранив выделение; отклик в карточке не трогать."""
        selected = self.current["url"] if self.current and "status" not in self.current else None

        def values(row):
            mark = REPOST_MARK if self._previous_application(row) else ""
            return [_score_item(row["score"]), mark + row["title"], row["company"], row["city"], row["published"]]

        _fill_table(self.table, self.rows, values, selected)
        self.found_tab.setText(f"Найденные · {len(self.rows)}")
        if selected and selected not in (row["url"] for row in self.rows):
            self.show_details(None)

    def render_applied(self) -> None:
        """Перерисовать отклики, сохранив выделение; найденную вакансию в карточке не трогать."""
        selected = self.current["url"] if self.current and "status" in self.current else None

        def values(row):
            status = QTableWidgetItem(STATUS_TEXT[row["status"]])
            status.setForeground(QColor(style.STATUS_COLORS[row["status"]][1]))
            return [row["applied_at"], row["title"], row["company"], status, _score_item(row["score"])]

        _fill_table(self.applied_table, self.applied, values, selected)
        self.applied_tab.setText(f"Мои отклики · {len(self.applied)}")
        if selected and selected not in (row["url"] for row in self.applied):
            self.show_details(None)

    def show_tab(self, index: int) -> None:
        """Переключить список слева: 0 — найденные, 1 — мои отклики."""
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

        is_application = "status" in row
        self.d_status.setVisible(is_application)
        if is_application:
            status_background, status_color = style.STATUS_COLORS[row["status"]]
            self.d_status.setText(f"Отклик {row['applied_at']} · {STATUS_TEXT[row['status']]}")
            self.d_status.setStyleSheet(f"background: {status_background}; color: {status_color};"
                                        " border-radius: 6px; padding: 6px 12px; font-weight: 600; margin-top: 12px;")
        previous = None if is_application else self._previous_application(row)
        self.d_notice.setVisible(previous is not None)
        if previous:
            self.d_notice.setText(f"Вы уже подавались на «{previous['title']}» в {previous['company']}"
                                  f" {previous['applied_at']} — статус: {STATUS_TEXT[previous['status']].lower()}")
        for button in self.found_buttons:
            button.setVisible(not is_application)
        for button in self.applied_buttons:
            button.setVisible(is_application)

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

    def apply_job(self) -> None:
        """«Подался»: вакансия уходит из найденных во вкладку «Мои отклики»."""
        db.apply(self.current["url"])
        self.show_details(None)
        self.load_rows()

    def set_status(self, status: str) -> None:
        """Отметить итог отклика; карточка остаётся на этом отклике и показывает новый статус."""
        url = self.current["url"]
        db.set_status(url, status)
        self.load_rows()
        self.show_details(next(row for row in self.applied if row["url"] == url))

    def unapply_job(self) -> None:
        """«Вернуть в найденные» — на случай, если «Подался» нажали по ошибке."""
        db.unapply(self.current["url"])
        self.show_details(None)
        self.load_rows()

    def closeEvent(self, event) -> None:
        if self.worker.model_loaded:
            llm.release(wait=False)  # не ждём: окно должно закрыться сразу
        event.accept()
