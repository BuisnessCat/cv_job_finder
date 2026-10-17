# Job Finder

A small Windows app that goes through job boards for me and tells me which jobs are actually worth
applying to.

I made it while looking for my first Python job in Prague. Checking job boards every day got old
fast: most listings want years of experience, a different stack, or an office in another city. So the
app does the first pass for me. It downloads new listings, drops the ones that have nothing to do with
my CV, and asks a local AI model to score the rest from 1 to 10 and explain the score.

![The main window](docs/screenshots/found.png)

## What it does

- Pulls new jobs from junior.guru, Himalayas, Jobicy and Working Nomads (all of them have open APIs).
- Skips jobs that don't mention any of my skills, so the model doesn't waste time on them. The skills
  are found in the CV automatically and can be fixed by hand.
- Scores the rest with a model running in LM Studio on my own graphics card. For each job I get a
  score, a short reason, what I already have, what's missing and what could rule me out.
- Shows jobs with a score of 5 or more, best first. Jobs that are new since last time are marked.
- Shows how old each job really is. Job sites like to bump old listings so they look new, so the app
  remembers when it first saw a job and marks those as "reposted". There's a search box, a
  7 / 14 / 30 days filter and a "newest first" order above the list.
- Keeps track of where I applied. One click moves a job to My applications, where I can mark it
  accepted or rejected, write notes and see how long I've been waiting for an answer.
- The Insights tab counts what I'm missing most often across all jobs. Handy for deciding what to
  learn next.

Nothing leaves the computer except the requests to the job boards. My CV and the database stay on
my machine and are ignored by git.

![My applications (demo data)](docs/screenshots/applications.png)

![Insights](docs/screenshots/insights.png)

## Running it yourself

You'll need Windows, Python 3.11, [LM Studio](https://lmstudio.ai) and a graphics card with about
8 GB of free memory.

1. Clone the repo:

   ```bash
   git clone https://github.com/BuisnessCat/cv_job_finder.git
   cd cv_job_finder
   ```

2. Download the model (about 6 GB):

   ```bash
   lms get mistralai/ministral-3-8b
   ```

3. Run the installer. It sets up a virtual environment and puts a Job Finder shortcut on the desktop:

   ```bash
   powershell -ExecutionPolicy Bypass -File install.ps1
   ```

4. Open Job Finder from the shortcut. The first time, a short setup asks for your CV (Markdown, plain
   text or PDF), finds the skills in it and asks what you're looking for: city, remote or not, your
   level (you can pick several, like intern and junior) and the languages you speak. There are no
   keywords to come up with: the remote job boards are searched by your main skill, which you pick
   from your own list.

5. After that the app scores every job, so the first run takes a while (on my RTX 3060 it's about
   8 seconds per job). Later only new jobs get scored.

You don't have to open LM Studio yourself. The app starts it, loads the model and unloads it when
it's done.

![Settings](docs/screenshots/settings.png)

## Changing things

Everything about you is in Settings (the button at the top of the window): your CV and skills, the
main skill, city, levels and languages. If a change affects the scores, the app tells you how long
scoring everything again will take before it saves.

The technical bits are in `job_finder/config.py`: the model and what to ask the job boards for. The
rules the model uses for scoring are a plain-text template in `job_finder/llm.py`, filled in from
your settings. If you change the template or your CV, all jobs get scored again on the next refresh.

## Tests

```bash
.venv\Scripts\python -m pytest tests -q
```

They take a couple of seconds and don't need internet or LM Studio.

## How it was made

I built this with Claude Code, Anthropic's coding assistant. The idea, the decisions about what the
app should do and the testing on my own job search were mine, and Claude wrote most of the code and
tests. The notes and plans from that process are in `docs/superpowers/` (in Russian), and there's a
plain explanation of how everything fits together in `docs/how-it-works.ru.md`.

## License

MIT
