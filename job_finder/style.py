"""Window look: a dark theme with a green accent. To change the theme, change the colors here."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette

COLORS = {
    "bg": "#1b1d23",           # window background
    "panel": "#24272f",        # cards: table and details
    "border": "#323641",
    "scroll": "#4b5060",       # scrollbar handle
    "text": "#e5e7eb",
    "muted": "#9ca3af",        # secondary text
    "accent": "#16a34a",       # "Refresh" and "Open job" buttons, progress bar
    "accent_hover": "#15803d",
    "accent_soft": "#1e3a2b",  # selected row
    "alt": "#272a33",          # alternating rows, the "Why this score" block
    "link": "#4ade80",         # links in the "My CV" window
    "notice_bg": "#3a2f12",    # yellow "You already applied" notice
    "notice_text": "#fcd34d",
}

GAP = 12  # one spacing: from the window edges and between blocks

# Marker colors in the detail lists: ✓ you have, ✕ missing, ! risks
LIST_COLORS = {"have": "#4ade80", "missing": "#f87171", "risks": "#fbbf24"}

# Application status colors: (pill background, text color) for waiting, accepted, rejected
STATUS_COLORS = {"applied": ("#0c4a6e", "#7dd3fc"), "accepted": ("#14532d", "#4ade80"),
                 "rejected": ("#7f1d1d", "#fca5a5")}

# Score colors: (pill background, text color)
_GOOD = ("#14532d", "#4ade80")
_OK = ("#0c4a6e", "#7dd3fc")
_MAYBE = ("#713f12", "#fcd34d")


def score_colors(score: int) -> tuple[str, str]:
    """Score colors: 8–10 green, 7 blue, lower amber."""
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
QPushButton#segmentLeft, QPushButton#segmentMiddle, QPushButton#segmentRight {{ background: {panel}; color: {muted};
    font-weight: 600; border: 1px solid {border}; padding: 6px 14px; }}
QPushButton#segmentLeft {{ border-radius: 0; border-top-left-radius: 6px; border-bottom-left-radius: 6px; }}
QPushButton#segmentMiddle {{ border-radius: 0; border-left: none; }}
QPushButton#segmentRight {{ border-radius: 0; border-top-right-radius: 6px; border-bottom-right-radius: 6px;
                           border-left: none; }}
QPushButton#segmentLeft:checked, QPushButton#segmentMiddle:checked, QPushButton#segmentRight:checked {{
    background: {accent_soft}; color: {text}; }}
QLabel#notice {{ background: {notice_bg}; color: {notice_text}; border-radius: 6px; padding: 8px 12px;
                margin-top: 12px; }}
QLabel#staleHint {{ color: {notice_text}; margin-top: 6px; }}
QPlainTextEdit#notes {{ background: {alt}; border: 1px solid {border}; border-radius: 6px; padding: 6px;
                       selection-background-color: {accent_soft}; }}
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
QScrollArea#detailsScroll, QWidget#details, QWidget#detailsPage, QWidget#emptyPage, QScrollArea#insightsScroll,
QWidget#insightsPage {{
    background: transparent; border: none; }}
QWidget#footer {{ background: transparent; border-top: 1px solid {border}; }}
QLabel#title {{ font-size: 15pt; font-weight: 600; }}
QLabel#company {{ font-size: 11pt; }}
QLabel#metaKey, QLabel#muted, QLabel#barCount {{ color: {muted}; }}
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
    """App-wide theme: what window style sheets cannot set."""
    # Qt dark scheme: dark title bar, scrollbars and dialogs
    app.styleHints().setColorScheme(Qt.ColorScheme.Dark)
    # Qt colors Markdown links (the "My CV" window) from the app palette, not from style sheets
    palette = app.palette()
    palette.setColor(QPalette.Link, QColor(COLORS["link"]))
    app.setPalette(palette)
