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
from job_finder.settings import AREAS, LEVELS, Settings
from job_finder.sources import Job

log = logging.getLogger(__name__)

_SKILLS = {"type": "array", "items": {
    "type": "object",
    "properties": {"skill": {"type": "string"}, "match": {"type": "string", "enum": ["yes", "similar", "no"]}},
    "required": ["skill", "match"],
    "additionalProperties": False,
}}
# The model takes the facts out of the ad; the program compares them with the profile (grounding.verdict)
SCHEMA = {
    "type": "object",
    "properties": {
        "areas": {"type": "array", "items": {"type": "string", "enum": [*AREAS, "Other IT", "Not IT"]}},
        "seniority": {"type": "string", "enum": [*LEVELS, "not stated"]},
        "min_years": {"type": "integer"},
        "degree": {"type": "string", "enum": ["none", "bachelor", "master", "phd"]},
        "students_welcome": {"type": "boolean"},
        "languages": {"type": "array", "items": {
            "type": "object",
            "properties": {"language": {"type": "string"},
                           "level": {"type": "string",
                                     "enum": ["A1", "A2", "B1", "B2", "C1", "C2", "native", "not stated"]}},
            "required": ["language", "level"],
            "additionalProperties": False,
        }},
        "workplace": {"type": "string", "enum": ["office", "hybrid", "remote", "not stated"]},
        "place": {"type": "string"},
        "must_have": _SKILLS,
        "nice_to_have": _SKILLS,
        "about": {"type": "string"},
    },
    "required": ["areas", "seniority", "min_years", "degree", "students_welcome", "languages", "workplace", "place",
                 "must_have", "nice_to_have", "about"],
    "additionalProperties": False,
}

RULES = """You read a job ad for a candidate whose CV is below. You do not judge whether the candidate fits:
you take the facts out of the ad, and a program compares them with the candidate.
Each ad ends with the technologies a program found in it and which of them are in the CV: rely on that list,
it is reliable.

Answer with a JSON object:
- areas — the kind of work: one or two of {areas} (two when the job mixes
  them, e.g. "Embedded / hardware" and "Backend"); "Other IT" if none of them fits, "Not IT" if it is not an
  IT job;
- seniority — the level the ad asks for: intern, junior, mid, senior, lead, or "not stated";
- min_years — the minimum years of work experience the ad requires; 0 if it doesn't say;
- degree — the minimum degree the ad requires: none, bachelor, master or phd; "none" if a degree is only
  preferred or not mentioned;
- students_welcome — true if the ad welcomes students or fresh graduates;
- languages — the spoken languages the ad requires, each with its level (A1 to C2, native, or "not stated");
- workplace — office, hybrid, remote, or "not stated";
- place — the city of the office, or the countries or regions a remote job is open to; "" if not stated;
- must_have — the skills and technologies the ad requires, at most 6, the core of the role first;
- nice_to_have — the ones it only welcomes ("a plus", "an advantage", "nice to have"), at most 6;
  for each skill, match: "yes" if the CV shows it; "similar" if the CV has an adjacent skill of the same
  programming language (Django or Flask for FastAPI, MySQL for PostgreSQL, React for Vue, Spring for
  Jakarta EE), any REST/HTTP API, any Git hosting; otherwise "no". Another programming language is never
  similar: C, C++ and C# are three different languages, and Java is not JavaScript.
  List what the ad asks for, as the ad writes it, whether the candidate has it or not; never add the
  candidate's skills the ad doesn't ask for, nor a technology the ad does not name. Soft skills, years of
  experience, degrees and spoken languages are not skills here.
- about — one sentence: what the person will do in this job.
Write all texts in English, as plain text without Markdown.

Candidate's CV:
""".format(areas=", ".join(AREAS))


def render_rules(s: Settings) -> str:
    """The rules for the model: the same for everyone, the profile is the program's part (spec section 21.2)."""
    return RULES


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
    """The model's facts about one job (grounding.verdict decides). facts: what the program found in the ad, at its
    end."""
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
