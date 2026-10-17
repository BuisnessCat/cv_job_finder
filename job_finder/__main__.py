"""Entry point: python -m job_finder (the shortcut runs it with pythonw.exe)."""
import ctypes
import logging
import os
import sys
from pathlib import Path

from PySide6.QtCore import QLockFile
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from job_finder import config, db, style
from job_finder.settings_window import first_run
from job_finder.window import MainWindow


def acquire_lock(path: Path) -> QLockFile | None:
    """The "app is already open" lock; None if another running instance holds it."""
    lock = QLockFile(str(path))
    return lock if lock.tryLock(0) else None


def main() -> None:
    logging.basicConfig(
        filename=config.LOG_PATH, encoding="utf-8", level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    # pythonw has no console: unhandled exceptions go to the log
    sys.excepthook = lambda *exc_info: logging.critical("Unhandled exception", exc_info=exc_info)
    # Our own app ID: otherwise Windows shows the pythonw.exe icon on the taskbar
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("job_finder.desktop")
    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon(str(config.ICON_PATH)))
    style.apply_app_theme(app)
    # A second launch: two windows would share one model, and closing one would unload it for the other
    lock = acquire_lock(config.ROOT / "job_finder.lock")
    if lock is None:
        QMessageBox.information(None, "Job Finder", "Job Finder is already open.")
        os._exit(0)
    db.init()
    if not first_run(config.CV_PATH):
        os._exit(0)  # the wizard was closed: nothing is saved, the next start shows it again
    window = MainWindow()
    window.show()
    code = app.exec()
    # Exit right away without waiting for the background thread with the current model request
    os._exit(code)


if __name__ == "__main__":
    main()
