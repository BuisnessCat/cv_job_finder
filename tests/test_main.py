from job_finder.__main__ import acquire_lock


def test_second_instance_cannot_take_lock(tmp_path):
    first = acquire_lock(tmp_path / "job_finder.lock")
    assert first is not None
    assert acquire_lock(tmp_path / "job_finder.lock") is None  # второй запуск ярлыка
    first.unlock()
    assert acquire_lock(tmp_path / "job_finder.lock") is not None
