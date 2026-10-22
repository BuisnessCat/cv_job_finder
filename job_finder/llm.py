"""The only place that calls the model. To switch to the Claude API, it is enough to rewrite
prepare / evaluate / release: prepare and release become empty, evaluate calls the API."""
import json
import logging
import re
import subprocess
import tempfile
import time

import requests

from job_finder import config, hardware
from job_finder.settings import LEVELS, Settings
from job_finder.sources import Job

log = logging.getLogger(__name__)

SCHEMA = {
    "type": "object",
    "properties": {
        "score": {"type": "integer", "minimum": 1, "maximum": 10},
        "summary": {"type": "string"},
        "have": {"type": "array", "items": {"type": "string"}},
        "missing": {"type": "array", "items": {"type": "string"}},
        "risks": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["score", "summary", "have", "missing", "risks"],
    "additionalProperties": False,
}

RULES_TEMPLATE = """You help a candidate decide whether to apply for a job. Their CV is below.
Rate from 1 to 10 the candidate's realistic chance of getting this job with this CV: getting through the hiring
process and doing the job.
Each ad ends with the technologies a program found in it and which of them are in the CV: rely on that list,
it is reliable.

About the candidate: {level_text} Languages: {languages}.

How to rate:
1. Identify the core of the role: what the person will do and the 2–4 truly required skills.
   Job ads often list every technology the company uses — those are wishes, not requirements.
   Do not lower the score for missing secondary tools (JIRA, a specific BI system, cloud,
   CI, monitoring, etc.) or "nice to have" items.
2. Count adjacent skills of the same programming language: a similar framework or database counts (e.g.
   Django or Flask instead of FastAPI, MySQL instead of PostgreSQL, React instead of Vue, Spring instead of
   Jakarta EE), any REST/HTTP API, any Git hosting. Another programming language never counts:
   C, C++ and C# are three different languages, and Java is not JavaScript.
3. {learn_text}
4. Lower the score sharply only for real blockers: {experience_blocker}; the job's main programming
   language or field differs from the candidate's main one in the CV; the job requires a language the
   candidate does not speak at the required level; {location_blocker}; citizenship or residency of another
   country is required.
   These are NOT problems: {not_problems}.

Scale:
9–10 — {top_band}, the core stack matches, no blockers;
7–8 — {top_band}, the core matches, some technologies are missing but can be learned;
5–6 — adjacent role or a different framework, but worth a try;
3–4 — serious gap: {gap_band}{below_band} or a noticeably different main stack;
1–2 — not a fit: {misfit_band}, a different main language or field, or a hard blocker.

Answer with a JSON object:
- score — a score from 1 to 10;
- summary — 1–2 sentences: why this score;
- have — important requirements written in the ad that the candidate meets (counting adjacent skills);
- missing — only significant requirements written in the ad that the candidate lacks;
- risks — only real blockers from point 4; an empty list if there are none.
Each list has at most 5 items, each item up to 10 words.
In have and missing never list a technology the ad does not name. If the ad names few concrete requirements,
judge it by the role, the level and the language of work, and do not invent requirements.
Write all texts in English, as plain text without Markdown. Rely only on facts from the CV and the job ad.

Candidate's CV:
"""

# Words for each level: its name in "looking for … roles", the experience that is a blocker for it,
# what is above it (a serious gap) and far above it (not a fit)
LEVEL_WORDS = {
    "intern": dict(name="internship", blocker="commercial experience is required", above="junior or higher level",
                   far="mid or senior"),
    "junior": dict(name="junior", blocker="2+ years of commercial experience or a mid/senior level is required",
                   above="above junior level", far="senior"),
    "mid": dict(name="mid-level", blocker="5+ years of experience or a senior/lead level is required",
                above="senior level", far="lead/principal or 8+ years"),
    "senior": dict(name="senior", blocker="a lead/principal level or 10+ years of experience is required",
                   above="lead or principal level", far="director or executive"),
    "lead": dict(name="lead", blocker="a director or executive level is required", above="director level",
                 far="executive"),
}
LEARN_TEXT = {
    True: "Junior positions and internships teach a lot on the job: if the basics of the candidate's stack match, "
          "missing technologies are a reason to learn, not a reason to reject.",
    False: "On roles at this level a missing secondary technology can be learned on the job; a missing core "
           "technology of the role is a real gap.",
}


def _language(name: str, level: str) -> str:
    return f"{name} native" if level == "Native" else f"{name} {level}"


def render_rules(s: Settings) -> str:
    """The scoring rules for this candidate: levels, languages and location come from the settings."""
    if s.remote:
        location_blocker = f"an office outside {s.city} with no remote option"
        not_problems = [f"an office or hybrid in {s.city}", "remote work from Czechia or the EU"]
    else:
        location_blocker = (f"an office outside {s.city}, or a remote-only job (the candidate wants office or "
                            f"hybrid work in {s.city}; remote-only jobs are not a fit)")
        not_problems = [f"an office or hybrid in {s.city}"]
    for name, level in s.languages.items():
        not_problems.append(f"{name} (native speaker)" if level == "Native"
                            else f"{name} {level} (unless a higher level is required)")
    levels = [level for level in LEVELS if level in s.levels]  # complete settings have at least one
    highest = LEVEL_WORDS[levels[-1]]
    names = " or ".join(LEVEL_WORDS[level]["name"] for level in levels)
    below_band = "" if levels[0] in ("intern", "junior") else f", a role clearly below {levels[0]} level"
    return RULES_TEMPLATE.format(
        level_text=f"The candidate is looking for {names} roles.",
        languages=", ".join(_language(name, level) for name, level in s.languages.items()),
        learn_text=LEARN_TEXT[levels[0] in ("intern", "junior")], experience_blocker=highest["blocker"],
        location_blocker=location_blocker, not_problems=", ".join(not_problems), top_band=f"{names} role",
        gap_band=highest["above"], below_band=below_band, misfit_band=highest["far"])


def fingerprint(s: Settings) -> str:
    """What determines a score besides the CV: if it changes, earlier scores are outdated."""
    return f"{model_name(s)}\n{render_rules(s)}"


def model_name(s: Settings) -> str:
    """The model that scores: from the settings, or the one that fits this computer's graphics card."""
    return s.model or hardware.default_model()


class ModelLost(RuntimeError):
    """The answer came from another model: ours was unloaded from LM Studio mid-run (e.g. from its chat)."""


def clean_output(text: str) -> str:
    """LM Studio's console output for a status line: no colour codes, the last 300 characters."""
    return re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", text).strip()[-300:]


def _lms(*args: str, timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(config.LMS_EXE), *args], stdin=subprocess.DEVNULL, capture_output=True,
        text=True, encoding="utf-8", errors="replace", timeout=timeout,
        creationflags=subprocess.CREATE_NO_WINDOW,  # no flashing console windows
    )


def _server_up() -> bool:
    try:
        requests.get(f"{config.LM_URL}/models", timeout=2).raise_for_status()
        return True
    except requests.RequestException:
        return False


def downloaded_models() -> set[str]:
    """The keys of the models downloaded in LM Studio; empty if it can't tell. The output goes to a temporary file,
    not a pipe: lms may start LM Studio's background service, which would inherit a pipe and keep the call waiting
    forever, even past the timeout."""
    try:
        with tempfile.TemporaryFile("w+", encoding="utf-8", errors="replace") as out:
            subprocess.run([str(config.LMS_EXE), "ls", "--llm", "--json"], stdin=subprocess.DEVNULL, stdout=out,
                           stderr=subprocess.DEVNULL, timeout=60, creationflags=subprocess.CREATE_NO_WINDOW)
            out.seek(0)
            entries = json.loads(out.read())
    except (OSError, subprocess.SubprocessError, ValueError):
        return set()
    return {entry.get("modelKey") for entry in entries if isinstance(entry, dict)} if isinstance(entries, list) else set()


def _loaded_model() -> tuple[bool, str]:
    """Whether a model is loaded under our name, and which one (its key, "" if LM Studio doesn't say)."""
    out = _lms("ps", "--json").stdout
    try:
        entries = json.loads(out)
    except ValueError:
        return config.MODEL_ID in out, ""
    for entry in entries if isinstance(entries, list) else []:
        if isinstance(entry, dict) and entry.get("identifier") == config.MODEL_ID:
            return True, entry.get("modelKey") or ""
    return False, ""


def prepare(model: str) -> None:
    """Start the LM Studio server and load the model if it is not loaded yet."""
    if not config.LMS_EXE.exists():
        raise RuntimeError(f"not found: {config.LMS_EXE}")
    if not _server_up():
        # Output is not captured: the LM Studio service started by the command would inherit our pipes,
        # and subprocess.run would wait for them to close forever, despite the timeout
        subprocess.run(
            [str(config.LMS_EXE), "server", "start", "--port", str(config.LM_PORT)],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=60, creationflags=subprocess.CREATE_NO_WINDOW,
        )
        deadline = time.monotonic() + 30
        while not _server_up():
            if time.monotonic() > deadline:
                raise RuntimeError("server did not start within 30 s")
            time.sleep(1)
    loaded, key = _loaded_model()
    if loaded and key and key != model:  # another model under our name (e.g. the settings changed)
        _lms("unload", config.MODEL_ID)
        loaded = False
    if not loaded:
        # --ttl: if the app closes in the middle of loading, LM Studio unloads the model by itself
        result = _lms(
            "load", model, "--identifier", config.MODEL_ID,
            "--context-length", str(config.CONTEXT_LENGTH), "--gpu", "max", "--ttl", "300", "-y",
            timeout=300,
        )
        if result.returncode != 0:
            raise RuntimeError(f"model failed to load: {clean_output(result.stderr or result.stdout)}")


def evaluate(cv_text: str, job: Job, rules: str, facts: str = "") -> dict:
    """Evaluate one job: score, summary, have, missing, risks. facts: what the program found in the ad, at its end."""
    vacancy = (
        f"Title: {job.title}\nCompany: {job.company}\nLocation: {job.city}\nSource: {job.source}\n\n"
        f"{job.description[:config.MAX_DESCRIPTION_CHARS]}"
    )
    if facts:
        vacancy += f"\n\n{facts}"
    response = requests.post(
        f"{config.LM_URL}/chat/completions",
        json={
            "model": config.MODEL_ID,
            "messages": [
                {"role": "system", "content": rules + cv_text},
                {"role": "user", "content": vacancy},
            ],
            "temperature": 0,
            "max_tokens": 700,
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "evaluation", "strict": True, "schema": SCHEMA},
            },
        },
        timeout=120,
    )
    response.raise_for_status()
    data = response.json()
    # Without our model LM Studio silently answers with any loaded one: such an answer is useless
    if data.get("model") != config.MODEL_ID:
        raise ModelLost(f"model {config.MODEL_ID} was unloaded (got an answer from {data.get('model')}), "
                        "evaluation stopped")
    result = json.loads(data["choices"][0]["message"]["content"])
    result["score"] = int(result["score"])
    return result


def release(wait: bool = True) -> None:
    """Unload the model from VRAM. wait=False: do not wait for it to finish (when the window closes)."""
    try:
        if wait:
            _lms("unload", config.MODEL_ID)
        else:
            subprocess.Popen(
                [str(config.LMS_EXE), "unload", config.MODEL_ID], stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
    except (OSError, subprocess.SubprocessError):
        log.exception("Failed to unload model")
