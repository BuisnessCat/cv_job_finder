"""Everything personal about the user: CV, skills, where and what to search, level, languages, thresholds
(spec section 15). Stored as one JSON row in the database; filled by the first-run wizard."""
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from job_finder import db, insights

# junior.guru regions the app can filter by
CITIES = ["Praha", "Brno", "Ostrava", "Plzeň", "Olomouc", "Liberec", "České Budějovice", "Hradec Králové",
          "Pardubice", "Zlín", "Jihlava", "Karlovy Vary", "Ústí nad Labem"]
LEVELS = ["intern", "junior", "mid", "senior", "lead"]
LANGUAGE_LEVELS = ["A1", "A2", "B1", "B2", "C1", "C2", "Native"]
# Suggestions in the language list; any other language can be typed in
LANGUAGES = ["English", "Czech", "Slovak", "German", "Polish", "Russian", "Ukrainian", "French", "Spanish", "Italian"]
# The "Languages" group of the dictionary: the main skill is guessed among these
PROGRAMMING_LANGUAGES = ["Python", "Java", "C#/.NET", "C/C++", "Go", "Rust", "JavaScript", "TypeScript", "PHP",
                         "Ruby", "Kotlin", "Swift", "Scala", "R"]
# Changing any of these changes the scoring rules or the CV, so every job is scored again
SCORING_FIELDS = ("cv_path", "city", "remote", "levels", "languages")
# Dictionary groups that are not skills you list in a CV's skills
NOT_SKILLS = {"Experience 2+ years", "Czech", "German", "Other languages", "English C1+", "Degree",
              "Domain knowledge", "Soft skills", "Project management"}


@dataclass
class Settings:
    cv_path: str = ""
    skills: list[str] = field(default_factory=list)
    main_skill: str = ""  # one of the skills: searched for on the remote job sites
    city: str = "Praha"
    remote: bool = True
    levels: list[str] = field(default_factory=lambda: ["junior"])  # one or more of LEVELS
    # language -> one of LANGUAGE_LEVELS; "" = the level is not chosen yet
    languages: dict[str, str] = field(default_factory=lambda: {"English": ""})
    min_score: int = 5
    stale_days: int = 14
    stale_job_days: int = 21


class CvError(Exception):
    """The CV file can't be read; the message says why, in plain words."""


def load() -> Settings | None:
    """The saved settings, or None before the first-run wizard was finished; fields of older versions are dropped."""
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
        "main_skill": s.main_skill not in s.skills,
        "levels": not s.levels or any(level not in LEVELS for level in s.levels),
        "languages": not s.languages or any(not name.strip() or level not in LANGUAGE_LEVELS
                                            for name, level in s.languages.items()),
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


def guess_main_skill(skills: list[str], cv_text: str) -> str:
    """The programming language among the skills that the CV mentions most; without one, the first skill."""
    languages = [name for name in skills if name in PROGRAMMING_LANGUAGES]
    if languages:
        return max(languages, key=lambda name: insights.mentions(name, cv_text))  # a tie: the earlier one
    return skills[0] if skills else ""


def initial(cv: Path) -> Settings:
    """Wizard prefill: an existing CV file, the skills found in it and a guess of the main one; the rest is asked."""
    if not cv.is_file():
        return Settings()
    try:
        text = read_cv_text(str(cv))
    except CvError:
        return Settings(cv_path=str(cv))
    skills = detect_skills(text)
    return Settings(cv_path=str(cv), skills=skills, main_skill=guess_main_skill(skills, text))
