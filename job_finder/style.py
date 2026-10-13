"""Оформление окна: тёмная тема с зелёным акцентом. Чтобы сменить тему, достаточно поменять цвета здесь."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette

COLORS = {
    "bg": "#1b1d23",           # фон окна
    "panel": "#24272f",        # карточки: таблица и детали
    "border": "#323641",
    "scroll": "#4b5060",       # ползунок прокрутки
    "text": "#e5e7eb",
    "muted": "#9ca3af",        # второстепенный текст
    "accent": "#16a34a",       # кнопки «Обновить» и «Открыть вакансию», полоса прогресса
    "accent_hover": "#15803d",
    "accent_soft": "#1e3a2b",  # выделенная строка
    "alt": "#272a33",          # чередование строк, блок «Почему такая оценка»
    "link": "#4ade80",         # ссылки в окне «Резюме»
}

GAP = 12  # единый отступ: от краёв окна и между блоками

# Цвета значков в списках деталей: ✓ есть, ✕ не хватает, ! может отсечь
LIST_COLORS = {"have": "#4ade80", "missing": "#f87171", "risks": "#fbbf24"}

# Цвета оценки: (фон плашки, цвет текста)
_GOOD = ("#14532d", "#4ade80")
_OK = ("#0c4a6e", "#7dd3fc")
_MAYBE = ("#713f12", "#fcd34d")


def score_colors(score: int) -> tuple[str, str]:
    """Цвета оценки: 8–10 зелёный, 7 синий, ниже — янтарный."""
    if score >= 8:
        return _GOOD
    if score >= 7:
        return _OK
    return _MAYBE


STYLESHEET = """
QMainWindow, QWidget#central, QDialog {{ background: {bg}; }}
QWidget {{ font-family: "Segoe UI"; font-size: 10pt; color: {text}; }}
QPushButton {{ background: {panel}; border: 1px solid {border}; border-radius: 6px; padding: 6px 14px; }}
QPushButton:hover {{ background: {alt}; }}
QPushButton:disabled {{ color: {muted}; }}
QPushButton#primary {{ background: {accent}; color: white; border: none; font-weight: 600; }}
QPushButton#primary:hover {{ background: {accent_hover}; }}
QPushButton#primary:disabled {{ background: {border}; color: {muted}; }}
QTableWidget {{ background: {panel}; border: 1px solid {border}; border-radius: 8px; gridline-color: transparent;
               selection-background-color: {accent_soft}; selection-color: {text};
               alternate-background-color: {alt}; outline: none; }}
QTableWidget::item {{ padding: 4px 8px; border: none; }}
QTableWidget::item:selected {{ background: {accent_soft}; color: {text}; }}
QHeaderView::section {{ background: {panel}; color: {muted}; font-weight: 600; border: none;
                       border-bottom: 1px solid {border}; padding: 8px; }}
QFrame#card {{ background: {panel}; border: 1px solid {border}; border-radius: 8px; }}
QTextBrowser {{ background: {panel}; border: 1px solid {border}; border-radius: 8px; padding: 12px 16px;
               selection-background-color: {accent_soft}; }}
QScrollArea#detailsScroll, QWidget#details, QWidget#detailsPage, QWidget#emptyPage {{
    background: transparent; border: none; }}
QWidget#footer {{ background: transparent; border-top: 1px solid {border}; }}
QLabel#title {{ font-size: 15pt; font-weight: 600; }}
QLabel#company {{ font-size: 11pt; }}
QLabel#metaKey, QLabel#muted {{ color: {muted}; }}
QLabel#section {{ color: {muted}; font-weight: 600; font-size: 9pt; }}
QLabel#empty {{ color: {muted}; font-size: 11pt; }}
QFrame#divider {{ background: {border}; border: none; min-height: 1px; max-height: 1px; }}
QProgressBar {{ background: {border}; border: none; border-radius: 3px; max-height: 6px; }}
QProgressBar::chunk {{ background: {accent}; border-radius: 3px; }}
QSplitter::handle {{ background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {scroll}; border-radius: 4px; min-height: 30px; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
""".format(**COLORS)


def apply_app_theme(app) -> None:
    """Тема на уровне всего приложения: то, что не задаётся стилями окна."""
    # Тёмная схема Qt: тёмные заголовок окна, полосы прокрутки и диалоги
    app.styleHints().setColorScheme(Qt.ColorScheme.Dark)
    # Ссылки из Markdown (окно «Резюме») Qt красит цветом палитры приложения, а не стилями
    palette = app.palette()
    palette.setColor(QPalette.Link, QColor(COLORS["link"]))
    app.setPalette(palette)
