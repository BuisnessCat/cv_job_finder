from job_finder import skills
from job_finder.sources import Job

CV = """# Master CV

## Target
- Roles: Python backend intern

## Skills — level and evidence
- Python — main language
- SQL — JOINs
- SQLAlchemy 2.0 ORM — models
- Git, GitHub — version control
- requests, BeautifulSoup — web scraping
- Concepts — OOP, REST API design
- In progress, NOT to be presented as done: pytest, Docker Compose

## Projects
- Django — not a skill section
"""

EXPECTED = ["Python", "SQL", "SQLAlchemy", "Git", "GitHub", "requests", "BeautifulSoup"]


def job(title, description=""):
    return Job(url="u", source="s", title=title, company="c", city="", published="2026-10-01",
               description=description)


def test_load_skills():
    assert skills.load_skills(CV) == EXPECTED


def test_load_skills_crlf_and_bom():
    assert skills.load_skills("﻿" + CV.replace("\n", "\r\n")) == EXPECTED


def test_load_skills_without_section():
    assert skills.load_skills("# CV\n\n## Projects\n- Python — x\n") == []


def test_matches_whole_words_case_insensitive():
    skill_list = ["Git", "SQL", "Python"]
    assert skills.matches(job("Junior PYTHON developer"), skill_list)
    assert skills.matches(job("Analyst", "Znalost T-SQL"), skill_list)
    assert not skills.matches(job("DevOps", "GitLab CI, MySQL"), skill_list)


def test_matches_nothing_without_skills():
    assert not skills.matches(job("Python developer"), [])


def test_skill_lines_skip_concepts_and_in_progress():
    cv = "## Skills\n- Python — main\n- Concepts — OOP\n- In progress: pytest\n- SQL, Git — daily\n\n## Projects\n- x\n"
    assert skills.skill_lines(cv) == ["Python — main", "SQL, Git — daily"]
