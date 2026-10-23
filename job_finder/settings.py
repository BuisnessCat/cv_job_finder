"""Everything personal about the user: CV, skills, where and what to search, level, languages, thresholds
(spec section 15). Stored as one JSON row in the database; filled by the first-run wizard."""
import os
import re
from dataclasses import asdict, dataclass, field, fields, replace
from pathlib import Path

from job_finder import config, db, insights

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
# Names the job dictionary matches loosely that are everyday words in a CV: here they count only when written like
# the skill ("Go", not "go deeper"; "C" in a list, not "grade C."; not "Spring 2024", "spring semester",
# "Mobile phone: +420" or "the rest")
_WORD = r"(?<![\w#+.])(?:{})(?![\w#+])"
CV_PATTERNS = {
    # A letter counts in a list: before , / ) | ; • or at the end of a line
    "C/C++": re.compile(_WORD.format(r"C(?=\s*(?:[,/)|;•]|$))|[Cc]\+\+(?:\d\d)?"), re.MULTILINE),  # also C++17
    "Go": re.compile(_WORD.format(r"Go(?!-)|Golang|golang")),
    "R": re.compile(_WORD.format(r"R(?=\s*(?:[,/)|;•]|$))|R programming|RStudio"), re.MULTILINE),
    "Spring": re.compile(_WORD.format(r"Spring(?!\s+(?:(?:19|20)\d\d|semester|term|break))|spring boot")),
    "Mobile": re.compile(_WORD.format(r"android|ios|mobile(?!\s*(?:phone|number|no\.?)?\s*[:+(\d])|flutter"
                                      r"|react native"), re.IGNORECASE),
    "REST API": re.compile(_WORD.format(r"REST(?:ful)?|(?i:rest\s+apis?|restful|apis?|web\s+services?)")),
}


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
    model: str = ""  # the AI model; "" = the one that fits the graphics card (hardware.default_model)
    min_score: int = 5
    stale_days: int = 14
    stale_job_days: int = 21
    cv_stamp: str = ""  # the chosen CV file (path, time, size) when its text was last copied; "missing" if gone


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
    """Whether the scoring rules or the CV change. Languages count in order (the rules list them so); the CV by the
    file it points to, not by how its path is spelled."""
    for name in SCORING_FIELDS:
        before, after = getattr(old, name), getattr(new, name)
        if name == "languages":
            before, after = list(before.items()), list(after.items())
        elif name == "cv_path":
            before, after = (os.path.normcase(os.path.abspath(path)) for path in (before, after))
        if before != after:
            return True
    return False


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


def file_stamp(path: str) -> str | None:
    """The file's path, modification time and size: it changes when the file is edited; None if there is none."""
    try:
        stat = Path(path).stat()
    except OSError:
        return None
    return f"{os.path.normcase(os.path.abspath(path))}|{stat.st_mtime_ns}|{stat.st_size}"


def saved_copy() -> str:
    """The app's copy of the CV, "" if there is none yet."""
    try:
        return config.CV_COPY.read_text(encoding="utf-8")
    except OSError:
        return ""


def cv_text(s: Settings) -> str:
    """The CV the app scores with: its saved copy, so a moved, deleted or busy file (a PDF open elsewhere, a synced
    folder) doesn't stop it; the chosen file itself only before the first copy."""
    text = saved_copy()
    return text if text.strip() else read_cv_text(s.cv_path)


def store_cv(s: Settings, text: str) -> Settings:
    """Save the CV's text as the app's copy; the settings remember which version of the file it is."""
    config.CV_COPY.parent.mkdir(parents=True, exist_ok=True)
    config.CV_COPY.write_text(text, encoding="utf-8", newline="\n")
    return replace(s, cv_stamp=file_stamp(s.cv_path) or "")


def sync_cv(s: Settings) -> tuple[Settings, str]:
    """Bring the copy up to date with the chosen file (at the start of every refresh): read the file only if it
    changed. Returns the settings and a note for the status line, said once ("" if there is nothing to say).
    CvError: neither the file nor a copy can be read."""
    stamp = file_stamp(s.cv_path)
    has_copy = config.CV_COPY.is_file()
    if has_copy and stamp == s.cv_stamp:
        return s, ""
    if stamp is None:
        if not has_copy:
            raise CvError(f"file not found: {s.cv_path}")
        note = "" if s.cv_stamp == "missing" else "your CV file isn't found, so the saved copy is used"
        s = replace(s, cv_stamp="missing")
        save(s)
        return s, note
    try:
        text = read_cv_text(s.cv_path)
    except CvError as error:
        if not has_copy:
            raise
        s = replace(s, cv_stamp=stamp)  # this version of the file is not read again
        save(s)
        return s, f"can't read your CV file ({error}), so the saved copy is used"
    changed = has_copy and config.CV_COPY.read_text(encoding="utf-8") != text
    s = store_cv(s, text)
    save(s)
    return s, "your CV changed, so all jobs were scored again" if changed else ""


def _cv_mentions(name: str, text: str) -> int:
    """How many times a CV mentions a skill from the dictionary (stricter for everyday words, see CV_PATTERNS)."""
    pattern = CV_PATTERNS.get(name)
    return len(pattern.findall(text)) if pattern else insights.mentions(name, text)


def detect_skills(text: str) -> list[str]:
    """Skills mentioned in a CV, by the Insights dictionary, in dictionary order."""
    return [name for name in insights.REQUIREMENTS if name not in NOT_SKILLS and _cv_mentions(name, text)]


def skill_name(name: str) -> str:
    """A typed skill as the dictionary writes it ("python" -> "Python"); any other skill as typed."""
    name = name.strip()
    return next((known for known in insights.REQUIREMENTS if known.lower() == name.lower()), name)


def language_name(name: str) -> str:
    """A typed language as the list writes it ("english" -> "English"); any other with a capital letter."""
    name = name.strip()
    return next((known for known in LANGUAGES if known.lower() == name.lower()), name[:1].upper() + name[1:])


def guess_main_skill(skills: list[str], cv_text: str) -> str:
    """The programming language among the skills that the CV mentions most; without one, the first skill."""
    languages = [name for name in skills if name in PROGRAMMING_LANGUAGES]
    if languages:
        return max(languages, key=lambda name: _cv_mentions(name, cv_text))  # a tie: the earlier one
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
