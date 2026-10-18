from pathlib import Path

from job_finder import config


def test_data_dir():
    assert config.data_dir(False, {"LOCALAPPDATA": "C:/L"}) == config.ROOT  # from the sources: as before
    assert config.data_dir(True, {"LOCALAPPDATA": "C:/L"}) == Path("C:/L/Job Finder")  # the installed app
    assert config.data_dir(True, {"LOCALAPPDATA": "C:/L", "JOB_FINDER_DATA": "D:/t"}) == Path("D:/t")
    assert config.data_dir(False, {"JOB_FINDER_DATA": "D:/t"}) == Path("D:/t")


def test_one_lock_for_the_sources_and_the_installed_app():
    assert config.lock_path({"LOCALAPPDATA": "C:/L"}) == Path("C:/L/Job Finder/job_finder.lock")
    assert config.lock_path({"LOCALAPPDATA": "C:/L", "JOB_FINDER_DATA": "D:/t"}) == Path("D:/t/job_finder.lock")
