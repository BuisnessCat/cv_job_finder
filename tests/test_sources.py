from dataclasses import replace

import pytest

from job_finder import config, sources, uradprace
from job_finder.settings import Settings
from job_finder.sources import Job

JG_CSV = (
    "title,company_name,url,remote,first_seen_at,locations_0_name,locations_0_region,"
    "locations_1_name,locations_1_region,description_html\n"
    'Junior Python vývojář,Firma s.r.o.,https://www.jobs.cz/rpd/1/?utm_source=juniorguru,False,'
    '2026-10-12 00:00:00,Praha,Praha,,,"<p>Hledáme <b>Python</b> vývojáře</p>"\n'
    "Remote tester,Remote a.s.,https://example.com/2,True,2026-10-10 00:00:00,Brno,Brno,,,<p>Testování</p>\n"
    "Brno developer,Brno s.r.o.,https://example.com/3,False,2026-10-09 00:00:00,Brno,Brno,,,<p>Django</p>\n"
    "Two offices,Multi a.s.,https://example.com/4,False,2026-10-08 00:00:00,Ostrava,Ostrava,Háje,Praha,<p>SQL</p>\n"
    "Office job,Office s.r.o.,https://example.com/5,False,2026-10-07 00:00:00,,,,,\n"
)

HIMALAYAS = {"jobs": [
    {"title": "Junior Backend Developer", "companyName": "Acme",
     "guid": "https://himalayas.app/companies/acme/jobs/junior-backend", "pubDate": 1791876793,
     "locationRestrictions": [], "description": "<p>Python &amp; SQL</p>"},
    {"title": "Python Engineer", "companyName": "Beta",
     "guid": "https://himalayas.app/companies/beta/jobs/python", "pubDate": "1791876793",
     "locationRestrictions": ["Czechia", "Slovakia", "Poland", "Hungary"], "description": None},
]}

JOBICY = {"jobs": [
    {"url": "https://jobicy.com/jobs/1-python-dev", "jobTitle": "Python Developer", "companyName": "Gamma",
     "jobGeo": "Europe", "pubDate": "2026-10-13T02:48:27+00:00", "jobDescription": "<div><p>Django</p></div>"},
]}

WORKINGNOMADS = [
    {"url": "https://www.workingnomads.com/job/go/1/", "title": "Backend Developer", "company_name": "Delta",
     "category_name": "Development", "location": "Time zone: CET (+/- 3 hours)",
     "pub_date": "2026-10-08T12:54:14-04:00", "description": "<p>Python</p>"},
    {"url": "https://www.workingnomads.com/job/go/2/", "title": "Support Agent", "company_name": "Delta",
     "category_name": "Customer Success", "location": "", "pub_date": "2026-10-08T12:54:14-04:00",
     "description": "<p>Help</p>"},
]


class FakeResponse:
    def __init__(self, content=b"", data=None, text=""):
        self.content = content
        self._data = data
        self.text = text

    def raise_for_status(self):
        pass

    def json(self):
        return self._data


def make(url, source, company="ACME", title="Python Dev"):
    return Job(url=url, source=source, title=title, company=company, city="", published="2026-10-01",
               description="")


def test_parse_juniorguru():
    jobs = sources.parse_juniorguru(JG_CSV, "Praha", True)
    assert jobs[0] == Job(
        url="https://www.jobs.cz/rpd/1/?utm_source=juniorguru", source="junior.guru",
        title="Junior Python vývojář", company="Firma s.r.o.", city="Prague", published="2026-10-12",
        description="Hledáme\nPython\nvývojáře",
    )
    assert (jobs[1].city, jobs[1].published, jobs[1].description) == ("Remote", "2026-10-10", "Testování")


def test_parse_juniorguru_keeps_only_prague_or_remote():
    jobs = sources.parse_juniorguru(JG_CSV, "Praha", True)
    # Brno without remote and a job without places are dropped; Prague listed second (Háje district) stays
    assert [(job.url, job.city) for job in jobs] == [
        ("https://www.jobs.cz/rpd/1/?utm_source=juniorguru", "Prague"),
        ("https://example.com/2", "Remote"),
        ("https://example.com/4", "Prague"),
    ]


def test_parse_himalayas():
    jobs = sources.parse_himalayas(HIMALAYAS)
    assert jobs[0] == Job(
        url="https://himalayas.app/companies/acme/jobs/junior-backend", source="Himalayas",
        title="Junior Backend Developer", company="Acme", city="Remote", published="2026-10-13",
        description="Python & SQL",
    )
    assert jobs[1].city == "Remote (Czechia, Slovakia, Poland …)"
    assert jobs[1].published == "2026-10-13"
    assert jobs[1].description == ""


def test_parse_jobicy():
    assert sources.parse_jobicy(JOBICY) == [Job(
        url="https://jobicy.com/jobs/1-python-dev", source="Jobicy", title="Python Developer", company="Gamma",
        city="Remote: Europe", published="2026-10-13", description="Django",
    )]


def test_parse_workingnomads_keeps_only_development():
    assert sources.parse_workingnomads(WORKINGNOMADS) == [Job(
        url="https://www.workingnomads.com/job/go/1/", source="Working Nomads", title="Backend Developer",
        company="Delta", city="Remote: Time zone: CET (+/- 3 hours)", published="2026-10-08",
        description="Python",
    )]


def test_dedupe_keeps_higher_priority_source():
    fetched = {
        "junior.guru": [make("u1", "junior.guru")],
        "Himalayas": [make("u2", "Himalayas", company=" acme ", title="python  dev"),
                      make("u3", "Himalayas", title="Other")],
    }
    result = sources.dedupe(fetched)
    assert [job.url for job in result["junior.guru"]] == ["u1"]
    assert [job.url for job in result["Himalayas"]] == ["u3"]


def test_fetch_all_isolates_source_errors(monkeypatch):
    def broken():
        raise RuntimeError("timeout")

    monkeypatch.setattr(sources, "sources_for", lambda s: [
        ("junior.guru", lambda: [make("u1", "junior.guru")]),
        ("Jobicy", broken),
    ])
    fetched, errors = sources.fetch_all(SETTINGS)
    assert list(fetched) == ["junior.guru"]
    assert "timeout" in errors["Jobicy"]


def test_fetch_juniorguru_decodes_utf8_with_bom(monkeypatch):
    content = ("﻿" + JG_CSV).encode("utf-8")
    monkeypatch.setattr(sources.requests, "get", lambda *args, **kwargs: FakeResponse(content=content))
    assert sources.fetch_juniorguru("Praha", True)[0].title == "Junior Python vývojář"


def test_fetch_himalayas_pages_until_empty(monkeypatch):
    pages = {
        1: HIMALAYAS,
        2: {"jobs": [HIMALAYAS["jobs"][0] | {"guid": "https://himalayas.app/x"}]},
        3: {"jobs": []},
    }
    calls = []

    def fake_get(url, params=None, **kwargs):
        calls.append(params["page"])
        return FakeResponse(data=pages[params["page"]])

    monkeypatch.setattr(sources.requests, "get", fake_get)
    monkeypatch.setattr(sources.time, "sleep", lambda seconds: None)
    assert len(sources.fetch_himalayas("Python", ["junior"])) == 3
    assert calls == [1, 2, 3]


def test_fetch_himalayas_respects_max_pages(monkeypatch):
    calls = []

    def fake_get(url, params=None, **kwargs):
        calls.append(params["page"])
        return FakeResponse(data=HIMALAYAS)

    monkeypatch.setattr(sources.requests, "get", fake_get)
    monkeypatch.setattr(sources.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(config, "HIMALAYAS_MAX_PAGES", 2)
    sources.fetch_himalayas("Python", ["junior"])
    assert calls == [1, 2]


def test_parsers_tolerate_null_fields():
    # API answers contain nulls: one such record must not break a source or the whole refresh
    him = sources.parse_himalayas({"jobs": [
        {"title": None, "companyName": None, "guid": "https://himalayas.app/1", "pubDate": None,
         "locationRestrictions": None, "description": None}]})
    jobicy = sources.parse_jobicy({"jobs": [
        {"url": "https://jobicy.com/1", "jobTitle": "Dev", "companyName": None, "jobGeo": None, "pubDate": None,
         "jobDescription": None}]})
    nomads = sources.parse_workingnomads([
        {"url": "https://www.workingnomads.com/1", "title": "Ops", "company_name": None,
         "category_name": "Development", "location": None, "pub_date": None, "description": None}])
    assert [(j.title, j.company, j.city, j.published) for j in him + jobicy + nomads] == [
        ("", "", "Remote", ""), ("Dev", "", "Remote", ""), ("Ops", "", "Remote", "")]
    deduped = sources.dedupe({"Himalayas": him, "Jobicy": jobicy, "Working Nomads": nomads})
    assert sum(len(jobs) for jobs in deduped.values()) == 3


def test_same_job_key_ignores_case_and_spaces():
    assert sources.same_job_key(" ACME ", "Python  Dev") == sources.same_job_key("acme", "python dev")


SETTINGS = Settings(cv_path="cv.md", skills=["Python"], main_skill="Python", languages={"English": "B2"})


def test_juniorguru_filters_by_chosen_city():
    assert [(j.url, j.city) for j in sources.parse_juniorguru(JG_CSV, "Brno", True)] == [
        ("https://example.com/2", "Brno"), ("https://example.com/3", "Brno")]
    assert [(j.url, j.city) for j in sources.parse_juniorguru(JG_CSV, "Praha", False)] == [
        ("https://www.jobs.cz/rpd/1/?utm_source=juniorguru", "Prague"), ("https://example.com/4", "Prague")]


def test_himalayas_searches_main_skill_with_level_seniority(monkeypatch):
    calls = []

    def fake_get(url, params=None):
        calls.append(dict(params))
        return FakeResponse(data=HIMALAYAS)

    monkeypatch.setattr(sources, "_get", fake_get)
    monkeypatch.setattr(sources.time, "sleep", lambda seconds: None)
    sources.fetch_himalayas("C#/.NET", ["intern", "junior"])
    assert [(c["q"], c["page"]) for c in calls] == [("C#", page) for page in range(1, 11)]  # one search, 10 pages
    assert {c["seniority"] for c in calls} == {"Entry-level,Mid-level"}  # merged, no repeats, in order
    calls.clear()
    sources.fetch_himalayas("Kotlin Multiplatform", ["senior", "lead"])  # a skill typed by hand: searched as written
    assert {(c["q"], c["seniority"]) for c in calls} == {("Kotlin Multiplatform", "Senior,Manager")}


def test_himalayas_query_for_dictionary_names():
    pairs = [("C#/.NET", "C#"), ("C/C++", "C++"), ("CI/CD", "CI/CD"), ("HTML/CSS", "HTML"),
             ("Frontend (any)", "Frontend"), ("Cloud (any)", "Cloud"), ("Python", "Python"),
             ("Kotlin Multiplatform", "Kotlin Multiplatform")]
    assert [(skill, sources.himalayas_query(skill)) for skill, _ in pairs] == pairs


def test_still_fetched_follows_settings():
    s = replace(SETTINGS, city="Praha", remote=True)
    assert sources.still_fetched("junior.guru", "Prague", s) and sources.still_fetched("junior.guru", "Remote", s)
    assert not sources.still_fetched("junior.guru", "Prague", replace(s, city="Brno"))
    assert not sources.still_fetched("junior.guru", "Remote", replace(s, remote=False))
    assert sources.still_fetched("Jobicy", "Remote", s)
    assert not sources.still_fetched("Jobicy", "Remote", replace(s, remote=False))


def test_no_remote_skips_remote_sources(monkeypatch):
    def must_not_run(*args):
        raise AssertionError("a remote-only source was fetched")

    monkeypatch.setattr(sources, "fetch_juniorguru", lambda city, remote: [make("u1", "junior.guru")])
    monkeypatch.setattr(uradprace, "fetch", lambda city: [make("u2", "Úřad práce", title="Analyst")])  # office jobs
    for name in ("fetch_himalayas", "fetch_jobicy", "fetch_workingnomads", "fetch_remoteok", "fetch_wwr"):
        monkeypatch.setattr(sources, name, must_not_run)
    fetched, errors = sources.fetch_all(replace(SETTINGS, remote=False))
    assert {name: [j.url for j in jobs] for name, jobs in fetched.items()} == {
        "junior.guru": ["u1"], "Úřad práce": ["u2"], "Himalayas": [], "Jobicy": [], "Working Nomads": [],
        "Remote OK": [], "We Work Remotely": []}
    assert errors == {}


def test_salary_text():
    assert sources.salary_text(2000, 3000, "USD", "monthly") == "$2,000–3,000 / month"
    assert sources.salary_text("150000", 250000.0, "EUR", "yearly") == "€150,000–250,000 / year"
    assert sources.salary_text(None, 60000, "CZK", "annual") == "up to 60,000 CZK / year"
    assert sources.salary_text(40, None, "GBP", "hourly") == "from £40 / hour"
    assert sources.salary_text(None, None, "USD", "monthly") == ""
    assert sources.salary_text("n/a", 0, "USD", None) == ""
    assert sources.salary_text("inf", float("inf"), "USD", "monthly") == ""  # no crash on odd numbers
    assert sources.salary_text(3000, 2000, "USD", "monthly") == "$2,000–3,000 / month"  # given reversed


def test_parsers_read_salary():
    him = sources.parse_himalayas({"jobs": [HIMALAYAS["jobs"][0] | {
        "minSalary": 50000, "maxSalary": 70000, "currency": "USD", "salaryPeriod": "year"}]})
    jobicy = sources.parse_jobicy({"jobs": [JOBICY["jobs"][0] | {
        "salaryMin": 2000, "salaryMax": 3000, "salaryCurrency": "USD", "salaryPeriod": "monthly"}]})
    assert him[0].salary == "$50,000–70,000 / year" and jobicy[0].salary == "$2,000–3,000 / month"
    assert sources.parse_jobicy(JOBICY)[0].salary == ""  # no salary from the site: nothing shown


REMOTEOK = [
    {"legal": "API Terms of Service: Please link back to the URL on Remote OK"},
    {"id": "1", "position": "Python Developer", "company": "Epsilon", "location": "Europe",
     "date": "2026-10-15T10:00:00+00:00", "description": "<p>Python</p>", "url": "https://remoteok.com/remote-jobs/1",
     "salary_min": 60000, "salary_max": 90000},
    {"id": "2", "position": "Marketer", "company": "Zeta", "location": "", "date": None, "description": None,
     "url": "https://remoteok.com/remote-jobs/2", "salary_min": 0, "salary_max": 0},
]

WWR_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>We Work Remotely</title>
<item><title>Eta: Senior Python Engineer</title><region>Anywhere in the World</region>
<link>https://weworkremotely.com/remote-jobs/eta-python</link><pubDate>Thu, 15 Oct 2026 12:00:00 +0000</pubDate>
<description>&lt;p&gt;Django&lt;/p&gt;</description></item>
<item><title>No company here</title><link>https://weworkremotely.com/remote-jobs/x</link><pubDate>not a date</pubDate></item>
<item><title></title><link>https://weworkremotely.com/remote-jobs/y</link></item>
</channel></rss>"""


def test_parse_remoteok():
    jobs = sources.parse_remoteok(REMOTEOK)  # the first element (the terms) is not a job
    assert jobs[0] == Job(url="https://remoteok.com/remote-jobs/1", source="Remote OK", title="Python Developer",
                          company="Epsilon", city="Remote: Europe", published="2026-10-15", description="Python",
                          salary="$60,000–90,000 / year")
    assert len(jobs) == 2 and (jobs[1].city, jobs[1].published, jobs[1].salary) == ("Remote", "", "")


def test_parse_wwr():
    jobs = sources.parse_wwr(WWR_RSS)
    assert jobs[0] == Job(url="https://weworkremotely.com/remote-jobs/eta-python", source="We Work Remotely",
                          title="Senior Python Engineer", company="Eta", city="Remote: Anywhere in the World",
                          published="2026-10-15", description="Django")
    assert (jobs[1].company, jobs[1].title, jobs[1].city, jobs[1].published) == ("", "No company here", "Remote", "")
    assert len(jobs) == 2  # an item without a title is skipped


def test_fetch_wwr_reads_each_category_and_drops_repeats(monkeypatch):
    calls = []
    monkeypatch.setattr(sources, "_get", lambda url, params=None: calls.append(url) or FakeResponse(
        content=WWR_RSS.encode("utf-8")))  # bytes: the XML declaration decides the encoding
    monkeypatch.setattr(sources.time, "sleep", lambda seconds: None)
    assert len(sources.fetch_wwr()) == 2 and len(calls) == len(config.WWR_CATEGORIES) == 5


def test_sources_order_and_remote_flags(monkeypatch):
    called = []
    for name in ("fetch_juniorguru", "fetch_himalayas", "fetch_jobicy", "fetch_workingnomads", "fetch_remoteok",
                 "fetch_wwr"):
        monkeypatch.setattr(sources, name, lambda *args, n=name: called.append(n) or [])
    monkeypatch.setattr(uradprace, "fetch", lambda city: called.append(f"uradprace {city}") or [])
    fetched, errors = sources.fetch_all(SETTINGS)
    assert list(fetched) == ["junior.guru", "Úřad práce", "Himalayas", "Jobicy", "Working Nomads", "Remote OK",
                             "We Work Remotely"]  # the order is the priority when removing duplicates
    assert "uradprace Praha" in called


def test_still_fetched_uradprace():
    s = replace(SETTINGS, city="Praha", remote=False)
    assert "Úřad práce" in config.FULL_LIST_SOURCES  # the registry is complete: a missing job was taken down
    assert sources.still_fetched("Úřad práce", "Prague", s)
    assert not sources.still_fetched("Úřad práce", "Prague", replace(s, city="Brno"))
    assert sources.still_fetched("Úřad práce", "Brno region", replace(s, city="Brno"))
    assert not sources.still_fetched("Remote OK", "Remote", s)
    assert not sources.still_fetched("We Work Remotely", "Remote", s)


def test_dedupe_only_across_sources():
    # Within one source every job has its own link; the labour office titles are profession classes
    # ("Vývojáři softwaru"), so one company can have several different jobs with the same title
    fetched = {"Úřad práce": [make("u1", "Úřad práce", title="Vývojáři softwaru"),
                              make("u2", "Úřad práce", title="Vývojáři softwaru")],
               "Himalayas": [make("u3", "Himalayas", title="Vývojáři softwaru")]}
    result = sources.dedupe(fetched)
    assert [job.url for job in result["Úřad práce"]] == ["u1", "u2"] and result["Himalayas"] == []


def test_parse_remoteok_rejects_an_unexpected_answer():
    with pytest.raises(ValueError):  # e.g. a rate-limit message: not "no jobs", or every job would look gone
        sources.parse_remoteok({"error": "rate limited"})
