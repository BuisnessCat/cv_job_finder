from dataclasses import replace

from job_finder import grounding
from job_finder.settings import Settings
from job_finder.sources import Job

S = Settings(cv_path="cv.md", skills=["Python"], main_skill="Python", city="Praha", remote=True,
             levels=["intern", "junior"], languages={"English": "B2", "Czech": "B1"})


def score(a, job, known, s=S):
    return grounding.score(a, job, known, s)

CSHARP_AD = Job(url="u", source="junior.guru", title="Junior C# Developer", company="A", city="Prague",
                published="2026-10-20", description="We build web apps in C# and .NET with SQL Server. Git is a plus.")
CPP_CV = "Junior developer. Skills: C++17, C, CMake, Git, Linux"


def req(text, required=True, match="yes"):
    return {"requirement": text, "required": required, "match": match}


def answer(requirements=(), blockers=()):
    return {"summary": "ok", "requirements": list(requirements), "blockers": list(blockers)}


PY_AD = Job(url="p", source="Jobicy", title="Junior Python Developer", company="A", city="", published="",
            description="Required: Python, SQL, Django, Docker. React and AWS are a plus. Teamwork.")
KNOWN = {"Python", "SQL", "FastAPI", "Git"}


def test_technologies_are_found_strictly():
    assert grounding.technologies("C# and .NET, SQL") == {"C#/.NET", "SQL"}
    assert "C/C++" in grounding.technologies("C++17")
    assert "C/C++" not in grounding.technologies("Junior C# Developer")  # C# is not C
    assert grounding.technologies("Our R&D team will go to market, grade C.") == set()
    assert grounding.technologies("2+ years of experience, fluent English, a degree") == set()  # not technologies


def test_facts_tell_the_model_what_the_ad_names():
    known = grounding.cv_technologies(CPP_CV)
    assert "C/C++" in known and "C#/.NET" not in known
    facts = grounding.facts(CSHARP_AD, known)
    assert "C#/.NET" in facts.split("Not in the CV:")[1]
    assert "Git" in facts.split("Not in the CV:")[0].split("in the candidate's CV:")[1]
    assert "C/C++" not in facts  # the CV's own languages are not "named in the ad"


def test_facts_when_the_ad_names_no_known_technology():
    vague = Job(url="v", source="Jobicy", title="Junior Developer", company="A", city="", published="",
                description="Join our friendly team and grow with us.")
    assert "no known technologies" in grounding.facts(vague, {"Python"})


def test_score_is_counted_from_the_requirements():
    result = score(answer([req("Python"), req("SQL"), req("Django (has FastAPI)", match="similar"),
                                     req("Docker", match="no"), req("React", False, "no"), req("AWS", False, "no")]),
                             PY_AD, KNOWN)
    # must-have 1 + 1 + 0.7 + 0 = 2.7 of 4, weight 2; nice to have 0 of 2, weight 1: 5.4 of 10 -> 1 + 9 x 0.54 = 5.9
    assert result["score"] == 6
    assert result["counted"] == {"must": [2.7, 4], "nice": [0.0, 2], "base": 6, "cap": None}
    assert result["have"] == ["Python", "SQL", "Django (has FastAPI)"]
    assert result["missing"] == ["Docker", "React", "AWS"] and result["risks"] == []
    every = answer([req("Python"), req("SQL"), req("Django", match="no"), req("Docker")])
    assert score(every, PY_AD, KNOWN | {"Docker"})["score"] == 8  # one of four must-haves missing


def test_blockers_cap_the_score():
    result = score(answer([req("Python"), req("SQL")] + [req(f"skill {i}") for i in range(3)],
                                    [{"kind": "experience", "evidence": "3+ years of commercial experience"}]),
                             replace(PY_AD, description=PY_AD.description + " 3+ years of commercial experience."), KNOWN)
    assert result["score"] == 4 and result["counted"]["base"] == 10 and result["counted"]["cap"] == 4
    assert result["blockers"] == [{"kind": "experience", "evidence": "3+ years of commercial experience", "cap": 4}]
    assert result["risks"] == ["3+ years of commercial experience (score at most 4)"]


def test_another_main_language_in_the_title_caps_the_score():
    result = score(answer([req("Git"), req("SQL Server", False, "no"), req("Bachelor's degree")]), CSHARP_AD,
                             {"C/C++", "Git"})
    assert result["score"] == 3
    assert result["risks"] == ["Main language C#/.NET is not in your CV (score at most 3)"]
    assert score(answer([req("C#", match="no")] * 3), CSHARP_AD, {"C/C++"})["score"] == 1  # lower stays
    js = Job(url="t", source="Jobicy", title="TypeScript Developer", company="A", city="", published="",
             description="TypeScript, React, Git")
    met = answer([req("TypeScript", match="similar"), req("React"), req("Git")])
    assert score(met, js, {"JavaScript", "React", "Git"})["counted"]["cap"] is None  # one family
    java = Job(url="j", source="Jobicy", title="Java Tester", company="A", city="", published="",
               description="Testing, SQL, Jira")
    tests = answer([req("Testing"), req("SQL"), req("Jira")])
    assert score(tests, java, {"SQL", "Testing"})["counted"]["cap"] is None  # no languages in the CV


def test_few_requirements_cap_the_score():
    two = score(answer([req("Python"), req("SQL")]), PY_AD, KNOWN)
    assert two["score"] == 7 and two["risks"] == ["The ad names few concrete requirements: read it before applying "
                                                   "(score at most 7)"]
    none = score(answer(), PY_AD, KNOWN)
    assert none["score"] == 5 and none["counted"]["base"] == 5


def test_requirements_are_checked_against_the_ad_and_the_cv():
    result = score(answer([req("Python"), req("Vue.js", match="no"), req("Docker"), req("teamwork")]),
                             PY_AD, KNOWN)
    assert [r["requirement"] for r in result["requirements"]] == ["Python", "Docker"]  # no Vue in the ad
    assert [r["match"] for r in result["requirements"]] == ["yes", "similar"]  # Docker isn't in the CV
    cpp = score(answer([req("C# programming (similar to C++)"), req("Git"), req(".NET", False, "similar")]),
                          CSHARP_AD, grounding.cv_technologies(CPP_CV))
    assert [r["match"] for r in cpp["requirements"]] == ["no", "yes", "no"]  # C# is not C++


def blocker(kind, evidence):
    return {"kind": kind, "evidence": evidence}


def test_blockers_count_only_when_the_program_confirms_them():
    met = [req("Python"), req("SQL"), req("Django"), req("Docker")]

    def ceiling(kind, evidence):  # the ad says it: the quote test is its own
        ad = replace(PY_AD, description=f"{PY_AD.description} {evidence}")
        return score(answer(met, [blocker(kind, evidence)]), ad, KNOWN | {"Django", "Docker"})["counted"]["cap"]

    assert ceiling("experience", "We are not looking for a finished expert") is None
    assert ceiling("experience", "0-3 years of experience, graduates welcome") is None
    assert ceiling("experience", "minimálně 3 roky praxe") == 4
    assert ceiling("experience", "Senior Backend Developer") == 4
    assert ceiling("spoken language", "Angličtina minimálně na úrovni B2") is None  # the settings say B2
    assert ceiling("spoken language", "Czech or Slovak – advanced level") == 5  # Czech B1 in the settings
    assert ceiling("spoken language", "Fluent German") == 5
    assert ceiling("location", "Time zone: CET (+/- 3 hours)") is None
    assert ceiling("location", "Office in Praha 7") is None
    assert ceiling("location", "Remote: Brazil only") == 3
    assert ceiling("residency", "EU citizenship required") == 2
    assert ceiling("residency", "Must love dogs") is None


def test_soft_skills_and_years_are_not_requirements():
    result = score(answer([req("Python"), req("teamwork and communication", match="no"),
                           req("Self-organization", match="no"), req("3+ years of experience", match="no"),
                           req("SQL"), req("English communication (B2)", match="no")]), PY_AD, KNOWN)
    assert [r["requirement"] for r in result["requirements"]] == ["Python", "SQL", "English communication (B2)"]


def test_spoken_language_requirements_follow_the_settings():
    result = score(answer([req("English intermediate", match="no"), req("Czech advanced", False, "yes"),
                           req("Python"), req("German", False, "yes")]), PY_AD, KNOWN)
    assert [r["match"] for r in result["requirements"]] == ["yes", "no", "yes", "no"]


def test_a_must_have_language_not_in_the_cv_caps_the_score():
    prusa = Job(url="i", source="junior.guru", title="Integrační vývojář", company="P", city="Praha", published="",
                description="Must-have: Znalost programování v Pythonu, Git. Linux, C.")
    result = score(answer([req("Python programming", match="no"), req("Git"), req("Linux", False)]), prusa,
                   {"C/C++", "Git", "Linux"})
    assert result["counted"]["cap"] == 4
    assert result["risks"] == ["Must-have language Python is not in your CV (score at most 4)"]
    nice = score(answer([req("Python", False, "no"), req("Git"), req("Linux")]), prusa, {"C/C++", "Git", "Linux"})
    assert nice["counted"]["cap"] is None  # a nice-to-have language doesn't cap


def test_czech_word_forms_count():
    czech = ("Must-have: Znalost programování v\xa0Pythonu, zkušenosti s\xa0používáním Gitu, práce s Dockerem, "
             "Linuxovým shellem, programování v\xa0Céčku a Javou.")
    assert {"Python", "Git", "Docker", "Linux", "C/C++", "Java"} <= grounding.technologies(czech)
    assert grounding.technologies("zkušenost s JavaScriptem") & {"Java", "JavaScript"} == {"JavaScript"}
    assert grounding.technologies("Pracujeme s daty a reporty.") == set()  # ordinary Czech words stay words


def test_a_blocker_must_quote_the_ad():
    ad = Job(url="q", source="Jobicy", title="Junior Developer", company="A", city="", published="",
             description="Python, SQL, Git. We need at least 3 years of commercial experience. English B2.")
    met = [req("Python"), req("SQL"), req("Git")]
    quoted = score(answer(met, [blocker("experience", "at least 3 years of commercial experience")]), ad, KNOWN)
    assert quoted["counted"]["cap"] == 4
    guessed = score(answer(met, [blocker("spoken language", "No explicit English requirement, but the context "
                                                            "implies native or fluent proficiency")]), ad, KNOWN)
    assert guessed["counted"]["cap"] is None and guessed["blockers"] == []  # the model's guess, not the ad's words
