"""Is a newer version out? The latest GitHub release against config.VERSION (the installed app only)."""
import logging
import threading

import requests
from PySide6.QtCore import QObject, Signal

from job_finder import config

log = logging.getLogger(__name__)
HEADERS = {"Accept": "application/vnd.github+json", "User-Agent": "job-finder (personal desktop app)"}


def parse_version(tag) -> tuple[int, ...] | None:
    """"v1.2.0" → (1, 2, 0); None for anything else ("latest", "v1.2.0-beta")."""
    if not isinstance(tag, str):
        return None
    parts = tag.strip().removeprefix("v").split(".")
    if not all(part.isdigit() for part in parts):
        return None
    return tuple(int(part) for part in parts)


def newer_version(release, current: str) -> str | None:
    """The release's version ("1.2.0") if it is newer than current, else None."""
    if not isinstance(release, dict):
        return None
    latest, mine = parse_version(release.get("tag_name")), parse_version(current)
    if latest is None or mine is None or latest <= mine:
        return None
    return ".".join(map(str, latest))


def check(current: str = config.VERSION) -> str | None:
    """A newer version from GitHub, or None, also when GitHub can't be reached: the check is not worth an error."""
    try:
        response = requests.get(config.RELEASES_API, headers=HEADERS, timeout=config.HTTP_TIMEOUT)
        response.raise_for_status()
        return newer_version(response.json(), current)
    except (requests.RequestException, ValueError) as error:
        log.info("Update check failed: %s", error)
        return None


def start_thread(target) -> None:
    threading.Thread(target=target, daemon=True).start()  # tests run it right away


class UpdateChecker(QObject):
    found = Signal(str)  # the newer version; emitted from the check's thread, delivered in the window's

    def run(self) -> None:
        version = check()
        if version:
            self.found.emit(version)
