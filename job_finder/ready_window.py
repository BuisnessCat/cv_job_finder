"""The "Getting ready" window: is LM Studio installed and the AI model downloaded (spec section 18.3).
Shown at start only when something is missing; a download starts only when the button is clicked."""
import subprocess
import threading

from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout

from job_finder import config, llm, style
from job_finder.hardware import vram_gb
from job_finder.window import _label

LM_STUDIO_URL = "https://lmstudio.ai"
MODEL_INFO = {config.MODEL: ("Ministral 3 8B", "about 6 GB"), config.SMALL_MODEL: ("Ministral 3 3B", "about 3 GB")}


def lms_installed() -> bool:
    """LM Studio's command-line tool appears after LM Studio has been opened once."""
    return config.LMS_EXE.exists()


def everything_ready(model: str) -> bool:
    return lms_installed() and model in llm.downloaded_models()


def download_model(model: str) -> int:
    """Download the model with LM Studio; returns its exit code. Output is not captured: LM Studio's background
    service started by the command would inherit our pipes and the call would never end."""
    return subprocess.run(
        [str(config.LMS_EXE), "get", model, "-y"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW,
    ).returncode


def start_thread(target) -> None:
    threading.Thread(target=target, daemon=True).start()  # tests run it right away


def _text(name: str, text: str = "") -> QLabel:
    label = _label(name)
    label.setText(text)
    return label


class Downloader(QObject):
    done = Signal(int)

    def __init__(self, model: str):
        super().__init__()
        self.model = model

    def run(self) -> None:
        try:
            code = download_model(self.model)
        except OSError:
            code = -1
        self.done.emit(code)


class ReadyDialog(QDialog):
    def __init__(self, model: str, parent=None):
        super().__init__(parent)
        self.model = model
        self.name, self.size = MODEL_INFO.get(model, (model, "a few GB"))
        self.downloading = False
        self.setWindowTitle("Job Finder — getting ready")
        self.setStyleSheet(style.STYLESHEET)
        self.resize(600, 360)

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
        self.continue_button = QPushButton("Continue")
        self.continue_button.setObjectName("primary")
        self.continue_button.clicked.connect(self.accept)
        for button in (self.get_button, self.download_button, self.check_button, self.continue_button):
            button.setAutoDefault(False)

        lms_row = QHBoxLayout()
        lms_row.addWidget(self.lms_status, 1)
        lms_row.addWidget(self.get_button)
        model_row = QHBoxLayout()
        model_row.addWidget(self.model_status, 1)
        model_row.addWidget(self.download_button)
        buttons = QHBoxLayout()
        buttons.addWidget(self.check_button)
        buttons.addStretch(1)
        buttons.addWidget(self.continue_button)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 22, 28, 20)
        layout.setSpacing(10)
        layout.addWidget(_text("h1", "Getting ready"))
        layout.addWidget(_text("muted", "Job Finder scores jobs with an AI model that runs on your own computer, "
                                        "in LM Studio (free). Two things are needed:"))
        layout.addSpacing(8)
        layout.addLayout(lms_row)
        layout.addLayout(model_row)
        layout.addWidget(self.model_note)
        layout.addWidget(self.progress)
        layout.addWidget(self.download_note)
        layout.addStretch(1)
        layout.addLayout(buttons)

        self.downloader = Downloader(model)
        self.downloader.done.connect(self.on_download_done)
        self.check()

    def check(self) -> None:
        installed = lms_installed()
        downloaded = installed and self.model in llm.downloaded_models()
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
        self.download_button.setEnabled(installed and not self.downloading)
        self.continue_button.setText("Continue" if downloaded else "Continue anyway")

    def open_lm_studio(self) -> None:
        QDesktopServices.openUrl(QUrl(LM_STUDIO_URL))

    def start_download(self) -> None:
        self.downloading = True
        self.download_button.setEnabled(False)
        self.progress.show()
        self.download_note.setText(f"Downloading {self.name} ({self.size}). It can take a while; you can keep "
                                   "this window open or continue, the download goes on.")
        start_thread(self.downloader.run)

    def on_download_done(self, code: int) -> None:
        self.downloading = False
        self.progress.hide()
        self.check()
        if self.model not in llm.downloaded_models():
            self.download_note.setText("The download failed (no internet?). Try again, or download the model in "
                                       f"LM Studio: search for {self.name}.")
        else:
            self.download_note.setText("Done.")
