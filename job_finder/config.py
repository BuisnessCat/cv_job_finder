"""App settings."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FROZEN = getattr(sys, "frozen", False)  # the installed app (built with PyInstaller), not the sources
APP_DIR = Path(getattr(sys, "_MEIPASS", ROOT))  # where the app's own files are (the icon)


def data_dir(frozen: bool, environ) -> Path:
    """Where the database, log and cache live: the project folder for the sources, the user's app data folder for
    the installed app (updating or removing the app keeps them); JOB_FINDER_DATA overrides both (for checks)."""
    if environ.get("JOB_FINDER_DATA"):
        return Path(environ["JOB_FINDER_DATA"])
    if frozen:
        return Path(environ.get("LOCALAPPDATA") or Path.home()) / "Job Finder"
    return ROOT


def lock_path(environ) -> Path:
    """One "already open" lock per user: the sources and the installed app never run at once with one model."""
    if environ.get("JOB_FINDER_DATA"):
        return Path(environ["JOB_FINDER_DATA"]) / "job_finder.lock"
    return Path(environ.get("LOCALAPPDATA") or Path.home()) / "Job Finder" / "job_finder.lock"


DATA_DIR = data_dir(FROZEN, os.environ)
LOCK_PATH = lock_path(os.environ)
CV_PATH = DATA_DIR / "master_cv.md"  # if it exists, the first-run wizard offers it as the CV
DB_PATH = DATA_DIR / "jobs.db"
LOG_PATH = DATA_DIR / "job_finder.log"
ICON_PATH = APP_DIR / "job_finder" / "icon.ico"

# This version; bump it together with the GitHub release tag (v1.1.0 = "1.1.0"). The installed app compares it with
# the latest release and offers the new one
VERSION = "1.1.0"
RELEASES_API = "https://api.github.com/repos/BuisnessCat/cv_job_finder/releases/latest"
RELEASES_PAGE = "https://github.com/BuisnessCat/cv_job_finder/releases/latest"

# While the app runs (also hidden in the tray) it looks for new jobs this often
AUTO_REFRESH_HOURS = 3

# A Windows notification tells about new jobs scored at least this (or the minimum score, if higher)
NOTIFY_SCORE = 7

# Jobs older than this by the site's date are not scored: the default 30-day freshness filter hides them anyway
OLD_JOB_DAYS = 30

# Sources that return their whole list: a job missing from them was probably taken down. Not junior.guru: it
# only shows jobs from other sites (jobs.cz, LinkedIn, StartupJobs) and drops some while they are still open
FULL_LIST_SOURCES = ("Jobicy", "Úřad práce")

# A job its source stopped listing stays in the found list this many days, muted, with a note to check the link
GONE_DAYS = 7

# Titles there are profession classes ("Vývojáři softwaru"): the same company and title can be a different job
NO_TWIN_SOURCES = ("Úřad práce",)

# LM Studio
LMS_HOME = Path.home() / ".lmstudio"
LMS_EXE = LMS_HOME / "bin" / "lms.exe"
LM_PORT = 1234
LM_URL = f"http://localhost:{LM_PORT}/v1"
MODEL = "mistralai/ministral-3-8b"  # graphics cards with 8 GB and more
SMALL_MODEL = "mistralai/ministral-3-3b"  # smaller cards: weaker, the scores may differ a bit
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
# Dictionary names that the general rule (the part before "/", without " (any)") would turn into a poor search word
HIMALAYAS_QUERY = {"C#/.NET": "C#", "C/C++": "C++", "CI/CD": "CI/CD"}
HIMALAYAS_MAX_PAGES = 10  # 20 jobs per page
# Úřad práce ČR: every vacancy registered in Czechia, updated daily (~190 MB); the IT selection is kept in UP_CACHE
UP_URL = "https://data.mpsv.cz/od/soubory/volna-mista/volna-mista.json"
UP_CACHE = DATA_DIR / "cache" / "uradprace.json"
UP_DETAIL_URL = "https://up.gov.cz/volna-mista-v-cr#/volna-mista-detail/{}"
REMOTEOK_URL = "https://remoteok.com/api"  # terms: link to the job on Remote OK and name it as the source
WWR_URL = "https://weworkremotely.com/categories/remote-{}-jobs.rss"
WWR_CATEGORIES = ("programming", "full-stack-programming", "back-end-programming", "front-end-programming",
                  "devops-sysadmin")
JOBICY_URL = "https://jobicy.com/api/v2/remote-jobs"
JOBICY_PARAMS = {"count": 50, "geo": "czechia", "industry": "dev"}
WORKINGNOMADS_URL = "https://www.workingnomads.com/api/exposed_jobs/"
