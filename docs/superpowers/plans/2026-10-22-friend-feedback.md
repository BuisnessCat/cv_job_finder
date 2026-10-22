# Friend's feedback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The model is offered during setup and a missing model never breaks the window; scores rest on technologies the ad really names; junior.guru jobs say which site they come from.

**Architecture:** LM Studio checks move to a non-UI module `lmstudio.py` shared by the worker, the Getting ready panel (now also a wizard step) and one app-wide downloader. A new `grounding.py` builds the "technologies found by the program" facts for the prompt and checks the model's answer afterwards.

**Tech Stack:** Python 3.11, PySide6, LM Studio (`lms`), SQLite, pytest.

**Spec:** `docs/superpowers/specs/2026-10-13-job-finder-design.md`, section 20.

## Global Constraints

- English UI and code, no Cyrillic in `job_finder/`, `tests/` (guard test).
- No lambdas holding `self` in signal connections (exit 139); connect to methods.
- Tests never call real `lms`, the network or `busy.windows_busy`.
- `config.VERSION = "1.2.0"`.
- Open job button unchanged (author's decision).

## Review Focus

1. A long multi-line LM Studio error with ANSI codes in the status: the window keeps its layout (one line, tooltip).
2. Settings complete but no model: the window shows Download model and no load is attempted; after the download a refresh starts once.
3. An ad naming C# for a C++ candidate: C# never lands in "have"; a "C# Developer" title caps the score at 3.
4. A have/missing item without dictionary technologies ("good communication") is kept as is.
5. A junior.guru job whose link is on junior.guru itself shows plain "junior.guru".

---

### Task 1: One-line status

**Files:** Modify `job_finder/window.py`, `job_finder/llm.py`; Test `tests/test_window.py`, `tests/test_llm.py`

**Interfaces:** Produces `window.ElidedLabel(QLabel)`: `setText(text)` keeps the full text, shows one elided line, tooltip = full text when elided. `llm.clean_output(text) -> str` strips ANSI codes, keeps the last 300 chars.

- [ ] Test `test_status_stays_one_line`: a 2000-char text with newlines → label height ≤ 2 × font height, shown text ends with "…", toolTip is the full text.
- [ ] Test `test_clean_output`: `"\x1b[31mError\x1b[0m: no model"` → `"Error: no model"`.
- [ ] Implement; `status_label = ElidedLabel()`; `prepare` uses `clean_output`.
- [ ] Commit.

### Task 2: lmstudio module, one downloader, AI model step in the wizard

**Files:** Create `job_finder/lmstudio.py`; Modify `job_finder/ready_window.py`, `job_finder/settings_window.py`, `job_finder/__main__.py`; Test `tests/test_ready_window.py`, `tests/test_settings_window.py`

**Interfaces:** Produces `lmstudio.lms_installed()`, `lmstudio.model_file_present(model)`, `lmstudio.have_model(model)`, `lmstudio.everything_ready(model)`, `lmstudio.download_model(model) -> int`, `lmstudio.downloading: bool`. `ready_window.downloader() -> Downloader` (one per app; `start(model)`, `running`, `done = Signal(int)`). `ready_window.ReadyPanel(model)` (statuses, Get LM Studio, Download model, Check again; `changed = Signal()`), `ReadyDialog(model)` = panel + Continue. `Wizard(s, model: str | None = None)`, `first_run(cv, model: str | None = None)`: with a model, an "AI model" page after Welcome.

- [ ] Tests: wizard with a model has 5 steps, step 2 shows the panel, Next is enabled while the model is missing; without a model 4 steps. Download started in one panel shows as running in another; `downloader()` is one object. Existing ready-window tests patch `lmstudio.*`.
- [ ] Implement; `__main__`: ReadyDialog only when the settings are complete, otherwise the wizard gets the model.
- [ ] Commit.

### Task 3: No load without the model; Download model button

**Files:** Modify `job_finder/worker.py`, `job_finder/window.py`; Test `tests/test_worker.py`, `tests/test_window.py`

**Interfaces:** Consumes `lmstudio.everything_ready`, `lmstudio.downloading`, `ready_window.downloader()`. Produces `Worker.model_missing: bool`; window `model_button`, `on_model_downloaded(code)`.

- [ ] Tests: worker with jobs to score and no model → `llm.prepare` not called, status "The AI model isn't downloaded yet…", `model_missing` True; while downloading → "Downloading the AI model…". Window: after such a pass the button is visible; `downloader().done` → one refresh, button hidden after a pass with the model.
- [ ] Implement. Commit.

### Task 4: junior.guru (from LinkedIn)

**Files:** Modify `job_finder/sources.py`, `job_finder/window.py`; Test `tests/test_sources.py`, `tests/test_window.py`

**Interfaces:** Produces `sources.source_label(source, url) -> str`.

- [ ] Tests: linkedin.com → "junior.guru (from LinkedIn)", jobs.cz → "(from jobs.cz)", startupjobs.cz → "(from StartupJobs)", other host → domain without www, junior.guru link → "junior.guru", other sources unchanged. The card's Source row uses it.
- [ ] Implement. Commit.

### Task 5: Facts, rules and the answer check

**Files:** Create `job_finder/grounding.py`; Modify `job_finder/llm.py`, `job_finder/worker.py`, `job_finder/settings.py`; Test `tests/test_grounding.py`, `tests/test_llm.py`, `tests/test_worker.py`, `tests/test_settings.py`

**Interfaces:** Produces `grounding.technologies(text) -> set[str]` (dictionary names minus non-technology groups), `grounding.cv_technologies(cv_text, skills) -> set[str]`, `grounding.facts(job, known) -> str`, `grounding.check(evaluation, job, known, languages) -> dict`; `settings.programming_languages(s) -> list[str]`; `llm.evaluate(cv_text, job, rules, facts="")`.

- [ ] Tests: facts for a C# ad and a C++ CV name C#/.NET as not in the CV; "no known technologies" text; check drops a missing "React" the ad doesn't name, moves have "C#" to missing for a C++ CV, keeps "good communication"; "C# Developer" title → score 3 and the risk; JavaScript CV + TypeScript title → no cap; no languages in skills → no cap. Rules mention the candidate's languages and "C, C++ and C# are three different languages"; `scoring_changed` is True when a programming language skill is added, False for another skill.
- [ ] Implement; worker computes the known technologies once per pass and applies `check` before saving.
- [ ] Commit.

### Task 6: Docs, version, before/after

**Files:** Modify `job_finder/config.py`, `README.md`, `docs/how-it-works.ru.md`

- [ ] `VERSION = "1.2.0"`; README (Getting ready as a setup step, Download model button); how-it-works (sections 5, 6, 12).
- [ ] Run the sample with the new code, compare with the baseline, write the table for the author.
- [ ] Commit.
