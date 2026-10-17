"""Job sources: four aggregators with open APIs."""
from __future__ import annotations

import csv
import io
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, fields
from datetime import datetime, timezone
from typing import TYPE_CHECKING

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

    def __post_init__(self):
        # API answers contain nulls: one such record must not break deduplication and saving to the database
        for field in fields(self):
            if getattr(self, field.name) is None:
                setattr(self, field.name, "")


def html_to_text(html: str | None) -> str:
    return BeautifulSoup(html or "", "html.parser").get_text("\n", strip=True)


def parse_juniorguru(text: str, city: str, remote: bool) -> list[Job]:
    """Only jobs in the chosen region (city) and, if remote is fine, remote ones."""
    jobs = []
    for row in csv.DictReader(io.StringIO(text)):
        # A region is more reliable than a name: a Prague district (e.g. "Háje") has no "Praha" in its name
        regions = [value for key, value in row.items() if key.startswith("locations_") and key.endswith("_region")]
        if city in regions:
            place = "Prague" if city == "Praha" else city
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
        ))
    return jobs


def parse_jobicy(data: dict) -> list[Job]:
    return [
        Job(
            url=item["url"], source="Jobicy", title=item["jobTitle"], company=item["companyName"],
            city=f"Remote: {item['jobGeo']}" if item.get("jobGeo") else "Remote",
            published=(item.get("pubDate") or "")[:10], description=html_to_text(item.get("jobDescription")),
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


def fetch_himalayas(keywords: list[str], level: str) -> list[Job]:
    """One search per keyword; the pages are shared so that there are at most HIMALAYAS_MAX_PAGES in all."""
    jobs = []
    pages = max(1, config.HIMALAYAS_MAX_PAGES // max(1, len(keywords)))
    first = True
    for keyword in keywords:
        for page in range(1, pages + 1):
            if not first:
                time.sleep(1)  # Himalayas rate-limits requests
            first = False
            params = {**config.HIMALAYAS_PARAMS, "q": keyword, "seniority": config.HIMALAYAS_SENIORITY[level],
                      "page": page}
            batch = parse_himalayas(_get(config.HIMALAYAS_URL, params).json())
            if not batch:
                break
            jobs += batch
    return jobs


def fetch_jobicy() -> list[Job]:
    return parse_jobicy(_get(config.JOBICY_URL, config.JOBICY_PARAMS).json())


def fetch_workingnomads() -> list[Job]:
    return parse_workingnomads(_get(config.WORKINGNOMADS_URL).json())


# Sources that list remote jobs only: not fetched when remote work is not fine
REMOTE_ONLY = ("Himalayas", "Jobicy", "Working Nomads")


def sources_for(s: Settings) -> list[tuple[str, Callable[[], list[Job]]]]:
    """The sources and how to fetch them for these settings; the order is the priority when removing duplicates."""
    return [
        ("junior.guru", lambda: fetch_juniorguru(s.city, s.remote)),
        ("Himalayas", lambda: fetch_himalayas(s.keywords, s.level)),
        ("Jobicy", fetch_jobicy),
        ("Working Nomads", fetch_workingnomads),
    ]


def _norm(text: str) -> str:
    return " ".join(text.lower().split())


def same_job_key(company: str, title: str) -> tuple[str, str]:
    """Key for "the same job": company and title, ignoring case and extra spaces."""
    return _norm(company), _norm(title)


def dedupe(fetched: dict[str, list[Job]]) -> dict[str, list[Job]]:
    """Remove repeats by "company + title"; the record from the source earlier in the dict stays."""
    seen = set()
    result = {}
    for name, jobs in fetched.items():
        result[name] = []
        for job in jobs:
            key = same_job_key(job.company, job.title)
            if key not in seen:
                seen.add(key)
                result[name].append(job)
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
