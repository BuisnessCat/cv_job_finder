from job_finder import busy


def test_windows_busy_answers_without_errors():
    # No full-screen game while the tests run; on other systems or on errors the answer is "not busy"
    assert busy.windows_busy() is False
