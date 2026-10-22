"""Is LM Studio installed and the AI model downloaded (spec sections 18.3, 20.1). No windows here: the worker, the
Getting ready panel and the setup wizard all ask this module. It looks on disk first and asks LM Studio itself
(which may start it) only when it must."""
import json
import subprocess
from pathlib import Path

from job_finder import config, llm

MODEL_FILES = {config.MODEL: "ministral-3-8b", config.SMALL_MODEL: "ministral-3-3b"}  # how the model's file starts
downloading = False  # a model download runs right now (set by the app's one downloader)


def lms_installed() -> bool:
    """LM Studio's command-line tool appears after LM Studio has been opened once."""
    return config.LMS_EXE.exists()


def _downloads_folder() -> Path:
    """LM Studio's downloads folder: from its settings (it can be moved), else the default one."""
    try:
        folder = json.loads((config.LMS_HOME / "settings.json").read_text(encoding="utf-8")).get("downloadsFolder")
    except (OSError, ValueError, AttributeError):
        folder = None
    return Path(folder) if folder else config.LMS_HOME / "models"


def model_file_present(model: str) -> bool:
    """Whether the model's file is in LM Studio's downloads folder: a look on disk, LM Studio isn't started."""
    start, folder = MODEL_FILES.get(model), _downloads_folder()
    if not start or not folder.is_dir():
        return False
    return any(file.name.lower().startswith(start) for file in folder.rglob("*.gguf"))


def have_model(model: str) -> bool:
    """The file on disk is enough; only without it LM Studio itself is asked (which may start it)."""
    return model_file_present(model) or model in llm.downloaded_models()


def everything_ready(model: str) -> bool:
    return lms_installed() and have_model(model)


def download_model(model: str) -> int:
    """Download the model with LM Studio; returns its exit code. Output is not captured: LM Studio's background
    service started by the command would inherit our pipes and the call would never end."""
    return subprocess.run(
        [str(config.LMS_EXE), "get", model, "-y"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW,
    ).returncode
