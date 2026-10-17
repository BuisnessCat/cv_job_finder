"""Filtering jobs without AI: does the job mention at least one skill from the settings."""
import re

from job_finder import insights
from job_finder.sources import Job


def matches(job: Job, skills: list[str]) -> bool:
    """Whether at least one skill appears in the title or description.

    A skill from the Insights dictionary is found by its spellings ("k8s" counts as Kubernetes); any other
    skill as a whole word, case-insensitive."""
    text = f"{job.title}\n{job.description}"
    found = insights.find(text)
    return any(skill in found if skill in insights.REQUIREMENTS
               else re.search(rf"(?<!\w){re.escape(skill)}(?!\w)", text, re.IGNORECASE)
               for skill in skills)
