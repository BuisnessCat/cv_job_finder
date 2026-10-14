"""Filtering jobs without AI: does the job mention at least one skill from master_cv.md."""
import re

from job_finder.sources import Job


def skill_lines(cv_text: str) -> list[str]:
    """Items of the "## Skills" section that count as skills: "- " lines without Concepts and In progress."""
    lines = []
    in_skills = False
    for line in cv_text.splitlines():
        if line.startswith("## "):
            in_skills = line.startswith("## Skills")
            continue
        if in_skills and line.startswith("- ") and not line[2:].startswith(("Concepts", "In progress")):
            lines.append(line[2:])
    return lines


def load_skills(cv_text: str) -> list[str]:
    """Skills from the "## Skills" section: line part before " — ", split by commas, first word of each."""
    skills = []
    for item in skill_lines(cv_text):
        for part in item.split(" — ")[0].split(","):
            words = part.split()
            if words:
                skills.append(words[0])
    return skills


def matches(job: Job, skills: list[str]) -> bool:
    """Whether at least one skill appears in the title or description: whole word, case-insensitive."""
    text = f"{job.title}\n{job.description}"
    return any(re.search(rf"(?<!\w){re.escape(skill)}(?!\w)", text, re.IGNORECASE) for skill in skills)
