"""App settings."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CV_PATH = ROOT / "master_cv.md"  # if it exists, the first-run wizard offers it as the CV
DB_PATH = ROOT / "jobs.db"
LOG_PATH = ROOT / "job_finder.log"
ICON_PATH = ROOT / "job_finder" / "icon.ico"

# Sources that return their whole list: a job missing from them was probably taken down
FULL_LIST_SOURCES = ("junior.guru", "Jobicy")

# LM Studio
LMS_EXE = Path.home() / ".lmstudio" / "bin" / "lms.exe"
LM_PORT = 1234
LM_URL = f"http://localhost:{LM_PORT}/v1"
MODEL = "mistralai/ministral-3-8b"
MODEL_ID = "job-finder"  # identifier of the loaded model in LM Studio and in the API
CONTEXT_LENGTH = 8192
MAX_DESCRIPTION_CHARS = 8000

# Sources
HTTP_TIMEOUT = 30
JUNIORGURU_URL = "https://junior.guru/api/jobs.csv"
HIMALAYAS_URL = "https://himalayas.app/jobs/api/search"
# The search word (the main skill) and the seniority (the levels) come from the settings
HIMALAYAS_PARAMS = {"country": "CZ", "sort": "recent"}
HIMALAYAS_SENIORITY = {"intern": ["Entry-level"], "junior": ["Entry-level", "Mid-level"],
                       "mid": ["Mid-level", "Senior"], "senior": ["Senior"], "lead": ["Senior", "Manager"]}
# Skills whose dictionary name is not a good search word
HIMALAYAS_QUERY = {"C#/.NET": "C#", "C/C++": "C++"}
HIMALAYAS_MAX_PAGES = 10  # 20 jobs per page
JOBICY_URL = "https://jobicy.com/api/v2/remote-jobs"
JOBICY_PARAMS = {"count": 50, "geo": "czechia", "industry": "dev"}
WORKINGNOMADS_URL = "https://www.workingnomads.com/api/exposed_jobs/"
