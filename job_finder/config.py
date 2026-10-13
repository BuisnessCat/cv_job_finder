"""Настройки приложения."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CV_PATH = ROOT / "master_cv.md"
DB_PATH = ROOT / "jobs.db"
LOG_PATH = ROOT / "job_finder.log"
ICON_PATH = ROOT / "job_finder" / "icon.ico"

# Показываем вакансии с оценкой не ниже порога
MIN_SCORE = 5

# LM Studio
LMS_EXE = Path.home() / ".lmstudio" / "bin" / "lms.exe"
LM_PORT = 1234
LM_URL = f"http://localhost:{LM_PORT}/v1"
MODEL = "mistralai/ministral-3-8b"
MODEL_ID = "job-finder"  # идентификатор загруженной модели в LM Studio и в API
CONTEXT_LENGTH = 8192
MAX_DESCRIPTION_CHARS = 8000

# Источники
HTTP_TIMEOUT = 30
JUNIORGURU_URL = "https://junior.guru/api/jobs.csv"
HIMALAYAS_URL = "https://himalayas.app/jobs/api/search"
# Чтобы сократить первую оценку, можно оставить только "Entry-level"
HIMALAYAS_PARAMS = {"q": "python", "country": "CZ", "seniority": "Entry-level,Mid-level", "sort": "recent"}
HIMALAYAS_MAX_PAGES = 10  # по 20 вакансий на страницу
JOBICY_URL = "https://jobicy.com/api/v2/remote-jobs"
JOBICY_PARAMS = {"count": 50, "geo": "czechia", "industry": "dev"}
WORKINGNOMADS_URL = "https://www.workingnomads.com/api/exposed_jobs/"
