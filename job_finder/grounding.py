"""Technologies an ad really names, found by the program (the skills dictionary, strict patterns), not by the model:
facts given to the model with the ad; then the score, counted by the program from the model's list of requirements
and checked against the ad and the CV (spec sections 20.3, 20.4)."""
import math
import re

from job_finder import insights, settings
from job_finder.sources import Job

FAMILIES = [{"JavaScript", "TypeScript"}]  # in the main-language check one counts for the other
LANGUAGES = set(settings.PROGRAMMING_LANGUAGES)

# How the score is counted (spec section 20.4)
WEIGHTS = {True: 2, False: 1}  # a must-have, a nice-to-have
MATCH = {"yes": 1.0, "similar": 0.7, "no": 0.0}  # the share of the weight the candidate gets
CAPS = {"experience": 4, "spoken language": 4, "location": 3, "field": 3, "residency": 2}  # ceilings of blockers
LANGUAGE_CAP = 3  # the title names a programming language the CV doesn't have
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


def _check(requirement: dict, named: set[str], known: set[str], mine: set[str]) -> dict | None:
    """One requirement kept to what the ad and the CV say; None if it names only technologies the ad doesn't name."""
    found = technologies(requirement["requirement"])
    if found and not found & named:
        return None
    match = requirement["match"] if requirement["match"] in MATCH else "no"
    if match != "no" and (found & LANGUAGES & named) - mine:  # "C# (similar to C++)" for a C++ CV
        match = "no"
    elif match == "yes" and found and not found & known:  # the CV doesn't show it: at best an adjacent skill
        match = "similar"
    return {"requirement": requirement["requirement"], "required": bool(requirement["required"]), "match": match}


def score(answer: dict, job: Job, known: set[str]) -> dict:
    """The score the program counts from the model's list of requirements (spec section 20.4): a must-have weighs
    2, a nice-to-have 1; "yes" gives the whole weight, "similar" 70 %, "no" nothing; score = 1 + 9 x the share.
    Blockers, another main language in the title and an ad with few requirements set a ceiling."""
    named = technologies(f"{job.title}\n{job.description}")
    mine = _with_families(known & LANGUAGES)
    requirements = [kept for item in answer["requirements"] if (kept := _check(item, named, known, mine))]
    counted = {}
    for key, required in (("must", True), ("nice", False)):
        group = [item for item in requirements if item["required"] == required]
        counted[key] = [round(sum(MATCH[item["match"]] for item in group), 1), len(group)]
    total = sum(WEIGHTS[required] * counted[key][1] for key, required in (("must", True), ("nice", False)))
    points = sum(WEIGHTS[required] * counted[key][0] for key, required in (("must", True), ("nice", False)))
    base = math.floor(1 + 9 * points / total + 0.5) if total else NO_REQUIREMENTS_SCORE
    risks, caps = [], []
    blockers = [{"kind": item["kind"], "evidence": item["evidence"], "cap": CAPS[item["kind"]]}
                for item in answer["blockers"] if item.get("kind") in CAPS]
    for item in blockers:
        caps.append(item["cap"])
        risks.append(f"{item['evidence']} (score at most {item['cap']})")
    title_languages = technologies(job.title) & LANGUAGES
    if mine and title_languages and not title_languages & mine:
        caps.append(LANGUAGE_CAP)
        risks.append(f"Main language {_ordered(title_languages)} is not in your CV (score at most {LANGUAGE_CAP})")
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
