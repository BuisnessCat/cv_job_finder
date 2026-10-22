"""The "Getting ready" panel: is LM Studio installed and the AI model downloaded (spec sections 18.3, 20.1). It is a
step of the setup wizard and, when the setup is done, a window at start; a download starts only when the button is
clicked, and there is one download for the whole app."""
import threading

from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout, QWidget

from job_finder import config, lmstudio, style
from job_finder.hardware import vram_gb
from job_finder.window import _label

LM_STUDIO_URL = "https://lmstudio.ai"
MODEL_INFO = {config.MODEL: ("Ministral 3 8B", "about 6 GB"), config.SMALL_MODEL: ("Ministral 3 3B", "about 3 GB")}


def start_thread(target) -> None:
    threading.Thread(target=target, daemon=True).start()  # tests run it right away


def _text(name: str, text: str = "") -> QLabel:
    label = _label(name)
    label.setText(text)
    return label


class Downloader(QObject):
    """The app's one model download: the wizard, the Getting ready window and the main window see the same one."""
    done = Signal(int)  # LM Studio's exit code; emitted from the download's thread

    def __init__(self):
        super().__init__()
        self.running = False
        self.model = ""

    def start(self, model: str) -> None:
        if self.running:
            return
        self.running, self.model = True, model
        lmstudio.downloading = True
        start_thread(self.run)

    def run(self) -> None:
        try:
            code = lmstudio.download_model(self.model)
        except OSError:
            code = -1
        self.running = False
        lmstudio.downloading = False
        self.done.emit(code)


_downloader: Downloader | None = None


def downloader() -> Downloader:
    global _downloader
    if _downloader is None:
        _downloader = Downloader()
    return _downloader


class ReadyPanel(QWidget):
    """LM Studio and the model: what is there, what is missing, buttons to get it."""
    changed = Signal()  # after every check: the model may have become ready

    def __init__(self, model: str, title: str = "Getting ready", parent=None):
        super().__init__(parent)
        self.setObjectName("details")
        self.model = model
        self.name, self.size = MODEL_INFO.get(model, (model, "a few GB"))
        self.ready = False

        self.lms_status = _label()
        self.get_button = QPushButton("Get LM Studio")
        self.get_button.clicked.connect(self.open_lm_studio)
        self.model_status = _label()
        self.model_note = _text("muted")
        self.download_button = QPushButton("Download model")
        self.download_button.clicked.connect(self.start_download)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)  # LM Studio doesn't tell how far it is: a moving bar
        self.progress.hide()
        self.download_note = _text("muted")
        self.check_button = QPushButton("Check again")
        self.check_button.clicked.connect(self.check)
        for button in (self.get_button, self.download_button, self.check_button):
            button.setAutoDefault(False)

        lms_row = QHBoxLayout()
        lms_row.addWidget(self.lms_status, 1)
        lms_row.addWidget(self.get_button)
        model_row = QHBoxLayout()
        model_row.addWidget(self.model_status, 1)
        model_row.addWidget(self.download_button)
        check_row = QHBoxLayout()
        check_row.addWidget(self.check_button)
        check_row.addStretch(1)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addWidget(_text("h1", title))
        layout.addWidget(_text("muted", "Job Finder scores jobs with an AI model that runs on your own computer, "
                                        "in LM Studio (free). Two things are needed:"))
        layout.addSpacing(8)
        layout.addLayout(lms_row)
        layout.addLayout(model_row)
        layout.addWidget(self.model_note)
        layout.addWidget(self.progress)
        layout.addWidget(self.download_note)
        layout.addLayout(check_row)
        layout.addStretch(1)

        downloader().done.connect(self.on_download_done)
        if downloader().running:
            self._show_downloading()
        self.check()

    def check(self) -> None:
        installed = lmstudio.lms_installed()
        downloaded = installed and lmstudio.have_model(self.model)
        self.ready = downloaded
        self.lms_status.setText("✓ LM Studio is installed" if installed
                                else "✕ LM Studio is not installed (or was never opened). Install it, open it "
                                     "once, then click Check again.")
        self.get_button.setVisible(not installed)
        gb = vram_gb()
        card = f" (your graphics card has {gb:g} GB)" if gb else ""
        self.model_status.setText(f"✓ AI model: {self.name}{card}" if downloaded
                                  else f"✕ AI model not downloaded: {self.name}, {self.size}{card}")
        self.model_note.setText("A smaller model for graphics cards under 8 GB: it is weaker, the scores may differ "
                                "a bit." if self.model == config.SMALL_MODEL else "")
        self.model_note.setVisible(self.model == config.SMALL_MODEL)
        self.download_button.setVisible(not downloaded)
        self.download_button.setEnabled(installed and not downloader().running)
        self.changed.emit()

    def open_lm_studio(self) -> None:
        QDesktopServices.openUrl(QUrl(LM_STUDIO_URL))

    def _show_downloading(self) -> None:
        self.download_button.setEnabled(False)
        self.progress.show()
        self.download_note.setText(f"Downloading {self.name} ({self.size}). It can take a while; you can go on, "
                                   "the download continues and the jobs are scored when it has finished.")

    def start_download(self) -> None:
        if downloader().running:
            return
        self._show_downloading()
        downloader().start(self.model)

    def on_download_done(self, code: int) -> None:
        self.progress.hide()
        self.check()
        if not self.ready:
            self.download_note.setText("The download failed (no internet?). Try again, or download the model in "
                                       f"LM Studio: search for {self.name}.")
        else:
            self.download_note.setText("Done.")


class ReadyDialog(QDialog):
    """At start when the setup is done but LM Studio or the model is missing, and from the main window."""

    def __init__(self, model: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Job Finder — getting ready")
        self.setStyleSheet(style.STYLESHEET)
        self.resize(600, 380)
        self.panel = ReadyPanel(model)
        self.continue_button = QPushButton("Continue")
        self.continue_button.setObjectName("primary")
        self.continue_button.setAutoDefault(False)
        self.continue_button.clicked.connect(self.accept)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self.continue_button)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 22, 28, 20)
        layout.addWidget(self.panel, 1)
        layout.addLayout(buttons)
        self.panel.changed.connect(self.update_continue)
        self.update_continue()

    def update_continue(self) -> None:
        self.continue_button.setText("Continue" if self.panel.ready else "Continue anyway")
