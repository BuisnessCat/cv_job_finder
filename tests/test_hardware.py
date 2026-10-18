from job_finder import hardware

GIB = 2 ** 30


def test_model_for_vram():
    assert hardware.model_for_vram(12.0) == "mistralai/ministral-3-8b"
    assert hardware.model_for_vram(7.9) == "mistralai/ministral-3-8b"  # an 8 GB card reports a bit less
    assert hardware.model_for_vram(6.0) == "mistralai/ministral-3-3b"
    assert hardware.model_for_vram(None) == "mistralai/ministral-3-8b"  # unknown: the usual model


def test_vram_from_registry_values():
    # REG_BINARY bytes or a REG_QWORD number; the biggest card counts
    assert hardware.vram_gb(lambda: [(12 * GIB).to_bytes(8, "little"), 128 * 2 ** 20]) == 12.0
    assert hardware.vram_gb(lambda: []) is None
    assert hardware.vram_gb(lambda: [b"", "junk", 0]) is None

    def no_access():
        raise OSError("access denied")

    assert hardware.vram_gb(no_access) is None
