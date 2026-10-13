"""Точка входа: python -m job_finder (ярлык запускает её через pythonw.exe)."""
import logging
import os
import sys

from PySide6.QtWidgets import QApplication

from job_finder import config, db
from job_finder.window import MainWindow


def main() -> None:
    logging.basicConfig(
        filename=config.LOG_PATH, encoding="utf-8", level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    # У pythonw нет консоли: необработанные исключения пишем в лог
    sys.excepthook = lambda *exc_info: logging.critical("Необработанное исключение", exc_info=exc_info)
    db.init()
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    code = app.exec()
    # Выходим сразу, не дожидаясь фонового потока с текущим запросом к модели
    os._exit(code)


if __name__ == "__main__":
    main()
