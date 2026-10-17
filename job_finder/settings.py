"""Everything personal about the user: CV, skills, where and what to search, level, languages, thresholds
(spec section 15). Stored as one JSON row in the database; filled by the first-run wizard."""
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from job_finder import db, insights

# junior.guru regions the app can filter by
CITIES = ["Praha", "Brno", "Ostrava", "Plzeň", "Olomouc", "Liberec", "České Budějovice", "Hradec Králové",
          "Pardubice", "Zlín", "Jihlava", "Karlovy Vary", "Ústí nad Labem"]
LEVELS = ["junior", "mid"]
LANGUAGE_LEVELS = ["none", "A1", "A2", "B1", "B2", "C1", "C2"]
# Changing any of these changes the scoring rules or the CV, so every job is scored again
SCORING_FIELDS = ("cv_path", "city", "remote", "level", "english", "czech", "needs_permit")
# Dictionary groups that are not skills you list in a CV's skills
NOT_SKILLS = {"Experience 2+ years", "Czech", "German", "Other languages", "English C1+", "Degree",
              "Domain knowledge", "Soft skills", "Project management"}


@dataclass
class Settings:
    cv_path: str = ""
    skills: list[str] = field(default_factory=list)
    city: str = "Praha"
    remote: bool = True
    keywords: list[str] = field(default_factory=list)
    level: str = "junior"
    english: str = ""                 # one of LANGUAGE_LEVELS; "" = not answered yet
    czech: str = ""
    needs_permit: bool | None = None  # None = not answered yet
    min_score: int = 5
    stale_days: int = 14
    stale_job_days: int = 21


class CvError(Exception):
    """The CV file can't be read; the message says why, in plain words."""


def load() -> Settings | None:
    """The saved settings, or None before the first-run wizard was finished."""
    data = db.get_settings()
    if data is None:
        return None
    known = {f.name for f in fields(Settings)}
    return Settings(**{key: value for key, value in data.items() if key in known})


def save(s: Settings) -> None:
    db.put_settings(asdict(s))


def missing(s: Settings) -> list[str]:
    """Required fields that are still empty, in the order the wizard asks for them."""
    empty = {
        "cv_path": not s.cv_path,
        "skills": not s.skills,
        "keywords": not 1 <= len(s.keywords) <= 3,
        "english": s.english not in LANGUAGE_LEVELS,
        "czech": s.czech not in LANGUAGE_LEVELS,
        "needs_permit": s.needs_permit is None,
    }
    return [name for name, is_empty in empty.items() if is_empty]


def scoring_changed(old: Settings, new: Settings) -> bool:
    return any(getattr(old, name) != getattr(new, name) for name in SCORING_FIELDS)


def read_cv_text(path: str) -> str:
    """Text of the CV: Markdown and text files as they are, PDF page by page."""
    file = Path(path)
    if not file.is_file():
        raise CvError(f"file not found: {path}")
    if file.suffix.lower() == ".pdf":
        try:
            from pypdf import PdfReader
            text = "\n".join(page.extract_text() or "" for page in PdfReader(str(file)).pages)
        except Exception as error:  # pypdf raises many kinds of errors for broken files
            raise CvError(f"can't read the PDF ({error.__class__.__name__})") from error
    else:
        text = file.read_text(encoding="utf-8", errors="replace")
    if not text.strip():
        raise CvError("no text found in the file (a scanned PDF?)")
    return text


def detect_skills(text: str) -> list[str]:
    """Skills mentioned in a CV, by the Insights dictionary, in dictionary order."""
    found = insights.find(text) - NOT_SKILLS
    return [name for name in insights.REQUIREMENTS if name in found]


def initial(cv: Path) -> Settings:
    """Wizard prefill: an existing CV file and the skills found in it; everything else is asked."""
    if not cv.is_file():
        return Settings()
    try:
        skills = detect_skills(read_cv_text(str(cv)))
    except CvError:
        skills = []
    return Settings(cv_path=str(cv), skills=skills)
