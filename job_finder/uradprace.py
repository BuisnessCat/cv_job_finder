"""Úřad práce ČR: IT vacancies of the chosen region from the labour office's open data (spec section 17.1).

The daily file has every vacancy registered in Czechia (~190 MB). It is read piece by piece, only IT jobs are kept,
and that selection is saved, so the file is downloaded again only when it changed."""
from __future__ import annotations

import codecs
import json
import logging
import re
from collections.abc import Iterable, Iterator
from datetime import date

import requests

from job_finder import config, sources

log = logging.getLogger(__name__)

SOURCE = "Úřad práce"
IT_PREFIXES = ("25", "351", "1330")  # CZ-ISCO: ICT specialists, ICT technicians, ICT managers
ANYWHERE = "celaCR"  # a vacancy for the whole of Czechia suits any region
# The app's cities (junior.guru regions) -> their kraj in the labour office data
CITY_REGIONS = {"Praha": "Kraj/19", "Brno": "Kraj/116", "Ostrava": "Kraj/132", "Plzeň": "Kraj/43",
                "Olomouc": "Kraj/124", "Liberec": "Kraj/78", "České Budějovice": "Kraj/35",
                "Hradec Králové": "Kraj/86", "Pardubice": "Kraj/94", "Zlín": "Kraj/141", "Jihlava": "Kraj/108",
                "Karlovy Vary": "Kraj/51", "Ústí nad Labem": "Kraj/60"}
CHUNK = 1 << 20
MAX_ITEM = 10 * 1024 * 1024  # one vacancy is ~5 KB: a "vacancy" this long means the file is broken
MIN_VACANCIES = 1000  # the real file has ~40 000: fewer means an empty answer or a maintenance page
STALE_DAYS = 3  # without an answer from the site for longer, the saved selection is not used and the error shows
CACHE_VERSION = 2
_SKIP = re.compile(r"[\s,]*")
_START = re.compile(r'"polozky"\s*:\s*\[')


def iter_items(chunks: Iterable[str]) -> Iterator[dict]:
    """The vacancies of the {"polozky": [...]} file one by one, from pieces of its text: never the whole file."""
    decoder = json.JSONDecoder()
    buffer, pos, started = "", 0, False
    for chunk in chunks:
        buffer = buffer[pos:] + chunk
        pos = 0
        if not started:
            start = _START.search(buffer)
            if not start:
                if len(buffer) > MAX_ITEM:
                    raise ValueError("not the vacancy file")
                continue
            pos, started = start.end(), True
        while True:
            pos = _SKIP.match(buffer, pos).end()
            if pos >= len(buffer):
                break
            if buffer[pos] == "]":
                return
            try:
                item, end = decoder.raw_decode(buffer, pos)
            except json.JSONDecodeError:
                if len(buffer) - pos > MAX_ITEM:
                    raise ValueError("a broken vacancy in the file") from None
                break  # the vacancy goes on in the next piece
            yield item
            pos = end
    raise ValueError("the vacancy file ended early" if started else "not the vacancy file")


def _text(value) -> str:
    return ((value or {}).get("cs") or "").strip()


def _id(value) -> str:
    return (value or {}).get("id") or ""


def pick_it(items: Iterable[dict]) -> list[dict]:
    """IT vacancies with their regions, as small records to save. Many vacancies name only a municipality or a
    district (or an address without its region); which region that is, the addresses of all the other vacancies
    in the same file tell."""
    obce, okresy, picked, count = {}, {}, [], 0
    for item in items:
        count += 1
        place = item.get("mistoVykonuPrace") or {}
        regions, places, districts = set(), [_id(place.get("obec"))], [_id(o) for o in place.get("okresy") or []]
        for workplace in place.get("pracoviste") or []:
            address = workplace.get("adresa") or {}
            region, obec, okres = _id(address.get("kraj")), _id(address.get("obec")), _id(address.get("okres"))
            if region:
                regions.add(region)
                obce[obec] = okresy[okres] = region
            else:
                places.append(obec)
                districts.append(okres)
        code = _id(item.get("profeseCzIsco")).removeprefix("CzIsco/")
        title = _text(item.get("pozadovanaProfese"))
        if not code.startswith(IT_PREFIXES) or not title or not item.get("portalId"):
            continue
        if _id(place.get("typMistaVykonuPrace")).endswith(ANYWHERE):
            regions = {ANYWHERE}
        picked.append(({
            "id": item["portalId"], "title": title,
            "company": ((item.get("zamestnavatel") or {}).get("nazev") or "").strip(),
            "published": (item.get("datumVlozeni") or "")[:10],
            "description": _text(item.get("upresnujiciInformace")),
            "salary": sources.salary_text(item.get("mesicniMzdaOd"), item.get("mesicniMzdaDo"), "CZK", "monthly"),
        }, regions, places, districts))
    if count < MIN_VACANCIES:
        raise ValueError(f"only {count} vacancies in the file")
    records = []
    for record, regions, places, districts in picked:
        regions = regions or {obce[obec] for obec in places if obec in obce}
        regions = regions or {okresy[okres] for okres in districts if okres in okresy}
        if regions:  # an unknown place can't be matched to the chosen city
            records.append({**record, "regions": sorted(regions)})
    return records


def _read_cache() -> dict | None:
    """The saved selection, or None if there is none or it isn't one this version wrote."""
    try:
        data = json.loads(config.UP_CACHE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("version") != CACHE_VERSION or not isinstance(data.get("records"), list):
        return None
    return data


def _write_cache(data: dict) -> None:
    config.UP_CACHE.parent.mkdir(parents=True, exist_ok=True)
    temporary = config.UP_CACHE.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    temporary.replace(config.UP_CACHE)  # a half-written file never replaces a good one


def _save(data: dict) -> None:
    try:
        _write_cache(data)
    except OSError:
        log.exception("Úřad práce: could not save the selection")  # the records are still used this time


def load(get=requests.get) -> list[dict]:
    """The IT records: the file is downloaded only when it changed (otherwise the server answers 304). If the
    download fails or the file is broken, the saved selection is used for a few days; after that, or without one,
    the error goes up and the status line shows it."""
    cache = _read_cache()
    today = date.today().isoformat()
    headers = dict(sources.HEADERS)
    if cache:
        if cache.get("etag"):
            headers["If-None-Match"] = cache["etag"]
        if cache.get("modified"):
            headers["If-Modified-Since"] = cache["modified"]
    try:
        with get(config.UP_URL, headers=headers, timeout=config.HTTP_TIMEOUT, stream=True) as response:
            if response.status_code == 304 and cache:
                _save({**cache, "checked": today})
                return cache["records"]
            response.raise_for_status()
            decoder = codecs.getincrementaldecoder("utf-8")()
            records = pick_it(iter_items(decoder.decode(piece) for piece in response.iter_content(CHUNK)))
            etag, modified = response.headers.get("ETag", ""), response.headers.get("Last-Modified", "")
    except Exception:
        if cache and (date.today() - date.fromisoformat(cache.get("checked") or "2000-01-01")).days <= STALE_DAYS:
            log.exception("Úřad práce: download failed, using the saved selection")
            return cache["records"]
        raise
    _save({"version": CACHE_VERSION, "etag": etag, "modified": modified, "checked": today, "records": records})
    return records


def place(city: str) -> str:
    """How the place of a vacancy from the chosen city's region is shown."""
    return "Prague" if city == "Praha" else f"{city} region"


def jobs_for(records: list[dict], city: str) -> list[sources.Job]:
    """Vacancies of the city's region (and for all of Czechia); exact copies (several places for one job) once."""
    region, jobs, seen = CITY_REGIONS.get(city), [], set()
    for record in records:
        copy = (record["company"], record["title"], record["description"], record["salary"])
        if (region in record["regions"] or ANYWHERE in record["regions"]) and copy not in seen:
            seen.add(copy)
            jobs.append(sources.Job(url=config.UP_DETAIL_URL.format(record["id"]), source=SOURCE,
                                    title=record["title"], company=record["company"], city=place(city),
                                    published=record["published"], description=record["description"],
                                    salary=record["salary"]))
    return jobs


def fetch(city: str) -> list[sources.Job]:
    return jobs_for(load(), city)
