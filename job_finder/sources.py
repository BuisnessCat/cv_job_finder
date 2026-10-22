"""Job sources: job boards with open APIs and feeds (the labour office's data is in uradprace.py)."""
from __future__ import annotations

import csv
import io
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, fields
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import TYPE_CHECKING
from urllib.parse import urlparse
from xml.etree import ElementTree

import requests
from bs4 import BeautifulSoup

from job_finder import config

if TYPE_CHECKING:  # settings imports db, which imports this module
    from job_finder.settings import Settings

log = logging.getLogger(__name__)
csv.field_size_limit(10_000_000)  # in case of very long descriptions in the junior.guru CSV
HEADERS = {"User-Agent": "job-finder/1.0 (personal desktop app)"}


@dataclass
class Job:
    url: str
    source: str
    title: str
    company: str
    city: str
    published: str  # YYYY-MM-DD
    description: str  # plain text
    salary: str = ""  # "$2,000–3,000 / month" when the site gives one

    def __post_init__(self):
        # API answers contain nulls: one such record must not break deduplication and saving to the database
        for field in fields(self):
            if getattr(self, field.name) is None:
                setattr(self, field.name, "")


def html_to_text(html: str | None) -> str:
    return BeautifulSoup(html or "", "html.parser").get_text("\n", strip=True)


SITE_NAMES = {"linkedin.com": "LinkedIn", "jobs.cz": "jobs.cz", "startupjobs.cz": "StartupJobs"}


def source_label(source: str, url: str) -> str:
    """Where a job was found, for the card. junior.guru mostly shows other sites' jobs and links straight to them
    (its description is a copy from there), so it names that site: "junior.guru (from LinkedIn)"."""
    host = (urlparse(url).hostname or "").removeprefix("www.")
    if source != "junior.guru" or not host or host == "junior.guru" or host.endswith(".junior.guru"):
        return source
    site = next((name for domain, name in SITE_NAMES.items() if host == domain or host.endswith("." + domain)),
                host)
    return f"junior.guru (from {site})"


def juniorguru_place(city: str) -> str:
    """How a junior.guru job from the chosen region shows its place: Praha as Prague."""
    return "Prague" if city == "Praha" else city


def parse_juniorguru(text: str, city: str, remote: bool) -> list[Job]:
    """Only jobs in the chosen region (city) and, if remote is fine, remote ones."""
    jobs = []
    for row in csv.DictReader(io.StringIO(text)):
        # A region is more reliable than a name: a Prague district (e.g. "Háje") has no "Praha" in its name
        regions = [value for key, value in row.items() if key.startswith("locations_") and key.endswith("_region")]
        if city in regions:
            place = juniorguru_place(city)
        elif remote and row.get("remote") == "True":
            place = "Remote"
        else:
            continue
        jobs.append(Job(
            url=row["url"], source="junior.guru", title=row["title"], company=row["company_name"],
            city=place, published=(row.get("first_seen_at") or "")[:10],
            description=html_to_text(row.get("description_html")),
        ))
    return jobs


CURRENCY_SIGNS = {"USD": "$", "EUR": "€", "GBP": "£"}
PERIODS = {"hour": "hour", "dai": "day", "day": "day", "week": "week", "month": "month", "year": "year",
           "annual": "year"}  # the start of a site's period word -> the word shown


def _amount(value) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError, OverflowError):  # "n/a", None, infinity
        return 0


def salary_text(low, high, currency, period) -> str:
    """A site's salary fields as one line: "$2,000–3,000 / month", "up to 60,000 CZK / year"; "" without amounts."""
    low, high = _amount(low), _amount(high)
    if not low and not high:
        return ""
    if low and high and low > high:
        low, high = high, low
    code = str(currency or "").upper()
    sign = CURRENCY_SIGNS.get(code, "")
    if low and high:
        text = f"{sign}{low:,}–{high:,}" if low != high else f"{sign}{low:,}"
    else:
        text = f"from {sign}{low:,}" if low else f"up to {sign}{high:,}"
    if code and not sign:
        text += f" {code}"
    unit = next((word for start, word in PERIODS.items() if str(period or "").lower().startswith(start)), "")
    return f"{text} / {unit}" if unit else text


def parse_himalayas(data: dict) -> list[Job]:
    jobs = []
    for item in data.get("jobs") or []:
        countries = item.get("locationRestrictions") or []
        city = "Remote"
        if countries:
            city += f" ({', '.join(map(str, countries[:3]))}{' …' if len(countries) > 3 else ''})"
        pub_date = item.get("pubDate")
        published = datetime.fromtimestamp(int(pub_date), timezone.utc).strftime("%Y-%m-%d") if pub_date else ""
        jobs.append(Job(
            url=item["guid"], source="Himalayas", title=item["title"], company=item["companyName"],
            city=city, published=published, description=html_to_text(item.get("description")),
            salary=salary_text(item.get("minSalary"), item.get("maxSalary"), item.get("currency"),
                               item.get("salaryPeriod")),
        ))
    return jobs


def parse_jobicy(data: dict) -> list[Job]:
    return [
        Job(
            url=item["url"], source="Jobicy", title=item["jobTitle"], company=item["companyName"],
            city=f"Remote: {item['jobGeo']}" if item.get("jobGeo") else "Remote",
            published=(item.get("pubDate") or "")[:10], description=html_to_text(item.get("jobDescription")),
            salary=salary_text(item.get("salaryMin"), item.get("salaryMax"), item.get("salaryCurrency"),
                               item.get("salaryPeriod")),
        )
        for item in data.get("jobs") or []
    ]


def parse_workingnomads(data: list) -> list[Job]:
    return [
        Job(
            url=item["url"], source="Working Nomads", title=item["title"], company=item["company_name"],
            city=f"Remote: {item['location']}" if item.get("location") else "Remote",
            published=(item.get("pub_date") or "")[:10], description=html_to_text(item.get("description")),
        )
        for item in data
        if item.get("category_name") == "Development"
    ]


def _get(url: str, params: dict | None = None) -> requests.Response:
    response = requests.get(url, params=params, headers=HEADERS, timeout=config.HTTP_TIMEOUT)
    response.raise_for_status()
    return response


def fetch_juniorguru(city: str, remote: bool) -> list[Job]:
    # Decode ourselves: this does not depend on the response header and strips the BOM
    return parse_juniorguru(_get(config.JUNIORGURU_URL).content.decode("utf-8-sig"), city, remote)


def himalayas_query(skill: str) -> str:
    """A search word for a skill: dictionary names like "HTML/CSS" or "Cloud (any)" become "HTML" and "Cloud"."""
    if skill in config.HIMALAYAS_QUERY:
        return config.HIMALAYAS_QUERY[skill]
    return skill.removesuffix(" (any)").split("/")[0].strip() or skill


def fetch_himalayas(main_skill: str, levels: list[str]) -> list[Job]:
    """One search by the main skill, up to HIMALAYAS_MAX_PAGES pages; the seniority of all chosen levels."""
    seniority = []
    for level, values in config.HIMALAYAS_SENIORITY.items():
        if level in levels:
            seniority += [value for value in values if value not in seniority]
    params = {**config.HIMALAYAS_PARAMS, "q": himalayas_query(main_skill),
              "seniority": ",".join(seniority)}
    jobs = []
    for page in range(1, config.HIMALAYAS_MAX_PAGES + 1):
        if page > 1:
            time.sleep(1)  # Himalayas rate-limits requests
        batch = parse_himalayas(_get(config.HIMALAYAS_URL, {**params, "page": page}).json())
        if not batch:
            break
        jobs += batch
    return jobs


def fetch_jobicy() -> list[Job]:
    return parse_jobicy(_get(config.JOBICY_URL, config.JOBICY_PARAMS).json())


def fetch_workingnomads() -> list[Job]:
    return parse_workingnomads(_get(config.WORKINGNOMADS_URL).json())


def parse_remoteok(data: list) -> list[Job]:
    """Remote OK's API answer: the first element is their terms, the rest are jobs."""
    if not isinstance(data, list):  # e.g. a rate-limit message: an error, not "no jobs" (they would all look gone)
        raise ValueError(f"unexpected answer: {str(data)[:100]}")
    jobs = []
    for item in data:
        if not isinstance(item, dict) or not item.get("position") or not item.get("url"):
            continue
        location = (item.get("location") or "").strip()
        jobs.append(Job(
            url=item["url"], source="Remote OK", title=item["position"], company=item.get("company"),
            city=f"Remote: {location}" if location else "Remote", published=(item.get("date") or "")[:10],
            description=html_to_text(item.get("description")),
            salary=salary_text(item.get("salary_min"), item.get("salary_max"), "USD", "yearly"),
        ))
    return jobs


def fetch_remoteok() -> list[Job]:
    return parse_remoteok(_get(config.REMOTEOK_URL).json())


def parse_wwr(xml_text: str | bytes) -> list[Job]:
    """A We Work Remotely RSS feed: the title is "Company: Position"."""
    jobs = []
    for item in ElementTree.fromstring(xml_text).iter("item"):
        link, heading = (item.findtext("link") or "").strip(), (item.findtext("title") or "").strip()
        if not link or not heading:
            continue
        company, _, title = heading.partition(": ")
        if not title:
            company, title = "", heading
        region = (item.findtext("region") or "").strip()
        try:
            published = parsedate_to_datetime(item.findtext("pubDate") or "").strftime("%Y-%m-%d")
        except (TypeError, ValueError):
            published = ""
        jobs.append(Job(url=link, source="We Work Remotely", title=title, company=company,
                        city=f"Remote: {region}" if region else "Remote", published=published,
                        description=html_to_text(item.findtext("description"))))
    return jobs


def fetch_wwr() -> list[Job]:
    """Several category feeds; a job listed in two of them is kept once."""
    jobs, seen = [], set()
    for index, category in enumerate(config.WWR_CATEGORIES):
        if index:
            time.sleep(1)
        for job in parse_wwr(_get(config.WWR_URL.format(category)).content):  # bytes: the XML says its encoding
            if job.url not in seen:
                seen.add(job.url)
                jobs.append(job)
    return jobs


# Sources that list remote jobs only: not fetched when remote work is not fine
REMOTE_ONLY = ("Himalayas", "Jobicy", "Working Nomads", "Remote OK", "We Work Remotely")


def still_fetched(source: str, city: str, s: Settings) -> bool:
    """Whether these settings still ask the source for such a job: only then does its absence mean it was taken down."""
    if source in REMOTE_ONLY:
        return s.remote
    if source == "junior.guru":
        return city == juniorguru_place(s.city) or (city == "Remote" and s.remote)
    if source == "Úřad práce":
        from job_finder import uradprace  # here, not at the top: uradprace itself uses this module
        return city == uradprace.place(s.city)
    return True


def sources_for(s: Settings) -> list[tuple[str, Callable[[], list[Job]]]]:
    """The sources and how to fetch them for these settings; the order is the priority when removing duplicates."""
    from job_finder import uradprace  # here, not at the top: uradprace itself uses this module
    return [
        ("junior.guru", lambda: fetch_juniorguru(s.city, s.remote)),
        ("Úřad práce", lambda: uradprace.fetch(s.city)),  # office jobs: fetched also when remote isn't fine
        ("Himalayas", lambda: fetch_himalayas(s.main_skill, s.levels)),
        ("Jobicy", fetch_jobicy),
        ("Working Nomads", fetch_workingnomads),
        ("Remote OK", fetch_remoteok),
        ("We Work Remotely", fetch_wwr),
    ]


def _norm(text: str) -> str:
    return " ".join(text.lower().split())


def same_job_key(company: str, title: str) -> tuple[str, str]:
    """Key for "the same job": company and title, ignoring case and extra spaces."""
    return _norm(company), _norm(title)


def dedupe(fetched: dict[str, list[Job]]) -> dict[str, list[Job]]:
    """Remove a job another source earlier in the dict already has ("company + title"). Within one source every
    job has its own link, and the labour office has many different jobs called e.g. "Vývojáři softwaru"."""
    seen = set()
    result = {}
    for name, jobs in fetched.items():
        result[name] = [job for job in jobs if same_job_key(job.company, job.title) not in seen]
        seen.update(same_job_key(job.company, job.title) for job in result[name])
    return result


def fetch_all(s: Settings) -> tuple[dict[str, list[Job]], dict[str, str]]:
    """Fetch all sources: (jobs by source without duplicates, errors by source).

    Without remote work the remote-only sources are not fetched; their empty lists make their old jobs inactive."""
    fetched, errors = {}, {}
    for name, fetch in sources_for(s):
        if not s.remote and name in REMOTE_ONLY:
            fetched[name] = []
            continue
        try:
            fetched[name] = fetch()
        except Exception as error:
            log.exception("Source %s failed to load", name)
            errors[name] = str(error)[:150]
    return dedupe(fetched), errors
