"""Installing and removing the built app on a friend's computer (spec section 18.1).

JobFinder-Setup.exe (built by build.ps1) carries the app folder as a zip archive: setup_main puts it into the user's
Programs folder and makes the shortcuts. "Uninstall Job Finder" runs the app with --uninstall. The user's data
(database, applications) lives elsewhere (config.DATA_DIR) and is kept."""
import ctypes
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

APP_NAME = "Job Finder"
EXE = "Job Finder.exe"
LINKS = ("Job Finder.lnk", "Uninstall Job Finder.lnk")
CSIDL_PROGRAMS, CSIDL_DESKTOP = 0x0002, 0x0010  # the Start menu's Programs folder, the desktop
QUOTES = "'" + chr(0x2018) + chr(0x2019) + chr(0x201A) + chr(0x201B)  # PowerShell takes all of these for '


class InstallError(Exception):
    """Installing failed for a reason the person can fix; the message says how."""


class ShortcutError(InstallError):
    """The app is in place, only a shortcut could not be made."""


def install_dir(environ=os.environ) -> Path:
    if environ.get("JOB_FINDER_INSTALL_DIR"):
        return Path(environ["JOB_FINDER_INSTALL_DIR"])
    return Path(environ.get("LOCALAPPDATA") or Path.home()) / "Programs" / APP_NAME


def _shell_folder(csidl: int, fallback: Path) -> Path:
    """A Windows folder by its id: the real desktop also when it is moved (e.g. into OneDrive)."""
    try:
        buffer = ctypes.create_unicode_buffer(260)
        if ctypes.windll.shell32.SHGetFolderPathW(None, csidl, None, 0, buffer) == 0 and buffer.value:
            return Path(buffer.value)
    except (AttributeError, OSError):
        pass
    return fallback


def shortcut_dirs(environ=os.environ) -> tuple[Path, Path]:
    """The desktop and the Start menu's Programs folder; JOB_FINDER_SHORTCUTS_DIR puts both under it (for checks)."""
    if environ.get("JOB_FINDER_SHORTCUTS_DIR"):
        base = Path(environ["JOB_FINDER_SHORTCUTS_DIR"])
        return base / "Desktop", base / "Programs"
    home = Path(environ.get("USERPROFILE") or Path.home())
    return (_shell_folder(CSIDL_DESKTOP, home / "Desktop"),
            _shell_folder(CSIDL_PROGRAMS, home / "AppData/Roaming/Microsoft/Windows/Start Menu/Programs"))


def _quoted(value) -> str:
    """A PowerShell string: every kind of single quote inside is doubled."""
    text = str(value)
    for quote in QUOTES:
        text = text.replace(quote, quote * 2)
    return f"'{text}'"


def shortcut_script(link: Path, exe: Path, arguments: str = "") -> str:
    return (f"$s = (New-Object -ComObject WScript.Shell).CreateShortcut({_quoted(link)}); "
            f"$s.TargetPath = {_quoted(exe)}; $s.Arguments = {_quoted(arguments)}; "
            f"$s.WorkingDirectory = {_quoted(exe.parent)}; $s.IconLocation = {_quoted(f'{exe},0')}; $s.Save()")


def make_shortcut(link: Path, exe: Path, arguments: str = "") -> None:
    result = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command",
                             shortcut_script(link, exe, arguments)],
                            capture_output=True, text=True, errors="replace",
                            creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode != 0:
        raise ShortcutError(f"Could not make the shortcut {link.name}: {result.stderr.strip()[-200:]}")


def install(archive: Path, target: Path, desktop: Path, programs: Path, make_shortcut=make_shortcut) -> Path:
    """Put the app into target (replacing an older version) and make the shortcuts; returns the app's exe."""
    if target.exists():
        old = target.with_name(target.name + ".old")
        shutil.rmtree(old, ignore_errors=True)
        try:
            target.rename(old)  # fails while the app runs (its files are in use): nothing is deleted then
        except OSError as error:
            raise InstallError("Job Finder is running, or its folder is in use (e.g. by an antivirus scan). "
                               "Close Job Finder (right-click its icon next to the clock, Quit) and run the setup "
                               "again.") from error
        shutil.rmtree(old, ignore_errors=True)
    target.mkdir(parents=True)
    with zipfile.ZipFile(archive) as files:
        files.extractall(target)
    exe = target / EXE
    desktop.mkdir(parents=True, exist_ok=True)
    programs.mkdir(parents=True, exist_ok=True)
    make_shortcut(desktop / LINKS[0], exe)
    make_shortcut(programs / LINKS[0], exe)
    make_shortcut(programs / LINKS[1], exe, "--uninstall")
    return exe


def uninstall(target: Path, desktop: Path, programs: Path, run=subprocess.Popen) -> None:
    """Remove the shortcuts and the app's folder. The running app can't delete its own folder, so a short-lived
    command does it a few seconds after the app quits."""
    for link in (desktop / LINKS[0], programs / LINKS[0], programs / LINKS[1]):
        link.unlink(missing_ok=True)
    if target.name != APP_NAME or not (target / EXE).exists():
        return  # not the folder the setup made (e.g. the exe copied somewhere by hand): never delete it
    # Started outside the folder: a process's current folder can't be removed
    run(f'cmd /c ping -n 4 127.0.0.1 >nul & rmdir /s /q "{target}"', cwd=str(target.parent),
        creationflags=subprocess.DETACHED_PROCESS)


def message(text: str, ask: bool = False, error: bool = False) -> bool:
    """A Windows message box; with ask: Yes/No, True for Yes."""
    flags = ((0x4 if ask else 0x0) | (0x10 if error else 0x40)  # MB_YESNO, MB_ICONERROR / MB_ICONINFORMATION
             | 0x10000 | 0x40000)  # MB_SETFOREGROUND, MB_TOPMOST: not hidden behind other windows
    return ctypes.windll.user32.MessageBoxW(None, text, APP_NAME, flags) == 6  # IDYES


def setup_main(argv: list[str]) -> int:
    """JobFinder-Setup.exe: install, then offer to open the app. --quiet: no questions (for checks)."""
    quiet = "--quiet" in argv
    archive = Path(getattr(sys, "_MEIPASS", ".")) / f"{APP_NAME}.zip"
    target = install_dir()
    desktop, programs = shortcut_dirs()
    try:
        exe = install(archive, target, desktop, programs)
    except ShortcutError as error:
        if not quiet:
            message(f"Job Finder is installed in\n{target}\nbut a shortcut couldn't be made ({error}).\n\n"
                    f"You can start it from that folder: {EXE}.", error=True)
        return 1
    except (InstallError, OSError, zipfile.BadZipFile) as error:
        if not quiet:
            message(f"Job Finder was not installed.\n\n{error}", error=True)
        return 1
    if not quiet and message("Job Finder is installed: its shortcut is on the desktop and in the Start menu.\n\n"
                             "Open Job Finder now?", ask=True):
        subprocess.Popen([str(exe)], cwd=str(target))
    return 0


def uninstall_main(data_dir: Path) -> int:
    """The app run with --uninstall (the "Uninstall Job Finder" shortcut)."""
    if not getattr(sys, "frozen", False):
        message("Uninstalling is for the installed app; this is the app run from its sources.", error=True)
        return 1
    if not message(f"Remove Job Finder from this computer?\n\nYour jobs, applications and notes stay in\n{data_dir}\n"
                   "Delete that folder too if you don't need them.", ask=True):
        return 0
    desktop, programs = shortcut_dirs()
    uninstall(Path(sys.executable).parent, desktop, programs)
    return 0
