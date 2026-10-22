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


@pytest.fixture
def update_setup(tmp_path, monkeypatch):
    """setup_main run by the app's updater, with installing, waiting and starting the app faked."""
    state = {"busy": 2, "installs": 0, "started": [], "messages": []}

    def install(archive, target, desktop, programs):
        state["installs"] += 1
        if state["installs"] <= state["busy"]:  # the app is still closing: its files are in use
            raise installer.InstallError("Job Finder is running")
        return target / installer.EXE

    monkeypatch.setattr(installer, "install", install)
    monkeypatch.setattr(installer, "sleep", lambda seconds: None)
    monkeypatch.setattr(installer, "start_app", lambda exe: state["started"].append(exe))
    monkeypatch.setattr(installer, "message", lambda text, **kwargs: state["messages"].append(text))
    monkeypatch.setenv("JOB_FINDER_INSTALL_DIR", str(tmp_path / "Job Finder"))
    monkeypatch.setenv("JOB_FINDER_SHORTCUTS_DIR", str(tmp_path / "links"))
    return state


def test_update_waits_for_the_app_to_close_and_opens_it_again(update_setup, tmp_path):
    assert installer.setup_main(["setup", "--update"]) == 0
    assert update_setup["installs"] == 3  # two tries while the app was closing
    assert update_setup["started"] == [tmp_path / "Job Finder" / installer.EXE]
    assert update_setup["messages"] == []  # no questions


def test_update_on_quit_doesnt_open_the_app(update_setup):
    update_setup["busy"] = 0
    assert installer.setup_main(["setup", "--update", "--no-start"]) == 0
    assert update_setup["started"] == [] and update_setup["messages"] == []


def test_update_that_cant_install_says_so(update_setup, monkeypatch):
    update_setup["busy"] = 1000  # e.g. an antivirus holds the folder
    monkeypatch.setattr(installer, "UPDATE_TRIES", 5)
    assert installer.setup_main(["setup", "--update"]) == 1
    assert update_setup["installs"] == 5 and update_setup["started"] == []
    assert len(update_setup["messages"]) == 1 and "not updated" in update_setup["messages"][0]
