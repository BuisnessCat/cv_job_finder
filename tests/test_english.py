"""The app is published in English: no Cyrillic in code, comments, tests or the installer."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CYRILLIC = re.compile(f"[{chr(0x400)}-{chr(0x4FF)}]")  # built from codes, so this file passes its own check


def test_no_cyrillic_in_code():
    files = [*ROOT.glob("job_finder/*.py"), *ROOT.glob("tests/*.py"), ROOT / "install.ps1"]
    found = [f"{path.relative_to(ROOT)}:{number}: {line.strip()[:60]}"
             for path in files
             for number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1)
             if CYRILLIC.search(line)]
    assert found == []


def test_installer_is_ascii():
    assert (ROOT / "install.ps1").read_bytes().lstrip(b"\xef\xbb\xbf").isascii()
