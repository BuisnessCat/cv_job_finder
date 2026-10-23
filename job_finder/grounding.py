"""Facts and verdicts (spec sections 20.3, 21). The program finds the technologies an ad names (the skills
dictionary, strict patterns) and hands them to the model with the ad; the model takes the facts out of the ad; the
program compares them with the candidate's profile and decides: Strong fit, Worth a try, Stretch, Out of reach or
Other area. The model doesn't judge: a small local model reads well and judges badly."""
import re

from job_finder import insights, settings
from job_finder.settings import EDUCATION, EXPERIENCE, LEVELS, Settings
from job_finder.sources import Job, juniorguru_place

FAMILIES = [{"JavaScript", "TypeScript"}]  # in the main-language check one counts for the other
LANGUAGES = set(settings.PROGRAMMING_LANGUAGES)

STRONG, WORTH, STRETCH, OUT, OTHER = "Strong fit", "Worth a try", "Stretch", "Out of reach", "Other area"
MATCH = {"yes": 1.0, "similar": 0.7, "no": 0.0}  # the share of a skill's weight the candidate gets
WEIGHTS = {True: 2, False: 0.5}  # a must-have, a nice-to-have (optional by its name: it weighs a quarter)
DEGREES = ["none", "bachelor", "master", "phd"]  # the lowest first
DEGREE_NAMES = {"bachelor": "Bachelor's degree", "master": "Master's degree", "phd": "PhD"}
EDUCATION_RANK = {"none": 0, "studying": 0.5, "bachelor": 1, "master": 2, "phd": 3}
# A degree counts only if the ad itself names one of its level: the model may add one the ad doesn't ask for
DEGREE_WORDS = {
    "phd": r"ph\.?\s?d|doctor\w*|doktor\w*",
    "master": r"master\w*|\bmsc\b|m\.sc|\bms\b|\bm\.s\.|magist\w*|\bing\.|inženýr\w*|postgraduate|graduate degree",
    "bachelor": r"bachelor\w*|\bbsc\b|b\.sc|\bbs\b|bakal\w*|degree|universit\w*|college|vysokoškol\w*|\bvš\b",
}
EXPERIENCE_YEARS = {"none": 0, "under1": 0.5, "1-2": 2, "3-5": 5, "5plus": 10}
LEVEL_RANK = {level: rank for rank, level in enumerate(LEVELS)}  # intern 0 … lead 4
# The level a title names, outside its parentheses ("Junior Developer (Mid/Senior welcome)" is junior)
TITLE_LEVELS = [(r"intern\w*|trainee|praktikant\w*|stáž\w*|student\w*", 0), (r"junior|jr", 1),
                (r"medior|mid-level|mid|regular", 2), (r"senior|sr", 3),
                (r"lead|principal|staff|head of|director|architect|vice president|vp|chief", 4)]
RANKS = {"A1": 1, "A2": 2, "B1": 3, "B2": 4, "C1": 5, "C2": 6, "NATIVE": 7}
FINE_PLACES = r"europe\w*|\beu\b|\bcet\b|\bcest\b|czech\w*|česk\w*|worldwide|anywhere|global\w*|emea"
YEARS = re.compile(r"(\d+)\s*\+?\s*(?:[-–]\s*\d+\s*)?(?:years?|yrs|let\b|roky|roků|rok\b)", re.IGNORECASE)
SOFT_SKILLS = re.compile(
    r"communicat\w*|teamwork|team player|collaborat\w*|leadership|mentoring|responsib\w*|self[- ]?organi[sz]\w*|"
    r"proactiv\w*|curio\w*|motivat\w*|problem[- ]solving|analytical\s+(?:thinking|mindset|skills)|detail[- ]oriented|"
    r"attention to detail|willing\w*|eager\w*|learn\w*\s+(?:ability|quickly|fast)|fast learn\w*|ambiguity|"
    r"independen\w*|sharing knowledge|interest in|passion\w*|attitude|flexib\w*|creativ\w*|soft skills|mindset",
    re.IGNORECASE)

# Czech puts endings on technology names ("v Pythonu", "s Gitem", "Linuxovým shellem"), and the dictionary looks
# for whole words: such forms are turned back into the name first
_PLAIN = sorted({alias for name, aliases in insights.REQUIREMENTS.items() if name not in settings.NOT_SKILLS
                 for alias in aliases if re.fullmatch(r"[a-z]{3,}", alias)}, key=len, reverse=True)
_CZECH_ENDINGS = re.compile(r"(?<![\w#+.])(" + "|".join(_PLAIN) + r")(?:u|em|a|y|ou|ech|ům|ách|ov\w*)(?![\w#+])",
                            re.IGNORECASE)
_CZECH_FORMS = [(re.compile(r"(?<![\w#+.])jav(?:ě|ou|u|y)(?![\w#+])", re.IGNORECASE), "Java"),
                (re.compile(r"(?<![\w#+.])céč(?:ko|ka|ku|kem)(?![\w#+])", re.IGNORECASE), "C++")]


def _base_forms(text: str) -> str:
    text = _CZECH_ENDINGS.sub(r"\1", text)
    for pattern, name in _CZECH_FORMS:
        text = pattern.sub(name, text)
    return text


def technologies(text: str) -> set[str]:
    """Dictionary technologies written in a text, also in Czech forms: "C#" is not "C", "go to market" is not Go;
    not experience, spoken languages or a degree."""
    return set(settings.detect_skills(_base_forms(text)))


def cv_technologies(cv_text: str) -> set[str]:
    """The candidate's technologies: from the CV, which the model reads too (so its key covers them)."""
    return technologies(cv_text)


def _ordered(names: set[str]) -> str:
    """Names in dictionary order (languages first), comma-separated."""
    return ", ".join(name for name in insights.REQUIREMENTS if name in names) or "none"


def facts(job: Job, known: set[str]) -> str:
    """What the program found in the ad, for the model: named technologies, which are in the CV and which not."""
    named = technologies(f"{job.title}\n{job.description}")
    if not named:
        return ("Technologies this ad names (found by a program): no known technologies. Do not add technologies "
                "it does not name.")
    return (f"Technologies this ad names (found by a program, reliable): {_ordered(named)}.\n"
            f"Of them in the candidate's CV: {_ordered(named & known)}. Not in the CV: {_ordered(named - known)}.")


def _with_families(names: set[str]) -> set[str]:
    return names.union(*(family for family in FAMILIES if family & names))


def _core(skill: str) -> str:
    """A skill without the model's note about the CV: "Django (has FastAPI)" is about Django."""
    return re.sub(r"\((?:has|you have|candidate has)\b[^)]*\)", " ", skill, flags=re.IGNORECASE)


def _clean(text) -> str:
    return re.sub(r"\*\*|__|`", "", str(text or "")).strip()  # the model sometimes writes Markdown


def _skills(items, required: bool, named: set[str], known: set[str], mine: set[str]) -> list[dict]:
    """The model's skills kept to what the ad and the CV say: one naming only technologies the ad doesn't name, a
    soft skill or years of experience is dropped; another programming language is never had (C# is not C++); a
    technology the CV doesn't show is at best similar."""
    kept = []
    for item in items if isinstance(items, list) else []:
        text = _clean(item.get("skill")) if isinstance(item, dict) else ""
        if not text:
            continue
        found = technologies(_core(text))
        if (found and not found & named) or YEARS.search(text) or (not found and SOFT_SKILLS.search(text)):
            continue
        match = item.get("match") if item.get("match") in MATCH else "no"
        if match != "no" and (found & LANGUAGES & named) - mine:
            match = "no"
        elif match == "yes" and found and not found & known:
            match = "similar"
        kept.append({"skill": text, "required": required, "match": match})
    return kept


def _condition(name: str, ok: bool, detail: str, reason: str = "") -> dict:
    return {"name": name, "ok": ok, "detail": detail, "reason": reason}


def _degree(extraction: dict, ad: str, s: Settings) -> dict:
    need = extraction.get("degree") if extraction.get("degree") in DEGREES else "none"
    while need != "none" and not re.search(DEGREE_WORDS[need], ad, re.IGNORECASE):
        need = DEGREES[DEGREES.index(need) - 1]  # not in the ad: at most the level it does name
    if need == "none":
        return _condition("Degree", True, "Not asked")
    name = DEGREE_NAMES[need]
    welcome = bool(extraction.get("students_welcome"))
    if EDUCATION_RANK.get(s.education, 0) >= DEGREES.index(need) or (
            welcome and need == "bachelor" and s.education == "studying"):
        return _condition("Degree", True, f"{name}, students welcome" if welcome else name)
    return _condition("Degree", False, f"{name} required · you: {EDUCATION.get(s.education, '').lower()}",
                      f"Requires a {name}")


def _experience(extraction: dict, ad: str, s: Settings) -> dict:
    try:
        need = max(0, min(int(extraction.get("min_years") or 0), 30))
    except (TypeError, ValueError):
        need = 0
    if need and not YEARS.search(ad):
        need = 0  # no years written in the ad: the model's guess
    if not need:
        return _condition("Experience", True, "Not asked")
    if need <= EXPERIENCE_YEARS.get(s.experience, 0) + 1:  # a year short is still worth a try
        return _condition("Experience", True, f"{need}+ years")
    return _condition("Experience", False, f"{need}+ years · you: {EXPERIENCE.get(s.experience, '').lower()}",
                      f"Requires {need}+ years of experience")


def _title_rank(title: str) -> int | None:
    plain = re.sub(r"\([^)]*\)|\[[^\]]*\]", " ", title)
    ranks = [rank for pattern, rank in TITLE_LEVELS if re.search(rf"\b(?:{pattern})\b", plain, re.IGNORECASE)]
    return min(ranks) if ranks else None


def _level(extraction: dict, job: Job, s: Settings) -> dict:
    title = _title_rank(job.title)
    rank = title if title is not None else LEVEL_RANK.get(extraction.get("seniority"))  # the title is the ad's word
    if rank is None:
        return _condition("Level", True, "Not stated")
    levels = [level for level in LEVELS if level in s.levels] or ["junior"]
    label = LEVELS[rank].capitalize()
    if rank <= LEVEL_RANK[levels[-1]] + 1:  # one step up is worth a try
        return _condition("Level", True, label)
    return _condition("Level", False, f"{label} · you: {', '.join(levels)}", f"{label} role")


def _language(extraction: dict, s: Settings) -> dict:
    required = [item for item in extraction.get("languages") or [] if isinstance(item, dict) and item.get("language")]
    if not required:
        return _condition("Language", True, "Not asked")
    texts, missing = [], []
    for item in required:
        name = settings.language_name(str(item["language"]))
        level = str(item.get("level") or "").strip()
        need = RANKS.get(level.upper())
        text = f"{name} {level}" if need else name
        have = next((lvl for known, lvl in s.languages.items() if known.lower() == name.lower()), None)
        texts.append(text)
        if have is None or (need and RANKS.get(have.upper(), 0) < need - 1):  # one level short is worth a try
            missing.append((text, have))
    if not missing:
        return _condition("Language", True, ", ".join(texts))
    text, have = missing[0]
    return _condition("Language", False, f"{text} · you: {have or 'not listed'}", f"Requires {text}")


def _location(extraction: dict, s: Settings) -> dict:
    workplace = extraction.get("workplace")
    place = _clean(extraction.get("place"))
    own = any(re.search(re.escape(city), place, re.IGNORECASE) for city in {s.city, juniorguru_place(s.city)})
    fine = own or not place or re.search(FINE_PLACES, place, re.IGNORECASE)
    if workplace == "remote":
        if not s.remote:
            return _condition("Location", False, f"Remote · you want to work in {s.city}", "A remote-only job")
        if not fine:
            return _condition("Location", False, f"Remote, {place}", f"Remote only for {place}")
        return _condition("Location", True, f"Remote, {place}" if place else "Remote")
    if workplace in ("office", "hybrid"):
        if not fine:
            return _condition("Location", False, f"{place}, {workplace}", f"An office in {place}")
        return _condition("Location", True, f"{place}, {workplace}" if place else workplace.capitalize())
    return _condition("Location", True, place or "Not stated")


def _area(extraction: dict, s: Settings) -> dict:
    """The job fits if one of its areas (one or two: a job between Embedded and Backend) is the candidate's."""
    areas = [area for area in extraction.get("areas") or [extraction.get("area")] if area] or ["Other IT"]
    if all(area == "Not IT" for area in areas):
        return _condition("Area", False, "Not an IT job", "Not an IT job")
    wanted = set(s.areas)
    if "Full-stack" in wanted:
        wanted |= {"Backend", "Frontend"}
    if wanted & {"Backend", "Frontend"}:
        wanted.add("Full-stack")
    shown = ", ".join(areas)
    if areas == ["Other IT"] or any(area in wanted for area in areas):  # "Other IT" next to an area is no wildcard
        return _condition("Area", True, shown)
    return _condition("Area", False, f"{shown} · not one of your areas", f"{areas[0]} isn't one of your areas")


def _foreign_languages(job: Job, named: set[str], mine: set[str]) -> set[str]:
    """The job's programming languages when the CV has none of them (and has some language): those of the title,
    else all the ad names. Read from the ad itself: the model may list the CV's skills instead of the ad's, or
    file "C#, Java or C++" under nice-to-haves."""
    if not mine:
        return set()
    languages = (technologies(job.title) & LANGUAGES) or (named & LANGUAGES)
    return set() if not languages or languages & mine else languages


def _title_skills(must: list[dict], nice: list[dict], job: Job, known: set[str]) -> list[dict]:
    """Technologies in the title are the core of the job: the ones the model left out become must-haves."""
    listed = set().union(*(technologies(_core(item["skill"])) for item in must + nice))
    missing = technologies(job.title) - listed
    return [{"skill": name, "required": True, "match": "yes" if name in known else "no"}
            for name in insights.REQUIREMENTS if name in missing]


def verdict(extraction: dict, job: Job, known: set[str], s: Settings) -> dict:
    """The program's verdict on one job (spec section 21.3) from the model's facts, the ad and the profile."""
    ad = f"{job.title}\n{job.description}"
    named = technologies(ad)
    mine = _with_families(known & LANGUAGES)
    must = _skills(extraction.get("must_have"), True, named, known, mine)
    nice = _skills(extraction.get("nice_to_have"), False, named, known, mine)
    must += _title_skills(must, nice, job, known)
    conditions = [_degree(extraction, ad, s), _experience(extraction, ad, s), _level(extraction, job, s),
                  _language(extraction, s), _location(extraction, s), _area(extraction, s)]
    failed = [c for c in conditions[:-1] if not c["ok"]]
    points = sum(WEIGHTS[i["required"]] * MATCH[i["match"]] for i in must + nice)
    total = sum(WEIGHTS[i["required"]] for i in must + nice)
    share = points / total if total else 0.0
    must_share = sum(MATCH[i["match"]] for i in must) / len(must) if must else 0.0
    count = f"{sum(i['match'] != 'no' for i in must)} of {len(must)} must-haves"
    if nice:
        count += f" · {sum(i['match'] != 'no' for i in nice)} of {len(nice)} nice-to-haves"
    foreign = _foreign_languages(job, named, mine)
    if failed:
        name, score, reason = OUT, 2 if len(failed) == 1 else 1, failed[0]["reason"]
    elif not conditions[-1]["ok"]:
        name, score, reason = OTHER, 3, conditions[-1]["reason"]
    elif foreign:
        name, score, reason = STRETCH, 4, f"Main language {_ordered(foreign)} isn't in your CV"
    elif not must:
        name, score, reason = WORTH, 6, "The ad names few concrete requirements: read it before applying"
    elif share >= 0.8 and must_share >= 0.75:
        name, score, reason = STRONG, 10 if share >= 1 else 9 if share >= 0.9 else 8, f"{count} · all conditions met"
    elif share >= 0.5:
        name, score, reason = WORTH, 7 if share >= 0.65 else 6, count
    else:
        name, score, reason = STRETCH, 5 if share >= 0.3 else 4, count
    about = _clean(extraction.get("about"))
    return {
        "verdict": name, "score": score, "reason": reason, "conditions": conditions, "must": must, "nice": nice,
        "about": about, "extraction": extraction,
        # What the Insights tab and older parts of the app read
        "summary": about, "have": [i["skill"] for i in must + nice if i["match"] != "no"],
        "missing": [i["skill"] for i in must + nice if i["match"] == "no"],
        "risks": [c["reason"] for c in conditions if not c["ok"]],
    }
