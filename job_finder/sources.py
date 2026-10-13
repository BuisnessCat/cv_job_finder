"""Job sources: four aggregators with open APIs."""
import csv
import io
import logging
import time
from dataclasses import dataclass, fields
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

from job_finder import config

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


def parse_juniorguru(text: str) -> list[Job]:
    """Only jobs in Prague or remote: the other sources return remote jobs only anyway."""
    jobs = []
    for row in csv.DictReader(io.StringIO(text)):
        # A region is more reliable than a name: a Prague district (e.g. "Háje") has no "Praha" in its name
        regions = [value for key, value in row.items() if key.startswith("locations_") and key.endswith("_region")]
        if "Praha" in regions:
            city = "Prague"
        elif row.get("remote") == "True":
            city = "Remote"
        else:
            continue
        jobs.append(Job(
            url=row["url"], source="junior.guru", title=row["title"], company=row["company_name"],
            city=city, published=(row.get("first_seen_at") or "")[:10],
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


def fetch_juniorguru() -> list[Job]:
    # Decode ourselves: this does not depend on the response header and strips the BOM
    return parse_juniorguru(_get(config.JUNIORGURU_URL).content.decode("utf-8-sig"))


def fetch_himalayas() -> list[Job]:
    jobs = []
    for page in range(1, config.HIMALAYAS_MAX_PAGES + 1):
        if page > 1:
            time.sleep(1)  # Himalayas rate-limits requests
        batch = parse_himalayas(_get(config.HIMALAYAS_URL, {**config.HIMALAYAS_PARAMS, "page": page}).json())
        if not batch:
            break
        jobs += batch
    return jobs


def fetch_jobicy() -> list[Job]:
    return parse_jobicy(_get(config.JOBICY_URL, config.JOBICY_PARAMS).json())


def fetch_workingnomads() -> list[Job]:
    return parse_workingnomads(_get(config.WORKINGNOMADS_URL).json())


# Order is the priority when removing duplicates
SOURCES = [
    ("junior.guru", fetch_juniorguru),
    ("Himalayas", fetch_himalayas),
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


def fetch_all() -> tuple[dict[str, list[Job]], dict[str, str]]:
    """Fetch all sources: (jobs by source without duplicates, errors by source)."""
    fetched, errors = {}, {}
    for name, fetch in SOURCES:
        try:
            fetched[name] = fetch()
        except Exception as error:
            log.exception("Source %s failed to load", name)
            errors[name] = str(error)[:150]
    return dedupe(fetched), errors
