"""Technologies an ad really names, found by the program (the skills dictionary, strict patterns), not by the model:
facts given to the model with the ad, and a check of its answer (spec section 20.3)."""
import re

from job_finder import insights, settings
from job_finder.sources import Job

FAMILIES = [{"JavaScript", "TypeScript"}]  # in the main-language check one counts for the other
LANGUAGES = set(settings.PROGRAMMING_LANGUAGES)
MAX_SCORE_OTHER_LANGUAGE = 3


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


def check(evaluation: dict, job: Job, known: set[str]) -> dict:
    """The model's answer kept to what the ad and the CV say: an item naming only technologies the ad doesn't name
    is dropped; an item in "have" with a programming language the CV doesn't have moves to "missing"; a job whose
    title names only languages the candidate doesn't have gets at most MAX_SCORE_OTHER_LANGUAGE."""
    named = technologies(f"{job.title}\n{job.description}")
    mine = _with_families(known & LANGUAGES)

    def in_ad(item: str) -> bool:
        found = technologies(item)
        return not found or bool(found & named)  # an item without technologies ("teamwork") is the model's word

    missing = [item for item in evaluation["missing"] if in_ad(item)]
    have = []
    for item in filter(in_ad, evaluation["have"]):
        foreign = (technologies(item) & LANGUAGES & named) - mine  # "C# (similar to C++)" for a C++ CV: C#
        if foreign:
            if not any(technologies(other) & foreign for other in missing):
                missing.append(item)
            continue
        have.append(item)
    score, risks = evaluation["score"], list(evaluation["risks"])
    title_languages = technologies(job.title) & LANGUAGES
    if mine and title_languages and not title_languages & mine and score > MAX_SCORE_OTHER_LANGUAGE:
        score = MAX_SCORE_OTHER_LANGUAGE
        risks.append(f"Main language: {_ordered(title_languages)} (not in your CV)")
    return {**evaluation, "score": score, "have": have, "missing": missing, "risks": risks}
