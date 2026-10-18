"""Úřad práce ČR: IT vacancies of the chosen region from the labour office's open data (spec section 17.1).

The daily file has every vacancy registered in Czechia (~190 MB). It is read piece by piece, only IT jobs are kept,
and that selection is saved, so the file is downloaded again only when it changed."""
from __future__ import annotations

import codecs
import json
import logging
import re
from collections.abc import Iterable, Iterator

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
_SKIP = re.compile(r"[\s,]*")


def iter_items(chunks: Iterable[str]) -> Iterator[dict]:
    """The vacancies of the {"polozky": [...]} file one by one, from pieces of its text: never the whole file."""
    decoder = json.JSONDecoder()
    buffer, pos, started = "", 0, False
    for chunk in chunks:
        buffer = buffer[pos:] + chunk
        pos = 0
        if not started:
            start = buffer.find("[")
            if start < 0:
                continue
            pos, started = start + 1, True
        while True:
            pos = _SKIP.match(buffer, pos).end()
            if pos >= len(buffer):
                break
            if buffer[pos] == "]":
                return
            try:
                item, end = decoder.raw_decode(buffer, pos)
            except json.JSONDecodeError:
                break  # the vacancy goes on in the next piece
            yield item
            pos = end
    raise ValueError("the vacancy file ended early")


def _text(value) -> str:
    return ((value or {}).get("cs") or "").strip()


def _id(value) -> str:
    return (value or {}).get("id") or ""


def pick_it(items: Iterable[dict]) -> list[dict]:
    """IT vacancies with their region, as small records to save. Many vacancies name only a municipality or a
    district; which region that is, the addresses of all the other vacancies in the same file tell."""
    obce, okresy, picked = {}, {}, []
    for item in items:
        place = item.get("mistoVykonuPrace") or {}
        workplace_region = ""
        for workplace in place.get("pracoviste") or []:
            address = workplace.get("adresa") or {}
            region = _id(address.get("kraj"))
            if region:
                obce[_id(address.get("obec"))] = okresy[_id(address.get("okres"))] = region
                workplace_region = workplace_region or region
        code = _id(item.get("profeseCzIsco")).removeprefix("CzIsco/")
        title = _text(item.get("pozadovanaProfese"))
        if not code.startswith(IT_PREFIXES) or not title or not item.get("portalId"):
            continue
        anywhere = _id(place.get("typMistaVykonuPrace")).endswith(ANYWHERE)
        picked.append(({
            "id": item["portalId"], "title": title,
            "company": ((item.get("zamestnavatel") or {}).get("nazev") or "").strip(),
            "published": (item.get("datumVlozeni") or "")[:10],
            "description": _text(item.get("upresnujiciInformace")),
            "salary": sources.salary_text(item.get("mesicniMzdaOd"), item.get("mesicniMzdaDo"), "CZK", "monthly"),
            "region": ANYWHERE if anywhere else workplace_region,
        }, _id(place.get("obec")), [_id(okres) for okres in place.get("okresy") or []]))
    records = []
    for record, obec, districts in picked:
        record["region"] = (record["region"] or obce.get(obec)
                            or next((okresy[okres] for okres in districts if okres in okresy), ""))
        if record["region"]:  # an unknown place can't be matched to the chosen city
            records.append(record)
    return records


def _read_cache() -> dict | None:
    try:
        return json.loads(config.UP_CACHE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _write_cache(data: dict) -> None:
    config.UP_CACHE.parent.mkdir(parents=True, exist_ok=True)
    temporary = config.UP_CACHE.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    temporary.replace(config.UP_CACHE)  # a half-written file never replaces a good one


def load(get=requests.get) -> list[dict]:
    """The IT records: the file is downloaded only when it changed (otherwise the server answers 304). If the
    download fails or the file is broken, the saved selection is used; without one, the error goes up."""
    cache = _read_cache()
    headers = dict(sources.HEADERS)
    if cache:
        if cache.get("etag"):
            headers["If-None-Match"] = cache["etag"]
        if cache.get("modified"):
            headers["If-Modified-Since"] = cache["modified"]
    try:
        response = get(config.UP_URL, headers=headers, timeout=config.HTTP_TIMEOUT, stream=True)
        if response.status_code == 304 and cache:
            return cache["records"]
        response.raise_for_status()
        decoder = codecs.getincrementaldecoder("utf-8")()
        records = pick_it(iter_items(decoder.decode(piece) for piece in response.iter_content(CHUNK)))
    except Exception:
        if cache:
            log.exception("Úřad práce: download failed, using the saved selection")
            return cache["records"]
        raise
    _write_cache({"etag": response.headers.get("ETag", ""), "modified": response.headers.get("Last-Modified", ""),
                  "records": records})
    return records


def place(city: str) -> str:
    """How the place of a vacancy from the chosen city's region is shown."""
    return "Prague" if city == "Praha" else f"{city} region"


def jobs_for(records: list[dict], city: str) -> list[sources.Job]:
    region = CITY_REGIONS.get(city)
    return [sources.Job(url=config.UP_DETAIL_URL.format(record["id"]), source=SOURCE, title=record["title"],
                        company=record["company"], city=place(city), published=record["published"],
                        description=record["description"], salary=record["salary"])
            for record in records if record["region"] in (region, ANYWHERE)]


def fetch(city: str) -> list[sources.Job]:
    return jobs_for(load(), city)
