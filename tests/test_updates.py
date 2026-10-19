import requests

from job_finder import updates


class FakeResponse:
    def __init__(self, data, status=200):
        self.data, self.status = data, status

    def raise_for_status(self):
        if self.status >= 400:
            raise requests.HTTPError(f"{self.status}")

    def json(self):
        if isinstance(self.data, Exception):
            raise self.data
        return self.data


def test_parse_version():
    assert updates.parse_version("v1.2.0") == (1, 2, 0)
    assert updates.parse_version("1.10.3") == (1, 10, 3)
    assert updates.parse_version(" v2.0 ") == (2, 0)
    assert updates.parse_version("latest") is None
    assert updates.parse_version("v1.2.0-beta") is None
    assert updates.parse_version("") is None
    assert updates.parse_version(None) is None


def test_newer_version():
    assert updates.newer_version({"tag_name": "v1.1.1"}, "1.1.0") == "1.1.1"
    assert updates.newer_version({"tag_name": "v1.10.0"}, "1.9.0") == "1.10.0"  # numbers, not text
    assert updates.newer_version({"tag_name": "v1.1.0"}, "1.1.0") is None
    assert updates.newer_version({"tag_name": "v1.0.1"}, "1.1.0") is None
    assert updates.newer_version({"tag_name": "nightly"}, "1.1.0") is None
    assert updates.newer_version({}, "1.1.0") is None
    assert updates.newer_version(["v9.0.0"], "1.1.0") is None


def test_check_asks_github_for_the_latest_release(monkeypatch):
    calls = []

    def get(url, **kwargs):
        calls.append((url, kwargs.get("timeout")))
        return FakeResponse({"tag_name": "v9.0.0", "html_url": "https://example.com/elsewhere"})

    monkeypatch.setattr(updates.requests, "get", get)
    assert updates.check("1.1.0") == "9.0.0"
    assert calls == [(updates.config.RELEASES_API, updates.config.HTTP_TIMEOUT)]


def test_check_stays_quiet_when_it_fails(monkeypatch):
    def offline(url, **kwargs):
        raise requests.ConnectionError("no internet")

    monkeypatch.setattr(updates.requests, "get", offline)
    assert updates.check("1.1.0") is None
    monkeypatch.setattr(updates.requests, "get", lambda url, **kwargs: FakeResponse({}, status=403))  # rate limit
    assert updates.check("1.1.0") is None
    monkeypatch.setattr(updates.requests, "get", lambda url, **kwargs: FakeResponse(ValueError("not JSON")))
    assert updates.check("1.1.0") is None


def test_checker_reports_a_newer_version(monkeypatch):
    found = []
    checker = updates.UpdateChecker()
    checker.found.connect(found.append)
    monkeypatch.setattr(updates, "check", lambda current=None: None)
    checker.run()
    assert found == []
    monkeypatch.setattr(updates, "check", lambda current=None: "9.0.0")
    checker.run()
    assert found == ["9.0.0"]
