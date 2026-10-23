from dataclasses import replace

from job_finder import grounding
from job_finder.settings import Settings
from job_finder.sources import Job

S = Settings(cv_path="cv.md", skills=["Python"], main_skill="Python", city="Praha", remote=True,
             levels=["intern", "junior"], languages={"English": "B2", "Czech": "B1"}, education="studying",
             experience="none", areas=["Backend", "Data / analytics"])
KNOWN = {"Python", "SQL", "FastAPI", "Git"}
CPP_CV = "Junior developer. Skills: C++17, C, CMake, Git, Linux"
AD = Job(url="p", source="Jobicy", title="Junior Python Developer", company="A", city="Prague", published="",
         description="Required: Python, SQL. Docker is a plus. English B2. Hybrid, Prague office.")
CSHARP_AD = Job(url="u", source="junior.guru", title="Junior C# Developer", company="A", city="Prague",
                published="2026-10-20", description="We build web apps in C# and .NET with SQL Server. Git is a plus.")


def skill(name, match="yes"):
    return {"skill": name, "match": match}


def facts(**overrides):
    """What the model takes out of an ad (spec section 21.2)."""
    base = {"areas": ["Backend"], "seniority": "junior", "min_years": 0, "degree": "none", "students_welcome": False,
            "languages": [{"language": "English", "level": "B2"}], "workplace": "hybrid", "place": "Prague",
            "must_have": [skill("Python"), skill("SQL")], "nice_to_have": [skill("Docker", "no")],
            "about": "Backend services in Python."}
    return {**base, **overrides}


def verdict(extraction, job=AD, known=KNOWN, s=S):
    return grounding.verdict(extraction, job, known, s)


def condition(result, name):
    return next(c for c in result["conditions"] if c["name"] == name)


def with_text(text, job=AD):
    return replace(job, description=f"{job.description} {text}")


def test_technologies_are_found_strictly():
    assert grounding.technologies("C# and .NET, SQL") == {"C#/.NET", "SQL"}
    assert "C/C++" in grounding.technologies("C++17")
    assert "C/C++" not in grounding.technologies("Junior C# Developer")  # C# is not C
    assert grounding.technologies("Our R&D team will go to market, grade C.") == set()
    assert grounding.technologies("2+ years of experience, fluent English, a degree") == set()  # not technologies


def test_facts_tell_the_model_what_the_ad_names():
    known = grounding.cv_technologies(CPP_CV)
    assert "C/C++" in known and "C#/.NET" not in known
    text = grounding.facts(CSHARP_AD, known)
    assert "C#/.NET" in text.split("Not in the CV:")[1]
    assert "Git" in text.split("Not in the CV:")[0].split("in the candidate's CV:")[1]
    assert "C/C++" not in text  # the CV's own languages are not "named in the ad"


def test_facts_when_the_ad_names_no_known_technology():
    vague = Job(url="v", source="Jobicy", title="Junior Developer", company="A", city="", published="",
                description="Join our friendly team and grow with us.")
    assert "no known technologies" in grounding.facts(vague, {"Python"})


def test_czech_word_forms_count():
    czech = ("Must-have: Znalost programování v\xa0Pythonu, zkušenosti s\xa0používáním Gitu, práce s Dockerem, "
             "Linuxovým shellem, programování v\xa0Céčku a Javou.")
    assert {"Python", "Git", "Docker", "Linux", "C/C++", "Java"} <= grounding.technologies(czech)
    assert grounding.technologies("zkušenost s JavaScriptem") & {"Java", "JavaScript"} == {"JavaScript"}
    assert grounding.technologies("Pracujeme s daty a reporty.") == set()  # ordinary Czech words stay words


def test_a_strong_fit():
    result = verdict(facts())
    # must-have 2 of 2 (weight 2), nice-to-have 0 of 1 (weight 0.5): 4 of 4.5 = 0.89
    assert (result["verdict"], result["score"]) == ("Strong fit", 8)
    assert result["reason"] == "2 of 2 must-haves · 0 of 1 nice-to-haves · all conditions met"
    assert all(c["ok"] for c in result["conditions"])
    assert [c["name"] for c in result["conditions"]] == ["Degree", "Experience", "Level", "Language", "Location",
                                                         "Area"]
    assert (result["have"], result["missing"], result["risks"]) == (["Python", "SQL"], ["Docker"], [])
    assert result["extraction"] == facts() and result["about"] == "Backend services in Python."


def test_skills_set_the_band():
    assert verdict(facts(nice_to_have=[skill("Docker")]), known=KNOWN | {"Docker"})["score"] == 10
    assert verdict(facts(nice_to_have=[skill("Docker")]))["score"] == 9  # not in the CV: at best similar
    half = verdict(facts(must_have=[skill("Python"), skill("Django", "no")], nice_to_have=[]), with_text("Django"))
    assert (half["verdict"], half["score"]) == ("Worth a try", 6)  # 2 of 4
    few = facts(must_have=[skill("Python"), skill("Django", "no"), skill("Kubernetes", "no"), skill("Go", "no")],
                nice_to_have=[])
    result = verdict(few, with_text("Django, Kubernetes, Go"))
    assert (result["verdict"], result["score"], result["reason"]) == ("Stretch", 4, "1 of 4 must-haves")


def test_no_concrete_requirements():
    result = verdict(facts(must_have=[], nice_to_have=[]), replace(AD, title="Junior Developer"))
    assert (result["verdict"], result["score"]) == ("Worth a try", 6)
    assert result["reason"] == "The ad names few concrete requirements: read it before applying"


def test_a_required_degree_rules_out():
    master = facts(degree="master")
    result = verdict(master, with_text("An MSc in Mathematics is required."))
    assert (result["verdict"], result["score"], result["reason"]) == ("Out of reach", 2, "Requires a Master's degree")
    assert condition(result, "Degree") == {"name": "Degree", "ok": False, "reason": "Requires a Master's degree",
                                           "detail": "Master's degree required · you: studying, no degree yet"}
    assert condition(verdict(master), "Degree")["ok"]  # the ad never says it: the model's guess
    assert condition(verdict(master, with_text("Vyžadujeme Ing. titul.")), "Degree")["ok"] is False  # Czech master
    bachelor = facts(degree="bachelor")
    assert not condition(verdict(bachelor, with_text("VŠ vzdělání")), "Degree")["ok"]
    welcome = facts(degree="bachelor", students_welcome=True)
    assert condition(verdict(welcome, with_text("A university degree, students welcome")), "Degree")["ok"]
    assert condition(verdict(master, with_text("MSc required"), s=replace(S, education="master")), "Degree")["ok"]


def test_years_of_experience():
    three = facts(min_years=3)
    result = verdict(three, with_text("3+ years of commercial experience"))
    assert (result["verdict"], result["reason"]) == ("Out of reach", "Requires 3+ years of experience")
    assert condition(result, "Experience")["detail"] == "3+ years · you: none"
    assert condition(verdict(three), "Experience")["ok"]  # no years in the ad: the model's guess
    assert condition(verdict(three, with_text("praxe 3 roky")), "Experience")["ok"] is False  # Czech
    two_years = replace(S, experience="1-2")
    assert condition(verdict(three, with_text("3+ years"), s=two_years), "Experience")["ok"]  # one year short is ok
    assert condition(verdict(facts(min_years=1), with_text("1 year")), "Experience")["ok"]


def test_the_level_of_the_role():
    untitled = replace(AD, title="Python Developer")  # the title names no level: the model's word counts
    assert not condition(verdict(facts(seniority="senior"), untitled), "Level")["ok"]
    assert condition(verdict(facts(seniority="mid"), untitled), "Level")["ok"]  # one step up is worth a try
    director = replace(AD, title="Engineering Director - Business Data")
    result = verdict(facts(seniority="junior"), director)
    assert (result["verdict"], result["reason"]) == ("Out of reach", "Lead role")
    assert condition(result, "Level")["detail"] == "Lead · you: intern, junior"
    senior = replace(AD, title="Senior Backend Developer (.NET)")
    assert not condition(verdict(facts(), senior), "Level")["ok"]
    welcome = replace(AD, title="Junior Developer (Mid/Senior welcome)")
    assert condition(verdict(facts(seniority="senior"), welcome), "Level")["ok"]  # the title says junior
    students = replace(AD, title="Product Integration Specialist (pro studenty VŠ)")
    assert condition(verdict(facts(seniority="not stated"), students), "Level")["detail"] == "Not stated"


def test_spoken_languages():
    czech = facts(languages=[{"language": "Czech", "level": "C1"}])
    result = verdict(czech)
    assert (result["verdict"], result["reason"]) == ("Out of reach", "Requires Czech C1")
    assert condition(result, "Language")["detail"] == "Czech C1 · you: B1"
    assert condition(verdict(facts(languages=[{"language": "English", "level": "C1"}])), "Language")["ok"]  # B2
    assert condition(verdict(facts(languages=[{"language": "english", "level": "not stated"}])), "Language")["ok"]
    german = verdict(facts(languages=[{"language": "German", "level": "not stated"}]))
    assert condition(german, "Language")["detail"] == "German · you: not listed"
    assert condition(verdict(facts(languages=[])), "Language")["detail"] == "Not asked"


def test_the_place_of_work():
    assert condition(verdict(facts(workplace="remote", place="Europe")), "Location")["ok"]
    us = verdict(facts(workplace="remote", place="the US"))
    assert (us["verdict"], us["reason"]) == ("Out of reach", "Remote only for the US")
    assert not condition(verdict(facts(workplace="office", place="Brno")), "Location")["ok"]
    assert condition(verdict(facts(workplace="office", place="Praha 7")), "Location")["ok"]
    office_wanted = replace(S, remote=False)
    assert not condition(verdict(facts(workplace="remote", place=""), s=office_wanted), "Location")["ok"]
    assert condition(verdict(facts(workplace="not stated", place="")), "Location")["detail"] == "Not stated"


def test_another_area_is_kept_aside():
    qa = verdict(facts(areas=["QA / testing"]))
    assert (qa["verdict"], qa["score"], qa["reason"]) == ("Other area", 3, "QA / testing isn't one of your areas")
    assert condition(verdict(facts(areas=["Other IT"])), "Area")["ok"]
    assert verdict(facts(areas=["Not IT"]))["reason"] == "Not an IT job"
    assert condition(verdict(facts(areas=["Full-stack"])), "Area")["ok"]  # Backend covers it
    frontend = replace(S, areas=["Full-stack"])
    assert condition(verdict(facts(areas=["Frontend"]), s=frontend), "Area")["ok"]
    # A job between two areas fits if one of them is yours (Python integrations of 3D printers)
    mixed = verdict(facts(areas=["Embedded / hardware", "Backend"]))
    assert condition(mixed, "Area") == {"name": "Area", "ok": True, "detail": "Embedded / hardware, Backend",
                                        "reason": ""}
    assert condition(verdict({**facts(), "area": "Backend"} | {"areas": []}), "Area")["ok"]  # an older answer
    both = verdict(facts(areas=["QA / testing"], degree="phd"), with_text("PhD required"))
    assert (both["verdict"], both["score"]) == ("Out of reach", 2)  # a rule-out comes first
    two = verdict(facts(degree="phd", seniority="senior"), replace(with_text("PhD required"), title="Developer"))
    assert two["score"] == 1


def test_another_main_language_is_a_stretch():
    known = grounding.cv_technologies(CPP_CV)
    result = verdict(facts(must_have=[skill("C#", "no"), skill("Git")], nice_to_have=[]), CSHARP_AD, known)
    assert (result["verdict"], result["score"]) == ("Stretch", 4)
    assert result["reason"] == "Main language C#/.NET isn't in your CV"


def test_skills_are_checked_against_the_ad_and_the_cv():
    result = verdict(facts(must_have=[skill("Python"), skill("Vue.js"), skill("teamwork"), skill("3+ years Python"),
                                      skill("Django (has FastAPI)")], nice_to_have=[]), with_text("Django"))
    assert [(s["skill"], s["match"]) for s in result["must"]] == [("Python", "yes"),
                                                                  ("Django (has FastAPI)", "similar")]
    known = grounding.cv_technologies(CPP_CV)
    cpp = verdict(facts(must_have=[skill("C# programming (similar to C++)"), skill("Git")]), CSHARP_AD, known)
    assert [s["match"] for s in cpp["must"]] == ["no", "yes"]  # C# is not C++


def test_technologies_in_the_title_are_must_haves():
    sarvify = replace(AD, title="Intern - HTML/CSS JS Python", description="Python, REST APIs, Git.")
    result = verdict(facts(must_have=[skill("Python"), skill("Git")], nice_to_have=[]), sarvify)
    assert [(s["skill"], s["match"]) for s in result["must"]] == [
        ("Python", "yes"), ("Git", "yes"), ("JavaScript", "no"), ("HTML/CSS", "no")]  # the model left them out
    assert result["verdict"] == "Worth a try"


def test_languages_only_welcomed_still_are_the_jobs_languages():
    fnz = replace(AD, title="Graduate Analyst Developer", description="Znalost C#, Java nebo C++.")
    result = verdict(facts(must_have=[], nice_to_have=[skill("C#", "no"), skill("Java", "no"), skill("C++", "no")]),
                     fnz)
    assert (result["verdict"], result["score"]) == ("Stretch", 4)
    assert result["reason"] == "Main language Java, C#/.NET, C/C++ isn't in your CV"


def test_markdown_is_taken_out_of_the_about_line():
    assert verdict(facts(about="Builds **Python** services with `FastAPI`."))["about"] == \
        "Builds Python services with FastAPI."


def test_the_ads_languages_count_even_when_the_model_lists_cv_skills():
    emetlab = replace(AD, title="Junior Software Engineer",
                      description="You write Python, C#, TypeScript or JavaScript. Networking and tests.")
    known = grounding.cv_technologies(CPP_CV)
    # The model listed what the CV has, not what the ad asks for
    result = verdict(facts(must_have=[skill("Git"), skill("Networking (TCP/IP sockets)", "similar")],
                           nice_to_have=[]), emetlab, known)
    assert (result["verdict"], result["score"]) == ("Stretch", 4)
    assert result["reason"] == "Main language Python, C#/.NET, JavaScript, TypeScript isn't in your CV"
    assert verdict(facts(), emetlab)["verdict"] != "Stretch"  # Python is in this CV


def test_other_it_is_no_wildcard_next_to_another_area():
    result = verdict(facts(areas=["Machine learning / AI", "Other IT"]))
    assert (result["verdict"], result["reason"]) == ("Other area", "Machine learning / AI isn't one of your areas")
