import hashlib
import subprocess

import pytest
import requests

from job_finder import updates

SETUP = b"the new setup"
URL = "https://github.com/BuisnessCat/cv_job_finder/releases/download/v9.0.0/JobFinder-Setup.exe"


class FakeResponse:
    def __init__(self, data=None, status=200, body=b""):
        self.data, self.status, self.body = data, status, body

    def raise_for_status(self):
        if self.status >= 400:
            raise requests.HTTPError(f"{self.status}")

    def json(self):
        if isinstance(self.data, Exception):
            raise self.data
        return self.data

    def iter_content(self, size):
        yield from (self.body[i:i + size] for i in range(0, len(self.body), size))

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def release_data(tag="v9.0.0", url=URL, digest="sha256:" + hashlib.sha256(SETUP).hexdigest(), name=None):
    return {"tag_name": tag, "html_url": "https://example.com/elsewhere",
            "assets": [{"name": "notes.txt", "browser_download_url": URL.replace("JobFinder-Setup.exe", "notes.txt"),
                        "size": 5},
                       {"name": name or updates.SETUP_NAME, "browser_download_url": url, "size": len(SETUP),
                        "digest": digest}]}


def test_parse_version():
    assert updates.parse_version("v1.2.0") == (1, 2, 0)
    assert updates.parse_version("1.10.3") == (1, 10, 3)
    assert updates.parse_version(" v2.0 ") == (2, 0)
    assert updates.parse_version("latest") is None
    assert updates.parse_version("v1.2.0-beta") is None
    assert updates.parse_version("") is None
    assert updates.parse_version(None) is None


def test_newer_release_with_its_setup():
    assert updates.newer_release(release_data(), "1.2.0") == updates.Release(
        "9.0.0", URL, len(SETUP), hashlib.sha256(SETUP).hexdigest())
    assert updates.newer_release(release_data("v1.10.0"), "1.9.0").version == "1.10.0"  # numbers, not text
    assert updates.newer_release(release_data("v1.2.0"), "1.2.0") is None
    assert updates.newer_release(release_data("v1.0.1"), "1.2.0") is None
    assert updates.newer_release(release_data("nightly"), "1.2.0") is None
    assert updates.newer_release({}, "1.2.0") is None
    assert updates.newer_release(["v9.0.0"], "1.2.0") is None


def test_a_setup_from_anywhere_else_is_not_downloaded():
    elsewhere = updates.newer_release(release_data(url="https://example.com/JobFinder-Setup.exe"), "1.2.0")
    assert elsewhere == updates.Release("9.0.0")  # a newer version, to be updated by hand
    assert updates.newer_release(release_data(name="Other.exe"), "1.2.0") == updates.Release("9.0.0")
    assert updates.newer_release({"tag_name": "v9.0.0"}, "1.2.0") == updates.Release("9.0.0")
    no_digest = updates.newer_release(release_data(digest=None), "1.2.0")
    assert no_digest.url == URL and no_digest.sha256 == ""  # the size is still checked


def test_check_asks_github_for_the_latest_release(monkeypatch):
    calls = []

    def get(url, **kwargs):
        calls.append((url, kwargs.get("timeout")))
        return FakeResponse(release_data())

    monkeypatch.setattr(updates.requests, "get", get)
    assert updates.check("1.2.0").version == "9.0.0"
    assert calls == [(updates.config.RELEASES_API, updates.config.HTTP_TIMEOUT)]


def test_check_stays_quiet_when_it_fails(monkeypatch):
    def offline(url, **kwargs):
        raise requests.ConnectionError("no internet")

    monkeypatch.setattr(updates.requests, "get", offline)
    assert updates.check("1.2.0") is None
    monkeypatch.setattr(updates.requests, "get", lambda url, **kwargs: FakeResponse({}, status=403))  # rate limit
    assert updates.check("1.2.0") is None
    monkeypatch.setattr(updates.requests, "get", lambda url, **kwargs: FakeResponse(ValueError("not JSON")))
    assert updates.check("1.2.0") is None


def test_download_checks_the_file(tmp_path, monkeypatch):
    release = updates.newer_release(release_data(), "1.2.0")
    asked = []

    def get(url, **kwargs):
        asked.append((url, kwargs.get("stream")))
        return FakeResponse(body=SETUP)

    monkeypatch.setattr(updates.requests, "get", get)
    (tmp_path / "JobFinder-Setup-8.0.0.exe").write_bytes(b"an older update")
    path = updates.download(release, tmp_path)
    assert path == tmp_path / "JobFinder-Setup-9.0.0.exe" and path.read_bytes() == SETUP
    assert asked == [(URL, True)]
    assert sorted(p.name for p in tmp_path.iterdir()) == ["JobFinder-Setup-9.0.0.exe"]  # the older one is gone
    assert updates.download(release, tmp_path) == path and len(asked) == 1  # already here: not again


def test_a_damaged_download_is_thrown_away(tmp_path, monkeypatch):
    release = updates.newer_release(release_data(), "1.2.0")
    monkeypatch.setattr(updates.requests, "get", lambda url, **kwargs: FakeResponse(body=b"the new setuX"))
    with pytest.raises(updates.UpdateError):
        updates.download(release, tmp_path)  # same size, another checksum
    monkeypatch.setattr(updates.requests, "get", lambda url, **kwargs: FakeResponse(body=SETUP[:5]))
    with pytest.raises(updates.UpdateError):
        updates.download(updates.Release("9.0.0", URL, len(SETUP)), tmp_path)  # cut short
    assert list(tmp_path.iterdir()) == []


def test_checker_downloads_and_says_when_it_is_ready(tmp_path, monkeypatch):
    ready, available = [], []
    checker = updates.UpdateChecker()
    checker.ready.connect(lambda version, path: ready.append((version, path)))
    checker.available.connect(available.append)
    monkeypatch.setattr(updates.config, "UPDATE_DIR", tmp_path)
    monkeypatch.setattr(updates, "check", lambda current=None: updates.Release("9.0.0", URL, 1, ""))
    monkeypatch.setattr(updates, "download", lambda release, folder: folder / "JobFinder-Setup-9.0.0.exe")
    checker.run()
    assert ready == [("9.0.0", str(tmp_path / "JobFinder-Setup-9.0.0.exe"))] and available == []


def test_checker_falls_back_to_the_release_page(tmp_path, monkeypatch):
    ready, available = [], []
    checker = updates.UpdateChecker()
    checker.ready.connect(lambda version, path: ready.append((version, path)))
    checker.available.connect(available.append)
    monkeypatch.setattr(updates.config, "UPDATE_DIR", tmp_path)

    def broken(release, folder):
        raise updates.UpdateError("damaged")

    monkeypatch.setattr(updates, "check", lambda current=None: updates.Release("9.0.0", URL, 1, ""))
    monkeypatch.setattr(updates, "download", broken)
    checker.run()
    monkeypatch.setattr(updates, "check", lambda current=None: updates.Release("9.1.0"))  # no setup to trust
    checker.run()
    assert available == ["9.0.0", "9.1.0"] and ready == []


def test_checker_cleans_up_when_up_to_date(tmp_path, monkeypatch):
    monkeypatch.setattr(updates.config, "UPDATE_DIR", tmp_path)
    (tmp_path / "JobFinder-Setup-1.2.0.exe").write_bytes(b"the setup that installed this version")
    monkeypatch.setattr(updates, "check", lambda current=None: None)
    updates.UpdateChecker().run()
    assert list(tmp_path.iterdir()) == []


def test_apply_starts_the_setup_on_its_own(monkeypatch, tmp_path):
    started = []
    monkeypatch.setattr(updates.subprocess, "Popen", lambda args, **kwargs: started.append((args, kwargs)))
    setup = tmp_path / "JobFinder-Setup-9.0.0.exe"
    updates.apply(setup)
    updates.apply(setup, restart=False)
    assert [args for args, _ in started] == [[str(setup), "--update"], [str(setup), "--update", "--no-start"]]
    assert started[0][1]["creationflags"] & subprocess.DETACHED_PROCESS  # it outlives the app
