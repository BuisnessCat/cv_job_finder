# Job Finder

A small Windows app that goes through job boards for me and tells me which jobs are actually worth
applying to.

I made it while looking for my first Python job in Prague. Checking job boards every day got old
fast: most listings want years of experience, a different stack, or an office in another city. So the
app does the first pass for me. It downloads new listings, drops the ones that have nothing to do with
my CV, and asks a local AI model to score the rest from 1 to 10 and explain the score.

![The main window](docs/screenshots/found.png)

## What it does

- Pulls new jobs from junior.guru, the Czech labour office (Úřad práce, its open data), Himalayas, Jobicy,
  Working Nomads, Remote OK and We Work Remotely. All of them have open APIs or feeds. It looks for jobs in
  your region of Czechia and remote jobs open to people in Czechia; the labour office's jobs always come with
  a salary.
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
- Lives in the tray. Every 3 hours it looks for new jobs by itself, and a Windows notification tells
  me when there are new ones scored 7 or more. It waits while a full-screen game is running, because
  the game and the model share the graphics card.
- Doesn't spend time scoring jobs older than a month, and shows the salary when the site gives one.

Nothing leaves the computer except the requests to the job boards. The CV and the database stay on
your machine.

## Installing it

It takes about 20 minutes, most of it waiting for downloads. You don't need Python or anything else
besides LM Studio.

### What you need

- Windows 10 or 11.
- A graphics card that LM Studio supports. The AI model runs on it. With 8 GB of video memory or more
  you get the same model I use (on my RTX 3060 with 12 GB). With less, the app picks a smaller model:
  it's weaker, so the scores may differ a bit, but it works.
- About 8 GB of free disk space: up to 6 GB for the model, the rest for the app.
- Your CV as a Markdown, text or PDF file. A PDF has to contain text, not a scanned picture. If your
  CV is in Word, save it as PDF.

### 1. Install LM Studio

Download and install [LM Studio](https://lmstudio.ai) and **open it once**: on the first start it sets
up its command-line tool, which Job Finder uses to run the model. After that you can close it. You
don't need to download a model there, Job Finder does it for you.

### 2. Install Job Finder

1. Download **`JobFinder-Setup.exe`** from the
   [latest release](https://github.com/BuisnessCat/cv_job_finder/releases/latest).
2. Run it. Windows will probably say "Windows protected your PC", because the app isn't signed (a
   signature costs money every year). Click **More info**, then **Run anyway**.
3. The setup puts Job Finder into your user folder and makes shortcuts on the desktop and in the Start
   menu. At the end it offers to open the app.

### 3. First start

If something is still missing, a **Getting ready** window says what:

- **LM Studio** isn't installed or was never opened: install it, open it once, click **Check again**.
- **The AI model** isn't downloaded: click **Download model**. It's about 6 GB (or about 3 GB for the
  smaller model), so it takes a while. You can keep the window open, or continue and click **Refresh** in
  the app when the download has finished.

Then a short setup asks three things:

1. **Your CV.** Pick the file. The app finds the skills in it and shows them as chips: remove the wrong
   ones, add the missing ones. Then pick your **main skill**. Remote job boards are searched by it, so
   choose what you'd type into a job search, like Python or Java. You don't have to come up with any
   keywords.
2. **What you're looking for.** City, whether remote is fine, and your level. You can pick several
   levels, like Intern and Junior.
3. **Languages.** Every language you speak and how well. The AI checks each job's language
   requirements against them.

After **Start search** the app scores every job it found. The first time this takes a while, about
8 seconds per job on my RTX 3060, so 20–40 minutes. Jobs show up in the list as they're scored, so you
can start reading right away. Later only new jobs get scored, which is a matter of minutes.

Avoid playing games while it's scoring: the game and the model share the video memory. When a
full-screen game is running, the app pauses the scoring and picks it up later.

Closing the window doesn't quit the app: it keeps running in the tray (next to the clock) and looks for
new jobs every 3 hours. Click the icon or the desktop shortcut to open the window again; to quit,
right-click the icon and choose **Quit**.

Everything from the setup can be changed later with the **Settings** button at the top of the window.
If a change affects the scores (your CV, city, levels or languages), the app tells you how long
scoring everything again will take and asks first.

![Settings](docs/screenshots/settings.png)

### Updating

Download the new `JobFinder-Setup.exe` and run it (quit Job Finder first). Your jobs, applications,
notes and settings stay: they live in `%LOCALAPPDATA%\Job Finder`, apart from the app.

### Uninstalling

Start menu → **Uninstall Job Finder** (the app isn't listed in Windows Settings → Apps). Your jobs and
notes stay in `%LOCALAPPDATA%\Job Finder`; delete that folder too if you don't need them. The model can be deleted in LM Studio under My Models.

### If something goes wrong

| What you see | What to do |
|---|---|
| "Windows protected your PC" | The app isn't signed. Click **More info** → **Run anyway**. |
| "Job Finder is running. Close it…" during setup | Right-click the icon next to the clock → **Quit**, then run the setup again. |
| **Getting ready** says LM Studio isn't installed, but it is | Open LM Studio once (it sets up its command-line tool then) and click **Check again**. |
| The model download failed | Check the internet connection and click **Download model** again, or download the model in LM Studio (search for "Ministral 3"). |
| `LM Studio: model failed to load` in the status line | The model isn't downloaded yet (wait for the download, then click Refresh), or there isn't enough free video memory (close games or other heavy apps and click Refresh). |
| Windows Defender or Smart App Control blocks the setup | The app isn't signed, so some security settings block it. Allow it in Windows Security, or run it from the source code (below). |
| Scoring is very slow or times out | The graphics card is busy with something else. Close it and click Refresh. |
| `Himalayas: error (521 …)` or another site error | That site is down for a while. The other sites still work; click Refresh later. |
| Anything else | Look at `job_finder.log` in `%LOCALAPPDATA%\Job Finder`: every error is written there with details. |

## Running it from the source code

For developers, or if you'd rather not run an unsigned exe. You need Python **3.11** (with the py
launcher) and LM Studio.

```powershell
git clone https://github.com/BuisnessCat/cv_job_finder.git JobFinder
cd JobFinder
powershell -ExecutionPolicy Bypass -File install.ps1
```

`install.ps1` makes a virtual environment with the libraries and a Job Finder shortcut on the desktop
(don't also run the setup on the same computer: it would take over that shortcut).
Run from the source code, the app keeps its data in the project folder. To build `JobFinder-Setup.exe`
yourself: `powershell -ExecutionPolicy Bypass -File build.ps1` (it puts the result into `dist`).

## Changing things

Everything about you is in Settings. The technical bits are in `job_finder/config.py`: the models and
what to ask the job boards for. The rules the model uses for scoring are a plain-text template in
`job_finder/llm.py`, filled in from your settings. If you change the template or your CV, all jobs get
scored again on the next refresh.

## Tests

```powershell
.venv\Scripts\python -m pytest tests -q
```

They take a few seconds and don't need internet or LM Studio.

## How it was made

I built this with Claude Code, Anthropic's coding assistant. The idea, the decisions about what the
app should do and the testing on my own job search were mine, and Claude wrote most of the code and
tests. The notes and plans from that process are in `docs/superpowers/` (in Russian), and there's a
plain explanation of how everything fits together in `docs/how-it-works.ru.md`.

## License

MIT
