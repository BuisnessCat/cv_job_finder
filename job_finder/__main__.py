"""Entry point: python -m job_finder (the shortcut runs it with pythonw.exe)."""
import ctypes
import logging
import os
import sys
from pathlib import Path

from PySide6.QtCore import QLockFile
from PySide6.QtNetwork import QLocalSocket
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from job_finder import config, db, installer, llm, lmstudio, ready_window, settings, style
from job_finder.settings import Settings
from job_finder.settings_window import first_run
from job_finder.window import MainWindow

SERVER_NAME = "job_finder"  # a second launch tells the running app through it to show its window


def acquire_lock(path: Path) -> QLockFile | None:
    """The "app is already open" lock; None if another running instance holds it."""
    lock = QLockFile(str(path))
    return lock if lock.tryLock(0) else None


def tell_running_instance(name: str = SERVER_NAME) -> bool:
    """Ask a running Job Finder (maybe hidden in the tray) to show its window; False if none answers."""
    try:
        ctypes.windll.user32.AllowSetForegroundWindow(-1)  # ASFW_ANY: the running app may come to the front
    except (AttributeError, OSError):
        pass
    socket = QLocalSocket()
    socket.connectToServer(name)
    if not socket.waitForConnected(1000):
        return False
    socket.write(b"show")
    socket.waitForBytesWritten(1000)
    socket.disconnectFromServer()
    return True


def main() -> None:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    config.LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=config.LOG_PATH, encoding="utf-8", level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    # pythonw has no console: unhandled exceptions go to the log
    sys.excepthook = lambda *exc_info: logging.critical("Unhandled exception", exc_info=exc_info)
    if "--uninstall" in sys.argv:  # the "Uninstall Job Finder" shortcut
        lock = acquire_lock(config.LOCK_PATH)  # kept until the end: the app can't start while removing
        if lock is None:
            installer.message("Job Finder is running. Close it (right-click its icon next to the clock, Quit) "
                              "and try again.", error=True)
            os._exit(1)
        os._exit(installer.uninstall_main(config.DATA_DIR))
    # Our own app ID: otherwise Windows shows the pythonw.exe icon on the taskbar
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("job_finder.desktop")
    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon(str(config.ICON_PATH)))
    style.apply_app_theme(app)
    # A second launch: two windows would share one model, and closing one would unload it for the other
    lock = acquire_lock(config.LOCK_PATH)
    if lock is None:
        if not tell_running_instance():  # it may be hidden in the tray: its window comes up
            QMessageBox.information(None, "Job Finder", "Job Finder is already open.")
        os._exit(0)
    db.init()
    saved = settings.load()
    model = llm.model_name(saved or Settings())
    ready = lmstudio.everything_ready(model)
    if not ready and saved is not None and not settings.missing(saved):
        ready_window.ReadyDialog(model).exec()  # the setup is done, LM Studio or the model is missing
    setup = saved is None or bool(settings.missing(saved))
    if not first_run(config.CV_PATH, None if ready else model):  # the wizard's first step gets them
        os._exit(0)  # the wizard was closed: nothing is saved, the next start shows it again
    window = MainWindow(score_now=setup)  # after Start search the first scoring starts right away
    window.listen_for_launches(SERVER_NAME)
    window.show()
    code = app.exec()
    # Exit right away without waiting for the background thread with the current model request
    os._exit(code)


if __name__ == "__main__":
    main()
