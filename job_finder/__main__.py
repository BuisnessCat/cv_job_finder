"""Точка входа: python -m job_finder (ярлык запускает её через pythonw.exe)."""
import logging
import os
import sys
from pathlib import Path

from PySide6.QtCore import QLockFile, Qt
from PySide6.QtWidgets import QApplication, QMessageBox

from job_finder import config, db
from job_finder.window import MainWindow


def acquire_lock(path: Path) -> QLockFile | None:
    """Блокировка «приложение уже открыто»; None, если её держит другой запущенный экземпляр."""
    lock = QLockFile(str(path))
    return lock if lock.tryLock(0) else None


def main() -> None:
    logging.basicConfig(
        filename=config.LOG_PATH, encoding="utf-8", level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    # У pythonw нет консоли: необработанные исключения пишем в лог
    sys.excepthook = lambda *exc_info: logging.critical("Необработанное исключение", exc_info=exc_info)
    app = QApplication(sys.argv)
    # Тёмная схема Qt: тёмные заголовок окна, полосы прокрутки и диалоги — под тему из style.py
    app.styleHints().setColorScheme(Qt.ColorScheme.Dark)
    # Второй двойной клик по ярлыку: два окна делили бы одну модель, и закрытие одного выгружало бы её у другого
    lock = acquire_lock(config.ROOT / "job_finder.lock")
    if lock is None:
        QMessageBox.information(None, "Подбор вакансий", "Приложение уже открыто.")
        os._exit(0)
    db.init()
    window = MainWindow()
    window.show()
    code = app.exec()
    # Выходим сразу, не дожидаясь фонового потока с текущим запросом к модели
    os._exit(code)


if __name__ == "__main__":
    main()
