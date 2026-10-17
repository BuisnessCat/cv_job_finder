"""The only place that calls the model. To switch to the Claude API, it is enough to rewrite
prepare / evaluate / release: prepare and release become empty, evaluate calls the API."""
import json
import logging
import subprocess
import time

import requests

from job_finder import config
from job_finder.settings import Settings
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
Rate from 1 to 10 how realistically the candidate can get through the hiring process and do the job.

About the candidate: {level_text} English: {english}; Czech: {czech}. {permit_text}

How to rate:
1. Identify the core of the role: what the person will do and the 2–4 truly required skills.
   Job ads often list every technology the company uses — those are wishes, not requirements.
   Do not lower the score for missing secondary tools (JIRA, a specific BI system, cloud,
   CI, monitoring, etc.) or "nice to have" items.
2. Count adjacent skills: a similar framework or database counts (e.g. Django or Flask instead of FastAPI,
   MySQL instead of PostgreSQL, React instead of Vue, Spring instead of Jakarta EE), any REST/HTTP API,
   any Git hosting.
3. {learn_text}
4. Lower the score sharply only for real blockers: {experience_blocker}; the job's main programming
   language or field differs from the candidate's main one in the CV; a required language level above the
   candidate's; {location_blocker}; {permit_blocker}citizenship or residency of another country is required.
   These are NOT problems: {not_problems}.

Scale:
9–10 — {top_band}, the core stack matches, no blockers;
7–8 — {top_band}, the core matches, some technologies are missing but can be learned;
5–6 — adjacent role or a different framework, but worth a try;
3–4 — serious gap: {gap_band} or a noticeably different main stack;
1–2 — not a fit: {misfit_band}, a different main language or field, or a hard blocker.

Answer with a JSON object:
- score — a score from 1 to 10;
- summary — 1–2 sentences: why this score;
- have — important job requirements the candidate meets (counting adjacent skills);
- missing — only significant requirements the candidate lacks;
- risks — only real blockers from point 4; an empty list if there are none.
Each list has at most 5 items, each item up to 10 words.
Write all texts in English, as plain text without Markdown. Rely only on facts from the CV and the job ad.

Candidate's CV:
"""

LEVEL_TEXT = {
    "junior": dict(
        level_text="The candidate is looking for junior roles or internships.",
        learn_text="Junior positions and internships teach a lot on the job: if the basics of the candidate's "
                   "stack match, missing technologies are a reason to learn, not a reason to reject.",
        experience_blocker="2+ years of commercial experience or a mid/senior level is required",
        top_band="junior or internship", gap_band="above junior level", misfit_band="senior"),
    "mid": dict(
        level_text="The candidate has commercial experience and is looking for mid-level roles.",
        learn_text="On mid-level roles a missing secondary technology can be learned on the job; a missing core "
                   "technology of the role is a real gap.",
        experience_blocker="5+ years of experience or a senior/lead level is required",
        top_band="mid-level role", gap_band="senior level", misfit_band="lead/principal or 8+ years"),
}


def render_rules(s: Settings) -> str:
    """The scoring rules for this candidate: level, languages, work permit and location come from the settings."""
    if s.remote:
        location_blocker = f"an office outside {s.city} with no remote option"
        not_problems = [f"an office or hybrid in {s.city}", "remote work from Czechia or the EU"]
    else:
        location_blocker = (f"an office outside {s.city}, or a remote-only job (the candidate wants office or "
                            f"hybrid work in {s.city}; remote-only jobs are not a fit)")
        not_problems = [f"an office or hybrid in {s.city}"]
    if s.needs_permit:
        permit_text = "The candidate needs a work permit for Czechia; a job that cannot sponsor one is a blocker."
        permit_blocker = "the employer cannot sponsor a Czech work permit; "
    else:
        permit_text = "The candidate does not need a work permit for Czechia (not a problem)."
        permit_blocker = ""
        not_problems.append("a work permit for Czechia (the candidate does not need one)")
    for language, level in (("English", s.english), ("Czech", s.czech)):
        if level and level != "none":
            not_problems.append(f"{language} {level} (unless a higher level is required)")
    return RULES_TEMPLATE.format(english=s.english or "none", czech=s.czech or "none", permit_text=permit_text,
                                 location_blocker=location_blocker, permit_blocker=permit_blocker,
                                 not_problems=", ".join(not_problems), **LEVEL_TEXT[s.level])


def fingerprint(s: Settings) -> str:
    """What determines a score besides the CV: if it changes, earlier scores are outdated."""
    return f"{config.MODEL}\n{render_rules(s)}"


class ModelLost(RuntimeError):
    """The answer came from another model: ours was unloaded from LM Studio mid-run (e.g. from its chat)."""


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


def prepare() -> None:
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
    if config.MODEL_ID not in _lms("ps", "--json").stdout:
        # --ttl: if the app closes in the middle of loading, LM Studio unloads the model by itself
        result = _lms(
            "load", config.MODEL, "--identifier", config.MODEL_ID,
            "--context-length", str(config.CONTEXT_LENGTH), "--gpu", "max", "--ttl", "300", "-y",
            timeout=300,
        )
        if result.returncode != 0:
            raise RuntimeError(f"model failed to load: {(result.stderr or result.stdout).strip()[-300:]}")


def evaluate(cv_text: str, job: Job, rules: str) -> dict:
    """Evaluate one job: score, summary, have, missing, risks."""
    vacancy = (
        f"Title: {job.title}\nCompany: {job.company}\nLocation: {job.city}\nSource: {job.source}\n\n"
        f"{job.description[:config.MAX_DESCRIPTION_CHARS]}"
    )
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
