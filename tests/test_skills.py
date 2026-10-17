from job_finder import skills
from job_finder.sources import Job


def job(title, description=""):
    return Job(url="u", source="s", title=title, company="c", city="", published="2026-10-01",
               description=description)


def test_matches_whole_words_case_insensitive():
    skill_list = ["Git", "SQL", "Python"]
    assert skills.matches(job("Junior PYTHON developer"), skill_list)
    assert skills.matches(job("Analyst", "Znalost T-SQL"), skill_list)
    assert not skills.matches(job("DevOps", "GitLab CI, MySQL"), skill_list)


def test_matches_nothing_without_skills():
    assert not skills.matches(job("Python developer"), [])


def test_dictionary_and_custom_skills_match():
    job = Job(url="u", source="s", title="Backend", company="c", city="", published="",
              description="REST API on Node.js with 1C integration")
    assert skills.matches(job, ["Node.js"]) and skills.matches(job, ["REST API"]) and skills.matches(job, ["1C"])
    assert not skills.matches(job, ["Go"])
