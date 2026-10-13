from job_finder import config, sources
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
    def __init__(self, content=b"", data=None):
        self.content = content
        self._data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self._data


def make(url, source, company="ACME", title="Python Dev"):
    return Job(url=url, source=source, title=title, company=company, city="", published="2026-10-01",
               description="")


def test_parse_juniorguru():
    jobs = sources.parse_juniorguru(JG_CSV)
    assert jobs[0] == Job(
        url="https://www.jobs.cz/rpd/1/?utm_source=juniorguru", source="junior.guru",
        title="Junior Python vývojář", company="Firma s.r.o.", city="Prague", published="2026-10-12",
        description="Hledáme\nPython\nvývojáře",
    )
    assert (jobs[1].city, jobs[1].published, jobs[1].description) == ("Remote", "2026-10-10", "Testování")


def test_parse_juniorguru_keeps_only_prague_or_remote():
    jobs = sources.parse_juniorguru(JG_CSV)
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

    monkeypatch.setattr(sources, "SOURCES", [
        ("junior.guru", lambda: [make("u1", "junior.guru")]),
        ("Jobicy", broken),
    ])
    fetched, errors = sources.fetch_all()
    assert list(fetched) == ["junior.guru"]
    assert "timeout" in errors["Jobicy"]


def test_fetch_juniorguru_decodes_utf8_with_bom(monkeypatch):
    content = ("﻿" + JG_CSV).encode("utf-8")
    monkeypatch.setattr(sources.requests, "get", lambda *args, **kwargs: FakeResponse(content=content))
    assert sources.fetch_juniorguru()[0].title == "Junior Python vývojář"


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
    assert len(sources.fetch_himalayas()) == 3
    assert calls == [1, 2, 3]


def test_fetch_himalayas_respects_max_pages(monkeypatch):
    calls = []

    def fake_get(url, params=None, **kwargs):
        calls.append(params["page"])
        return FakeResponse(data=HIMALAYAS)

    monkeypatch.setattr(sources.requests, "get", fake_get)
    monkeypatch.setattr(sources.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(config, "HIMALAYAS_MAX_PAGES", 2)
    sources.fetch_himalayas()
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
