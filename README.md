<div align="center">

<img src="docs/icon.png" width="88" alt="">

# Job Finder

**Reads job boards for you and tells you which jobs are worth applying to.**

[![Download JobFinder-Setup.exe](https://img.shields.io/badge/Download-JobFinder--Setup.exe-2ea043?style=for-the-badge)](https://github.com/BuisnessCat/cv_job_finder/releases/latest)

![Latest release](https://img.shields.io/github/v/release/BuisnessCat/cv_job_finder?color=2ea043)
![Windows 10 and 11](https://img.shields.io/badge/Windows-10%20%7C%2011-0078d4)
![The AI runs on your PC](https://img.shields.io/badge/AI-runs%20on%20your%20PC-8957e5)
![MIT license](https://img.shields.io/badge/license-MIT-blue)

</div>

![The main window](docs/screenshots/found.png)

Job Finder downloads new listings, drops the ones that don't match your CV, and asks an AI model
running on your own graphics card to score the rest from 1 to 10 and explain why. I made it while
looking for my first Python job in Prague: checking job boards every day got old fast.

## What it does

<table>
<tr>
<td width="50%" valign="top">

🔎 **Seven job sites**<br>
junior.guru, Úřad práce, Himalayas, Jobicy, Working Nomads, Remote OK and We Work Remotely. Your
region of Czechia and remote jobs open to it.

</td>
<td width="50%" valign="top">

🤖 **A score for every job**<br>
From 1 to 10, with the reason, what you already have, what's missing and what could rule you out.

</td>
</tr>
<tr>
<td valign="top">

⭐ **The good ones first**<br>
Jobs scored 5 or more, best first, new ones marked. Jobs that don't mention your skills or are older
than a month are skipped.

</td>
<td valign="top">

♻️ **Old jobs spotted**<br>
Sites bump old listings so they look new. The app remembers when it first saw a job and marks
reposts.

</td>
</tr>
<tr>
<td valign="top">

📋 **Your applications**<br>
Notes, accepted or rejected, and how long you've been waiting for an answer.

</td>
<td valign="top">

📚 **What to learn next**<br>
The Insights tab counts the skills jobs want that you don't have yet.

</td>
</tr>
<tr>
<td valign="top">

🔔 **Works in the background**<br>
Sits in the tray, looks for new jobs every 3 hours and notifies you when one scores 7 or more.

</td>
<td valign="top">

🔒 **Stays on your computer**<br>
Only the requests to the job sites go out. Your CV and the jobs stay on your machine.

</td>
</tr>
</table>

## Installing

About 20 minutes, most of it waiting for downloads. You don't need Python.

> [!IMPORTANT]
> **You need** Windows 10 or 11, a graphics card that LM Studio supports, about 8 GB of free disk
> space and your CV as a PDF, Markdown or text file (a PDF with real text, not a scan).
> With 8 GB of video memory or more you get the full model; with less, the app picks a smaller one,
> which scores a bit less precisely.

### Step 1 · LM Studio

Download [LM Studio](https://lmstudio.ai), install it and **open it once**: on the first start it
sets up the command-line tool Job Finder uses. Then you can close it. You don't need to download a
model there.

### Step 2 · Job Finder

Download **JobFinder-Setup.exe** from the
[latest release](https://github.com/BuisnessCat/cv_job_finder/releases/latest) and run it. It
installs into your user folder and adds shortcuts to the desktop and the Start menu.

> [!TIP]
> If Windows says **"Windows protected your PC"**, click **More info**, then **Run anyway**. The app
> isn't signed: a code signature costs money every year.

### Step 3 · First start

1. **Getting ready.** If LM Studio or the AI model is missing, a window says what to do. The model
   downloads with one click: about 6 GB, or 3 GB for the smaller one.
2. **Setup.** Pick your CV, check the skills the app found in it and choose your main skill, like
   Python or Java. Then your city, whether remote is fine, your level (you can pick several, like
   Intern and Junior) and the languages you speak.
3. **Start search.** The first scoring takes a while: about 8 seconds per job, so 20–40 minutes on an
   RTX 3060. Jobs appear as they're scored, so you can start reading right away. Later only new jobs
   are scored.

## Day to day

- **Closing the window doesn't quit the app.** It stays in the tray next to the clock. To quit,
  right-click the icon and choose **Quit**.
- **Settings**, at the top of the window, changes anything from the setup. If a change affects the
  scores, the app says how long scoring everything again will take and asks first.
- **Games and the model share the video memory**, so the app pauses scoring while a full-screen game
  is running and picks it up later.
- **Updating:** when a new version is out, a green **Update** button appears at the top of the window
  (and a notification, if the app is in the tray). Click it, download the new `JobFinder-Setup.exe`, quit
  Job Finder and run the setup. Your jobs, applications and settings stay: they live in
  `%LOCALAPPDATA%\Job Finder`, apart from the app.
- **Uninstalling:** Start menu → **Uninstall Job Finder** (it isn't listed in Windows Settings → Apps).
  Your data stays in
  `%LOCALAPPDATA%\Job Finder`: delete that folder too if you don't need it. The model can be deleted
  in LM Studio under **My Models**.

<details>
<summary><b>If something goes wrong</b></summary>

<br>

| What you see | What to do |
|---|---|
| "Windows protected your PC" | Click **More info** → **Run anyway**. |
| "Job Finder is running. Close it…" during setup | Right-click the icon next to the clock → **Quit**, then run the setup again. |
| **Getting ready** says LM Studio isn't installed, but it is | Open LM Studio once and click **Check again**. |
| The model download failed | Check the internet connection and click **Download model** again, or download "Ministral 3" in LM Studio. |
| `LM Studio: model failed to load` | Wait until the model has downloaded, or close games and other heavy apps to free video memory. Then click **Refresh**. |
| Windows Security or Smart App Control blocks the setup | Allow it in Windows Security, or run the app from the source code (below). |
| Scoring is very slow or times out | Something else is using the graphics card. Close it and click **Refresh**. |
| `Himalayas: error (521 …)` or another site error | That site is down for a while. The others still work; click **Refresh** later. |
| Anything else | Every error is written to `job_finder.log` in `%LOCALAPPDATA%\Job Finder`. |

</details>

<details>
<summary><b>For developers: running from the source code</b></summary>

<br>

For developers, or if you'd rather not run an unsigned exe. You need Python 3.11 and LM Studio.

```powershell
git clone https://github.com/BuisnessCat/cv_job_finder.git JobFinder
cd JobFinder
powershell -ExecutionPolicy Bypass -File install.ps1
```

`install.ps1` makes a virtual environment and a Job Finder shortcut on the desktop. Run this way, the
app keeps its data in the project folder. Don't also run the setup on the same computer: it would take
over the shortcut.

- **Build the setup:** `powershell -ExecutionPolicy Bypass -File build.ps1` → `dist\JobFinder-Setup.exe`
- **Run the tests:** `.venv\Scripts\python -m pytest tests -q` (a few seconds, no internet or LM Studio needed)
- **Models and job site queries:** `job_finder/config.py`
- **Scoring rules:** a plain-text template in `job_finder/llm.py`. Changing it, or your CV, re-scores
  every job on the next refresh.

</details>

## About

I use Job Finder for my own job search and keep improving it based on what I see there: which jobs it
misses, which scores feel wrong.

I built it with [Claude Code](https://claude.com/claude-code), Anthropic's AI coding assistant. My part
was the product: what the app should do, how it should look and work, which trade-offs to make, and
testing every change on my real job search. Claude did most of the coding. The design notes and plans
are in [`docs/superpowers/`](docs/superpowers/), and [`docs/how-it-works.ru.md`](docs/how-it-works.ru.md)
explains how the parts fit together (both in Russian).

Licensed under MIT.
