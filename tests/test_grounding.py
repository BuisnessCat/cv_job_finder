from job_finder import grounding
from job_finder.sources import Job

CSHARP_AD = Job(url="u", source="junior.guru", title="Junior C# Developer", company="A", city="Prague",
                published="2026-10-20", description="We build web apps in C# and .NET with SQL Server. Git is a plus.")
CPP_CV = "Junior developer. Skills: C++17, C, CMake, Git, Linux"


def evaluation(score=8, have=(), missing=(), risks=()):
    return {"score": score, "summary": "ok", "have": list(have), "missing": list(missing), "risks": list(risks)}


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


def test_check_drops_technologies_the_ad_does_not_name():
    python_ad = Job(url="p", source="Jobicy", title="Junior Python Developer", company="A", city="", published="",
                    description="Python, SQL and teamwork.")
    checked = grounding.check(evaluation(have=["Python", "Docker", "good communication"],
                                         missing=["React", "SQL window functions", "team player"]),
                              python_ad, {"Python"})
    assert checked["have"] == ["Python", "good communication"]  # Docker: the ad doesn't name it
    assert checked["missing"] == ["SQL window functions", "team player"]  # React: the ad doesn't name it


def test_check_moves_another_language_from_have_to_missing():
    checked = grounding.check(evaluation(score=4, have=["C# programming (similar to C++)", "Git"], missing=[".NET"]),
                              CSHARP_AD, grounding.cv_technologies(CPP_CV))
    assert checked["have"] == ["Git"]
    assert checked["missing"] == [".NET"]  # C# is already there as .NET: not added twice
    checked = grounding.check(evaluation(score=4, have=["C# programming"]), CSHARP_AD, {"C/C++"})
    assert checked["missing"] == ["C# programming"]


def test_another_main_language_in_the_title_caps_the_score():
    checked = grounding.check(evaluation(score=8), CSHARP_AD, {"C/C++", "Git"})
    assert checked["score"] == 3
    assert checked["risks"] == ["Main language: C#/.NET (not in your CV)"]
    assert grounding.check(evaluation(score=2), CSHARP_AD, {"C/C++"})["score"] == 2  # lower stays lower
    assert grounding.check(evaluation(score=8), CSHARP_AD, {"C#/.NET"})["score"] == 8


def test_language_check_spares_families_and_cvs_without_languages():
    ts = Job(url="t", source="Jobicy", title="TypeScript Developer", company="A", city="", published="",
             description="TypeScript, React")
    assert grounding.check(evaluation(score=7), ts, {"JavaScript"})["score"] == 7  # one family
    java = Job(url="j", source="Jobicy", title="Java Tester", company="A", city="", published="", description="")
    assert grounding.check(evaluation(score=6), java, {"SQL", "Testing"})["score"] == 6  # no languages in the CV
