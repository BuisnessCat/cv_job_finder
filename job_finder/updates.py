"""Updates of the installed app (spec section 19): is a newer GitHub release out, download its setup in the
background, and on "Restart to update" run it quietly: it waits for the app to close, installs and opens it again."""
import hashlib
import logging
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path

import requests
from PySide6.QtCore import QObject, Signal

from job_finder import config

log = logging.getLogger(__name__)
HEADERS = {"Accept": "application/vnd.github+json", "User-Agent": "job-finder (personal desktop app)"}
SETUP_NAME = "JobFinder-Setup.exe"
CHUNK = 1 << 16


class UpdateError(Exception):
    """The download is damaged or incomplete."""


@dataclass(frozen=True)
class Release:
    version: str     # "1.3.0"
    url: str = ""    # the setup's address in our repository's releases; "" if there is none to trust
    size: int = 0
    sha256: str = ""  # GitHub's checksum of the setup, when it gives one


def parse_version(tag) -> tuple[int, ...] | None:
    """"v1.2.0" → (1, 2, 0); None for anything else ("latest", "v1.2.0-beta")."""
    if not isinstance(tag, str):
        return None
    parts = tag.strip().removeprefix("v").split(".")
    if not all(part.isdigit() for part in parts):
        return None
    return tuple(int(part) for part in parts)


def newer_release(data, current: str) -> Release | None:
    """The release if it is newer than current, with its setup when it is in our repository's releases."""
    if not isinstance(data, dict):
        return None
    latest, mine = parse_version(data.get("tag_name")), parse_version(current)
    if latest is None or mine is None or latest <= mine:
        return None
    version = ".".join(map(str, latest))
    for asset in data.get("assets") or []:
        url = asset.get("browser_download_url") or ""
        if asset.get("name") == SETUP_NAME and url.startswith(config.RELEASE_DOWNLOADS):
            digest = asset.get("digest") or ""
            return Release(version, url, int(asset.get("size") or 0),
                           digest.removeprefix("sha256:") if digest.startswith("sha256:") else "")
    return Release(version)


def check(current: str = config.VERSION) -> Release | None:
    """A newer release from GitHub, or None, also when GitHub can't be reached: the check is not worth an error."""
    try:
        response = requests.get(config.RELEASES_API, headers=HEADERS, timeout=config.HTTP_TIMEOUT)
        response.raise_for_status()
        return newer_release(response.json(), current)
    except (requests.RequestException, ValueError) as error:
        log.info("Update check failed: %s", error)
        return None


def _matches(path: Path, release: Release) -> bool:
    if release.size and path.stat().st_size != release.size:
        return False
    if release.sha256:
        digest = hashlib.sha256()
        with path.open("rb") as file:
            for chunk in iter(lambda: file.read(CHUNK), b""):
                digest.update(chunk)
        return digest.hexdigest() == release.sha256.lower()
    return True


def clean(folder: Path, keep: Path | None = None) -> None:
    """Remove downloaded setups (one may still be running right after an update: it goes next time)."""
    for path in folder.glob("*") if folder.is_dir() else []:
        if path != keep:
            try:
                path.unlink()
            except OSError:
                pass


def download(release: Release, folder: Path) -> Path:
    """Download the release's setup into folder (once) and check its size and checksum."""
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"JobFinder-Setup-{release.version}.exe"
    if target.exists() and _matches(target, release):
        return target
    clean(folder)
    part = target.with_suffix(".part")
    try:
        with requests.get(release.url, headers={"User-Agent": HEADERS["User-Agent"]}, stream=True,
                          timeout=config.HTTP_TIMEOUT) as response:
            response.raise_for_status()
            with part.open("wb") as file:
                for chunk in response.iter_content(CHUNK):
                    file.write(chunk)
        if not _matches(part, release):
            raise UpdateError(f"the downloaded setup for {release.version} is damaged or incomplete")
        part.replace(target)
    finally:
        part.unlink(missing_ok=True)
    return target


def apply(setup: Path, restart: bool = True) -> None:
    """Run the downloaded setup on its own: it waits until the app has closed, installs, and (restart) opens it."""
    subprocess.Popen([str(setup), "--update", *([] if restart else ["--no-start"])], cwd=str(Path(setup).parent),
                     creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP, close_fds=True)


def start_thread(target) -> None:
    threading.Thread(target=target, daemon=True).start()  # tests run it right away


class UpdateChecker(QObject):
    """Checks for a newer release and downloads its setup; the signals come from the check's thread."""
    ready = Signal(str, str)  # version, the downloaded setup: "Restart to update"
    available = Signal(str)  # version that couldn't be downloaded: the release page, to update by hand

    def run(self) -> None:
        release = check()
        if release is None:
            clean(config.UPDATE_DIR)  # e.g. the setup of the version that runs now
            return
        if release.url:
            try:
                self.ready.emit(release.version, str(download(release, config.UPDATE_DIR)))
                return
            except (requests.RequestException, OSError, UpdateError) as error:
                log.warning("Update download failed: %s", error)
        self.available.emit(release.version)
