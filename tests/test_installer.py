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
    commands = []
    installer.uninstall(target, desktop, start, run=lambda command, **kwargs: commands.append(command))
    assert not list(desktop.iterdir()) and not list(start.iterdir())
    # The running app can't delete its own folder: a short-lived command does it after the app quits
    assert "rmdir /s /q" in commands[0] and f'"{target}"' in commands[0]


def test_shortcut_script_quotes_paths():
    script = installer.shortcut_script(Path("C:/Users/O'Brien/Desktop/Job Finder.lnk"),
                                       Path("C:/Users/O'Brien/AppData/Local/Programs/Job Finder/Job Finder.exe"),
                                       "--uninstall")
    assert "O''Brien" in script and "'--uninstall'" in script
