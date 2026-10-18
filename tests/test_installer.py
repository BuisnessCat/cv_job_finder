import zipfile
from pathlib import Path

import pytest

from job_finder import installer


def archive_with(path, files):
    with zipfile.ZipFile(path, "w") as archive:
        for name, text in files.items():
            archive.writestr(name, text)
    return path


def test_folders_from_the_environment():
    assert installer.install_dir({"LOCALAPPDATA": "C:/L"}) == Path("C:/L/Programs/Job Finder")
    assert installer.install_dir({"LOCALAPPDATA": "C:/L", "JOB_FINDER_INSTALL_DIR": "D:/t"}) == Path("D:/t")
    assert installer.shortcut_dirs({"JOB_FINDER_SHORTCUTS_DIR": "D:/s"}) == (Path("D:/s/Desktop"), Path("D:/s/Programs"))


def test_install_replaces_old_files_and_makes_shortcuts(tmp_path):
    archive = archive_with(tmp_path / "app.zip", {"Job Finder.exe": "new", "_internal/base.dll": "x"})
    target = tmp_path / "Programs" / "Job Finder"
    target.mkdir(parents=True)
    (target / "old.dll").write_text("from the previous version")
    made = []
    exe = installer.install(archive, target, tmp_path / "Desktop", tmp_path / "Start",
                            make_shortcut=lambda link, exe, arguments="": made.append((str(link.relative_to(tmp_path)),
                                                                                       exe.name, arguments)))
    assert exe == target / "Job Finder.exe" and exe.read_text() == "new"
    assert (target / "_internal" / "base.dll").exists() and not (target / "old.dll").exists()
    assert made == [(str(Path("Desktop/Job Finder.lnk")), "Job Finder.exe", ""),
                    (str(Path("Start/Job Finder.lnk")), "Job Finder.exe", ""),
                    (str(Path("Start/Uninstall Job Finder.lnk")), "Job Finder.exe", "--uninstall")]
    assert not list(tmp_path.glob("Programs/*.old"))  # the previous version's folder is gone


def test_install_over_a_running_app(tmp_path, monkeypatch):
    archive = archive_with(tmp_path / "app.zip", {"Job Finder.exe": "new"})
    target = tmp_path / "Job Finder"
    target.mkdir()
    (target / "Job Finder.exe").write_text("old, running")

    def in_use(self, other):
        raise PermissionError("the file is being used by another process")

    monkeypatch.setattr(Path, "rename", in_use)
    with pytest.raises(installer.InstallError, match="Quit"):
        installer.install(archive, target, tmp_path / "D", tmp_path / "S", make_shortcut=lambda *args: None)
    assert (target / "Job Finder.exe").read_text() == "old, running"  # nothing was broken


def test_uninstall_removes_shortcuts_and_schedules_the_folder(tmp_path):
    desktop, start = tmp_path / "Desktop", tmp_path / "Start"
    for link in (desktop / "Job Finder.lnk", start / "Job Finder.lnk", start / "Uninstall Job Finder.lnk"):
        link.parent.mkdir(exist_ok=True)
        link.write_text("")
    target = tmp_path / "Programs" / "Job Finder"
    target.mkdir(parents=True)
    (target / "Job Finder.exe").write_text("")
    commands = []
    installer.uninstall(target, desktop, start, run=lambda command, **kwargs: commands.append((command, kwargs)))
    assert not list(desktop.iterdir()) and not list(start.iterdir())
    # The running app can't delete its own folder: a short-lived command does it after the app quits,
    # started outside the folder (a process's current folder can't be removed)
    command, kwargs = commands[0]
    assert "rmdir /s /q" in command and f'"{target}"' in command and kwargs["cwd"] == str(target.parent)


def test_uninstall_deletes_only_the_apps_own_folder(tmp_path):
    shared = tmp_path / "Downloads"  # the exe copied somewhere else by hand
    shared.mkdir()
    (shared / "Job Finder.exe").write_text("")
    commands = []
    installer.uninstall(shared, tmp_path / "D", tmp_path / "S", run=lambda command, **kwargs: commands.append(command))
    assert commands == []


def test_shortcut_script_quotes_paths():
    script = installer.shortcut_script(Path("C:/Users/O'Brien/Desktop/Job Finder.lnk"),
                                       Path("C:/Users/O'Brien/AppData/Local/Programs/Job Finder/Job Finder.exe"),
                                       "--uninstall")
    assert "O''Brien" in script and "'--uninstall'" in script
    quote = chr(0x2019)  # a typographic quote: PowerShell treats it like an apostrophe
    assert f"Ji{quote}{quote}" in installer.shortcut_script(Path(f"C:/Ji{quote}/x.lnk"), Path("C:/a.exe"))


def test_shortcut_failure_after_install_says_it_is_installed(tmp_path):
    archive = archive_with(tmp_path / "app.zip", {"Job Finder.exe": "new"})

    def broken(link, exe, arguments=""):
        raise installer.ShortcutError("Could not make the shortcut Job Finder.lnk")

    with pytest.raises(installer.ShortcutError):
        installer.install(archive, tmp_path / "Job Finder", tmp_path / "D", tmp_path / "S", make_shortcut=broken)
    assert (tmp_path / "Job Finder" / "Job Finder.exe").exists()  # the app is there, only a shortcut is missing
