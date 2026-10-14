from job_finder import insights
from job_finder.insights import analyze, find

NAMES = ["AWS", "Azure", "GCP", "Kubernetes", "Docker", "Terraform", "Linux", "Git", "JavaScript", "TypeScript",
         "React", "Vue", "Angular", "Java", "Go", "Rust", "PHP", "Ruby", "Kotlin", "Swift", "Scala", "Django",
         "Flask", "FastAPI", "Redis"]


def test_aliases_map_to_one_requirement():
    assert find("Kubernetes (k8s) with Helm") == {"Kubernetes"}
    assert find("cloud platforms (AWS/GCP/Azure)") == {"AWS", "GCP", "Azure", "Cloud (any)"}


def test_c_sharp_is_not_c():
    assert find("C# / .NET") == {"C#/.NET"}
    assert find("ASP.NET Core") == {"C#/.NET"}
    assert find("C/C++ programming") == {"C/C++"}


def test_common_words_are_not_requirements():
    assert find("go-to-market strategy, R&D budget, Scrum Master role, solid understanding") == {"Agile/Scrum"}


def test_experience_phrases():
    assert "Experience 2+ years" in find("3+ years of professional experience")
    assert "Experience 2+ years" in find("commercial software development experience")


def test_analyze_counts_each_job_once_and_skips_cv_skills():
    evaluations = [
        {"have": ["Python backend"], "missing": ["AWS", "AWS Lambda", "commercial Python experience"]},
        {"have": [], "missing": ["AWS", "underwater basket weaving"]},
    ]
    result = analyze(evaluations, ["Python — main language"])
    assert result.total == 2
    assert result.in_cv == {"Python"}
    assert result.missing == [("AWS", 2), ("Experience 2+ years", 1)]
    assert result.required == [("AWS", 2, 0), ("Experience 2+ years", 1, 0), ("Python", 1, 1)]
    assert result.unknown == 1


def test_have_and_missing_in_one_job_count_once():
    result = analyze([{"have": ["Docker basics"], "missing": ["Docker in production"]}], [])
    assert result.required == [("Docker", 1, 1)]
    assert result.missing == [("Docker", 1)]


def test_missing_lists_and_skills_section_are_optional():
    result = analyze([{"score": 5}], [])
    assert (result.total, result.missing, result.required, result.unknown) == (1, [], [], 0)


def test_lists_are_cut_to_top():
    result = analyze([{"have": [], "missing": NAMES}], [])
    assert len(NAMES) == 25 and len(result.missing) == insights.TOP == 20
