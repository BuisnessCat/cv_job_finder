# Job Finder

**Stop scrolling job boards. Let your own CV pick the jobs worth applying to.**

Job Finder is a small Windows app for students and junior developers. It pulls fresh listings from
several job boards, throws out the ones that have nothing to do with you, and asks an AI model
running **on your own computer** to score every remaining job against your CV — with a short,
honest explanation of why.

![Job Finder: found jobs with scores and the analysis of the selected one](docs/screenshots/found.png)

## Why

Looking for your first developer job usually goes like this: open a job board, scroll through a
hundred listings, open twenty of them, and find out that half want "5+ years of experience" and the
other half are in a city you don't live in. Then do it again tomorrow, and try to remember which
ones you already applied to.

Job Finder does the boring part. You open it, and a few minutes later you see a short list of jobs
sorted by how well they fit you, each with:

- **a score from 1 to 10** — how realistic it is to get through the hiring process;
- **why this score** — one or two sentences, in plain words;
- **what you have** and **what's missing** — matched against what you actually wrote in your CV;
- **risks** — the real deal-breakers only: "3+ years required", "fluent Czech", "office in another city".

A long list of nice-to-have technologies doesn't scare it: the model is told to separate real
requirements from wish lists, and on junior roles a missing tool counts as something to learn, not
a reason to skip.

## What it can do

- 🔎 **Fetches jobs** from four boards with open APIs: [junior.guru](https://junior.guru),
  [Himalayas](https://himalayas.app), [Jobicy](https://jobicy.com) and
  [Working Nomads](https://www.workingnomads.com). Duplicates across boards are merged.
- 🧹 **Filters without AI first**: a job that doesn't mention a single skill from your CV never
  reaches the model.
- 🤖 **Scores the rest locally** with a small model in [LM Studio](https://lmstudio.ai). The app
  starts LM Studio's server, loads the model, and unloads it when it's done — you never open LM
  Studio yourself.
- ⚡ **Shows results as they come**: each scored job appears in the list immediately; the window
  never freezes.
- ♻️ **Never scores the same job twice** — unless you edit your CV, then everything is re-checked
  against the new version.
- 📝 **Tracks your applications**: click **I applied**, and the job moves to **My applications**.
  Mark it **Accepted** or **Rejected** later, keep notes ("talked to HR on Friday"), and see how many
  days you've been waiting. After two weeks without a reply the app reminds you to follow up.
- ↻ **Remembers where you applied**: if the same company reposts the same job, it's marked so you
  don't apply twice by accident.
- • **Marks new jobs** that appeared since you last closed the app.
- 📊 **Shows what to learn next**: the **Insights** tab counts, across all scored jobs, which
  requirements you are missing most often (cloud? TypeScript? Linux?) and what employers ask for most.
- 📄 **Shows the CV it uses** in a separate window, so you always know what the model is comparing
  against.

![My applications (demo data): statuses, days waiting and notes](docs/screenshots/applications.png)

![Insights: the requirements you miss most often and the ones asked for most](docs/screenshots/insights.png)

## Private by design

Your CV never leaves your computer. Job boards are read through their public APIs, the model runs
in LM Studio on your GPU, and everything is stored in one local SQLite file. `master_cv.md` and the
database are in `.gitignore`, so they can't end up on GitHub by accident.

## Getting started

You need:

- **Windows 10/11** and **Python 3.11** (the `py` launcher);
- **[LM Studio](https://lmstudio.ai)** with its command-line tool `lms` (run LM Studio once and it
  installs `lms` into `%USERPROFILE%\.lmstudio\bin`);
- **a GPU with about 8 GB of free video memory** for the default model, Ministral 3 8B.

Then:

1. **Get the code**

   ```bash
   git clone https://github.com/BuisnessCat/cv_job_finder.git
   cd cv_job_finder
   ```

2. **Download the model** (about 6 GB, once):

   ```bash
   lms get mistralai/ministral-3-8b
   ```

3. **Write your CV** as `master_cv.md` in the project folder. Any Markdown works — the model reads
   all of it. The only thing the app needs is a `## Skills` section with one skill group per line,
   because that's what the quick pre-filter uses:

   ```markdown
   ## Skills
   - Python — main language, two pet projects
   - SQL, PostgreSQL — JOINs, aggregation, schema design
   - FastAPI — REST API with pagination and filters
   - Git, GitHub — daily use
   ```

   The first word before each comma is taken as a skill (`Python`, `SQL`, `PostgreSQL`, `FastAPI`,
   `Git`, `GitHub`).

4. **Install** — this creates a virtual environment, installs the dependencies and puts a
   **Job Finder** shortcut on your desktop:

   ```bash
   powershell -ExecutionPolicy Bypass -File install.ps1
   ```

5. **Double-click Job Finder.** The first run scores every matching job, so give it a while (on an
   RTX 3060 it's about 8 seconds per job). After that, only new jobs are scored.

![My CV window: the CV the model compares against](docs/screenshots/cv.png)

## Make it yours

Everything you're likely to tweak lives in [`job_finder/config.py`](job_finder/config.py):

| Setting | Default | What it does |
|---|---|---|
| `MIN_SCORE` | `5` | jobs scored lower are hidden |
| `STALE_DAYS` | `14` | after how many days without a reply the app nudges you |
| `MODEL` | `mistralai/ministral-3-8b` | any instruct model you have in LM Studio |
| `HIMALAYAS_PARAMS`, `JOBICY_PARAMS` | Python, Czechia, entry/mid level | what to ask the job boards for |

The app is tuned for **Prague or remote** jobs: junior.guru listings outside Prague are dropped in
[`job_finder/sources.py`](job_finder/sources.py), and the remote boards are asked for jobs open to
Czechia. Change those two places to search somewhere else. The scoring rules — what counts as a
blocker and what doesn't — are plain English text in [`job_finder/llm.py`](job_finder/llm.py)
(`RULES`); edit them and every job is re-scored with the new rules. What the **Insights** tab counts
as "AWS", "Kubernetes" or "2+ years of experience" is a plain dictionary, `REQUIREMENTS` in
[`job_finder/insights.py`](job_finder/insights.py) — add a line, no re-scoring needed.

Want a different AI? All model calls live in one file, `llm.py`, behind three functions
(`prepare`, `evaluate`, `release`). Swapping LM Studio for a cloud API means rewriting just those.

## Good to know

- The score is a hint, not a verdict. Read the job ad before applying — and apply to the 6s too.
- The model only knows what's in your CV. If you learned something new, add it to `master_cv.md`.
- Windows only for now (the installer, the shortcut and the LM Studio control are Windows-specific).

## Under the hood

Python 3.11 · PySide6 (Qt) · SQLite · requests + BeautifulSoup · LM Studio's OpenAI-compatible API
with JSON-schema output · pytest.

```bash
.venv\Scripts\python -m pytest tests -q
```

The tests run in a few seconds, without network or LM Studio. A plain-language walkthrough of how
everything fits together is in [`docs/how-it-works.ru.md`](docs/how-it-works.ru.md) (in Russian).

## How it was built

This app was built together with [Claude Code](https://claude.com/claude-code), Anthropic's AI coding
assistant. I came up with the idea, decided what the app should and shouldn't do, chose between the
options Claude proposed, and tested every version on my real job search. Claude wrote the code, the
tests and the documentation. The design notes and implementation plans from that process are in
[`docs/superpowers/`](docs/superpowers/) (in Russian).

## License

[MIT](LICENSE) — use it, change it, share it.
