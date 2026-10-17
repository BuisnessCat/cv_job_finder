import ctypes
import sys

import pytest

from job_finder import busy


def answer(state, result=0):
    def fake(pointer):
        pointer._obj.value = state
        return result
    return fake


@pytest.mark.skipif(sys.platform != "win32", reason="the check asks Windows")
def test_busy_states(monkeypatch):
    for state, expected in [(2, True), (3, True), (4, True), (5, False), (1, False)]:
        monkeypatch.setattr(ctypes.windll.shell32, "SHQueryUserNotificationState", answer(state))
        assert busy.windows_busy() is expected, state
    monkeypatch.setattr(ctypes.windll.shell32, "SHQueryUserNotificationState", answer(3, result=-1))
    assert busy.windows_busy() is False  # Windows could not tell: not busy
