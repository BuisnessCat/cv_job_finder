"""Technologies an ad really names, found by the program (the skills dictionary, strict patterns), not by the model:
facts given to the model with the ad; then the score, counted by the program from the model's list of requirements
and checked against the ad and the CV (spec sections 20.3, 20.4)."""
import math
import re

from job_finder import insights, settings
from job_finder.settings import LEVELS, Settings
from job_finder.sources import Job

FAMILIES = [{"JavaScript", "TypeScript"}]  # in the main-language check one counts for the other
LANGUAGES = set(settings.PROGRAMMING_LANGUAGES)

# How the score is counted (spec section 20.4)
WEIGHTS = {True: 2, False: 1}  # a must-have, a nice-to-have
MATCH = {"yes": 1.0, "similar": 0.7, "no": 0.0}  # the share of the weight the candidate gets
# Ceilings of blockers, when the program confirms them: years of experience above the level, a spoken language
# above the settings (5: still in the list, it can be worth a try), an office or remote region out of reach,
# citizenship or residency
CAPS = {"experience": 4, "spoken language": 5, "location": 3, "residency": 2}
LANGUAGE_CAP = 3  # the title names a programming language the CV doesn't have
MUST_LANGUAGE_CAP = 4  # a must-have programming language the CV doesn't have
QUOTE_SHARE = 0.6  # of a blocker's longer words that must be in the ad
FEW_REQUIREMENTS, FEW_CAP = 3, 7  # fewer requirements than this: too little to be sure of a high score
NO_REQUIREMENTS_SCORE = 5


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
        return ("Technologies this ad names (found by a program): no known technologies. Judge the ad by its role, "
                "level and language of work; do not add technologies it does not name.")
    return (f"Technologies this ad names (found by a program, reliable): {_ordered(named)}.\n"
            f"Of them in the candidate's CV: {_ordered(named & known)}. Not in the CV: {_ordered(named - known)}.")


def _with_families(names: set[str]) -> set[str]:
    return names.union(*(family for family in FAMILIES if family & names))


# Spoken languages and their levels, as an ad or the model writes them (English and Czech words)
SPOKEN = {"English": r"english|angli\w*", "Czech": r"czech(?!\s+republic)|češtin\w*|česk\w+\s+jazyk\w*",
          "Slovak": r"slovak|slovenštin\w*", "German": r"german|deutsch|němčin\w*|německ\w+\s+jazyk\w*",
          "Polish": r"polish|polštin\w*", "Russian": r"russian|ruštin\w*", "Ukrainian": r"ukrainian|ukrajinštin\w*",
          "French": r"french|francouzštin\w*", "Spanish": r"spanish|španělštin\w*", "Italian": r"italian|italštin\w*"}
RANKS = {"A1": 1, "A2": 2, "B1": 3, "B2": 4, "C1": 5, "C2": 6, "Native": 7}
LEVEL_WORDS = [  # checked in order: "středně pokročilá" (intermediate) before "pokročilá" (advanced)
    (r"native|mother tongue|rodil\w*", 7), (r"\bc2\b", 6), (r"\bb2\b|upper[- ]intermediate", 4),
    (r"\bb1\b|(?<!upper )(?<!upper-)intermediate|středně\s+pokročil\w*|komunikativn\w*|communicative|conversational", 3),
    (r"\bc1\b|fluent\w*|advanced|proficien\w*|plynul\w*|pokročil\w*", 5), (r"\ba2\b|basic|elementary|základ\w*", 2),
    (r"\ba1\b", 1)]
YEARS = re.compile(r"(\d+)\s*\+?\s*(?:[-–]\s*\d+\s*)?(?:years?|yrs|let\b|roky|roků|rok\b)", re.IGNORECASE)
MIN_YEARS = {"intern": 1, "junior": 2, "mid": 5, "senior": 10, "lead": 99}  # of experience that rule a level out
ABOVE = {"intern": r"senior|medior|mid-level|lead|principal|staff|head of|architect",  # seniority above a level
         "junior": r"senior|medior|mid-level|lead|principal|staff|head of|architect",
         "mid": r"lead|principal|head of|director", "senior": r"director|vice president|executive|head of",
         "lead": r"director|vice president|executive"}
FINE_PLACES = r"europe\w*|\beu\b|\bcet\b|\bcest\b|czech\w*|česk\w*|prague|praha|worldwide|anywhere|global\w*|emea"
RESIDENCY = r"citizen\w*|residen\w*|work permit|security clearance|green card|visa|občan\w*|pobyt\w*"
SOFT_SKILLS = re.compile(
    r"communicat\w*|teamwork|team player|collaborat\w*|leadership|mentoring|responsib\w*|self[- ]?organi[sz]\w*|"
    r"proactiv\w*|curio\w*|motivat\w*|problem[- ]solving|analytical\s+(?:thinking|mindset|skills)|detail[- ]oriented|"
    r"attention to detail|willing\w*|eager\w*|learn\w*\s+(?:ability|quickly|fast)|fast learn\w*|ambiguity|"
    r"independen\w*|sharing knowledge|interest in|passion\w*|attitude|flexib\w*|creativ\w*|soft skills|mindset",
    re.IGNORECASE)


def _level(text: str) -> int | None:
    """The lowest language level a text names ("B2 minimum, native preferred" → B2), None if it names none."""
    found = [rank for pattern, rank in LEVEL_WORDS if re.search(pattern, text, re.IGNORECASE)]
    return min(found) if found else None


def _speaks(text: str, languages: dict[str, str]) -> bool | None:
    """Whether the candidate speaks a language the text asks for ("Czech or Slovak": either), at the level it asks
    for; None if the text names no spoken language."""
    names = [name for name, pattern in SPOKEN.items() if re.search(pattern, text, re.IGNORECASE)]
    if not names:
        return None
    have = [RANKS.get(languages[name], 0) for name in names if name in languages]
    need = _level(text)
    return bool(have) and (need is None or max(have) >= need)


def _quotes(evidence: str, ad: str) -> bool:
    """Whether a blocker's evidence is the ad's own words (most of its longer words are in the ad), not the
    model's guess about it."""
    words = re.findall(r"\w{4,}", evidence.lower())
    text = ad.lower()
    return bool(words) and sum(word in text for word in words) >= QUOTE_SHARE * len(words)


def _rules_out(blocker: dict, s: Settings) -> bool:
    """Whether the program can confirm a blocker the model found: the model sees blockers where there are none
    ("we don't expect an expert" as experience, "English B2" for a B2 candidate), and a blocker caps the score."""
    evidence, kind = blocker["evidence"], blocker["kind"]
    if kind == "experience":
        top = [level for level in LEVELS if level in s.levels][-1]
        years = [int(found.group(1)) for found in YEARS.finditer(evidence)]
        return (bool(years) and min(years) >= MIN_YEARS[top]) or bool(re.search(rf"\b(?:{ABOVE[top]})\b", evidence,
                                                                                  re.IGNORECASE))
    if kind == "spoken language":
        return _speaks(evidence, s.languages) is False
    if kind == "location":
        return not re.search(rf"{FINE_PLACES}|{re.escape(s.city)}", evidence, re.IGNORECASE)
    if kind == "residency":
        return bool(re.search(RESIDENCY, evidence, re.IGNORECASE))
    return False


def _check(requirement: dict, named: set[str], known: set[str], mine: set[str], s: Settings) -> dict | None:
    """One requirement kept to what the ad, the CV and the settings say; None if it is not a requirement to count:
    it names only technologies the ad doesn't name, it is a soft skill, or years of experience (a blocker)."""
    text = requirement["requirement"]
    found = technologies(text)
    speaks = _speaks(text, s.languages) if not found else None
    if (found and not found & named) or YEARS.search(text) or (speaks is None and not found
                                                               and SOFT_SKILLS.search(text)):
        return None
    match = requirement["match"] if requirement["match"] in MATCH else "no"
    if speaks is not None:  # a spoken language: the settings say it, not the model
        match = "yes" if speaks else "no"
    elif match != "no" and (found & LANGUAGES & named) - mine:  # "C# (similar to C++)" for a C++ CV
        match = "no"
    elif match == "yes" and found and not found & known:  # the CV doesn't show it: at best an adjacent skill
        match = "similar"
    return {"requirement": text, "required": bool(requirement["required"]), "match": match}


def score(answer: dict, job: Job, known: set[str], s: Settings) -> dict:
    """The score the program counts from the model's list of requirements (spec section 20.4): a must-have weighs
    2, a nice-to-have 1; "yes" gives the whole weight, "similar" 70 %, "no" nothing; score = 1 + 9 x the share.
    Blockers the program can confirm, another main language and an ad with few requirements set a ceiling."""
    named = technologies(f"{job.title}\n{job.description}")
    mine = _with_families(known & LANGUAGES)
    requirements = [kept for item in answer["requirements"] if (kept := _check(item, named, known, mine, s))]
    counted = {}
    for key, required in (("must", True), ("nice", False)):
        group = [item for item in requirements if item["required"] == required]
        counted[key] = [round(sum(MATCH[item["match"]] for item in group), 1), len(group)]
    total = sum(WEIGHTS[required] * counted[key][1] for key, required in (("must", True), ("nice", False)))
    points = sum(WEIGHTS[required] * counted[key][0] for key, required in (("must", True), ("nice", False)))
    base = math.floor(1 + 9 * points / total + 0.5) if total else NO_REQUIREMENTS_SCORE
    risks, caps = [], []
    blockers = [{"kind": item["kind"], "evidence": item["evidence"], "cap": CAPS[item["kind"]]}
                for item in answer["blockers"]
                if item.get("kind") in CAPS and _quotes(item["evidence"], f"{job.title}\n{job.description}")
                and _rules_out(item, s)]
    for item in blockers:
        caps.append(item["cap"])
        risks.append(f"{item['evidence']} (score at most {item['cap']})")
    title_languages = technologies(job.title) & LANGUAGES
    if mine and title_languages and not title_languages & mine:
        caps.append(LANGUAGE_CAP)
        risks.append(f"Main language {_ordered(title_languages)} is not in your CV (score at most {LANGUAGE_CAP})")
    else:  # the ad's must-have programming languages, when the title names none of them
        foreign = [technologies(item["requirement"]) & LANGUAGES for item in requirements if item["required"]]
        foreign = set().union(*(languages for languages in foreign if languages and not languages & mine))
        if mine and foreign:
            caps.append(MUST_LANGUAGE_CAP)
            risks.append(f"Must-have language {_ordered(foreign)} is not in your CV "
                         f"(score at most {MUST_LANGUAGE_CAP})")
    if not requirements:
        risks.append("The ad names no concrete requirements: read it before applying")
    elif len(requirements) < FEW_REQUIREMENTS:
        caps.append(FEW_CAP)
        risks.append(f"The ad names few concrete requirements: read it before applying (score at most {FEW_CAP})")
    cap = min(caps) if caps and min(caps) < base else None
    return {
        "score": min(base, cap) if cap else base, "summary": answer.get("summary", ""),
        "requirements": requirements, "blockers": blockers, "counted": {**counted, "base": base, "cap": cap},
        # The lists the Insights tab and older parts of the app read
        "have": [item["requirement"] for item in requirements if item["match"] != "no"],
        "missing": [item["requirement"] for item in requirements if item["match"] == "no"],
        "risks": risks,
    }
