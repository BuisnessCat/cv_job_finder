"""The only place that calls the model. To switch to the Claude API, it is enough to rewrite
prepare / evaluate / release: prepare and release become empty, evaluate calls the API."""
import json
import logging
import re
import subprocess
import tempfile
import time

import requests

from job_finder import config, grounding, hardware
from job_finder.settings import LEVELS, Settings
from job_finder.sources import Job

log = logging.getLogger(__name__)

# The model lists the ad's requirements and blockers; the program counts the score from them (grounding.score)
SCHEMA = {
    "type": "object",
    "properties": {
        "requirements": {"type": "array", "items": {
            "type": "object",
            "properties": {"requirement": {"type": "string"}, "required": {"type": "boolean"},
                           "match": {"type": "string", "enum": list(grounding.MATCH)}},
            "required": ["requirement", "required", "match"],
            "additionalProperties": False,
        }},
        "blockers": {"type": "array", "items": {
            "type": "object",
            "properties": {"kind": {"type": "string", "enum": list(grounding.CAPS)}, "evidence": {"type": "string"}},
            "required": ["kind", "evidence"],
            "additionalProperties": False,
        }},
        "summary": {"type": "string"},
    },
    "required": ["requirements", "blockers", "summary"],
    "additionalProperties": False,
}

RULES_TEMPLATE = """You help a candidate decide whether to apply for a job. Their CV is below. You do not give a
score: you list what the ad asks for and whether the CV has it, and a program counts the score from that.
Each ad ends with the technologies a program found in it and which of them are in the CV: rely on that list,
it is reliable.

About the candidate: {level_text} Languages: {languages}.

Answer with a JSON object:
- requirements — what the ad asks of the candidate, at most 8, the most important first: technologies, skills,
  education, spoken languages. Each has:
  - requirement — up to 8 words; when the candidate has a similar skill, add it: "Django (has FastAPI)";
  - required — true if the ad says it is required or a must, or it is the core of the role; false for
    "nice to have", "a plus", "an advantage" and long lists of every tool the company uses;
  - match — "yes" if the CV shows it; "similar" if the CV has an adjacent skill of the same programming
    language: a similar framework or database (Django or Flask for FastAPI, MySQL for PostgreSQL, React for
    Vue, Spring for Jakarta EE), any REST/HTTP API, any Git hosting; otherwise "no". Another programming
    language is never similar: C, C++ and C# are three different languages, and Java is not JavaScript.
  Only requirements written in the ad: never add a technology the ad does not name. If the ad names few
  concrete requirements, list only those and do not invent requirements. Experience, level, location and
  residency are not requirements: they are blockers when they rule the candidate out.
- blockers — only real hard stops, each with a kind and evidence (a short quote from the ad):
  "experience" — {experience_blocker};
  "spoken language" — the job requires a language the candidate does not speak at the required level;
  "location" — {location_blocker};
  "residency" — citizenship or residency of another country is required;
  "field" — the role is in another field than the candidate's CV (e.g. sales or hardware design for a
  software developer).
  These are NOT blockers: {not_problems}. An empty list if there are none.
- summary — 1–2 sentences: the main reasons for and against.
Write all texts in English, as plain text without Markdown. Rely only on facts from the CV and the job ad.

Candidate's CV:
"""

# Words for each level: its name in "looking for … roles" and the experience that is a blocker for it
LEVEL_WORDS = {
    "intern": dict(name="internship", blocker="commercial experience is required"),
    "junior": dict(name="junior", blocker="2+ years of commercial experience or a mid/senior level is required"),
    "mid": dict(name="mid-level", blocker="5+ years of experience or a senior/lead level is required"),
    "senior": dict(name="senior", blocker="a lead/principal level or 10+ years of experience is required"),
    "lead": dict(name="lead", blocker="a director or executive level is required"),
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
    names = " or ".join(LEVEL_WORDS[level]["name"] for level in levels)
    experience = LEVEL_WORDS[levels[-1]]["blocker"]
    if levels[0] not in ("intern", "junior"):
        experience += f", or a role clearly below {levels[0]} level"
    return RULES_TEMPLATE.format(
        level_text=f"The candidate is looking for {names} roles.",
        languages=", ".join(_language(name, level) for name, level in s.languages.items()),
        experience_blocker=experience, location_blocker=location_blocker, not_problems=", ".join(not_problems))


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
    """The model's answer for one job: requirements, blockers, summary (grounding.score counts the score). facts:
    what the program found in the ad, at its end."""
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
            "max_tokens": 900,
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
    return json.loads(data["choices"][0]["message"]["content"])


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
