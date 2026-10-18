import json
from datetime import date, timedelta

import pytest
import requests

from job_finder import config, uradprace


def item(portal_id, code="25120", region="Kraj/19", typ="adrprov", obec=None, okresy=None, salary_from=60000,
         salary_to=None, employer="ACME s.r.o.", description="Python a SQL, programátor", posted="2026-10-10",
         workplace_obec=None):
    """One vacancy as the labour office file writes it; with region: an address that also teaches its obec/okres;
    with workplace_obec: an address that names only the municipality, no region."""
    place = {"typMistaVykonuPrace": {"id": f"TypMistaVykonuPrace/{typ}"}, "obec": {"id": obec} if obec else None,
             "okresy": [{"id": code} for code in okresy] if okresy else None, "pracoviste": []}
    if region:
        place["pracoviste"] = [{"nazev": employer, "adresa": {
            "kraj": {"id": region}, "obec": {"id": f"Obec/{portal_id}"}, "okres": {"id": f"Okres/{portal_id}"}}}]
    elif workplace_obec:
        place["pracoviste"] = [{"nazev": employer, "adresa": {"kraj": None, "obec": {"id": workplace_obec}}}]
    return {"portalId": portal_id, "profeseCzIsco": {"id": f"CzIsco/{code}"},
            "pozadovanaProfese": {"cs": f"Job {portal_id}"},
            "zamestnavatel": {"nazev": employer} if employer else None,
            "datumVlozeni": f"{posted}T00:00:00.000Z",
            "upresnujiciInformace": {"cs": description} if description else None,
            "mesicniMzdaOd": salary_from, "mesicniMzdaDo": salary_to, "mistoVykonuPrace": place}


def file_text(items):
    return json.dumps({"polozky": items}, ensure_ascii=False, indent=2)


class FakeResponse:
    def __init__(self, status_code, text="", headers=None):
        self.status_code, self.text, self.headers = status_code, text, headers or {}
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        self.closed = True

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))

    def iter_content(self, size):
        data = self.text.encode("utf-8")
        for start in range(0, len(data), 5):  # tiny pieces: a letter like "á" is split between two of them
            yield data[start:start + 5]


def answer(response):
    return lambda url, headers=None, **kwargs: response


@pytest.fixture(autouse=True)
def cache(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "UP_CACHE", tmp_path / "cache" / "uradprace.json")
    monkeypatch.setattr(uradprace, "MIN_VACANCIES", 1)  # the real file has ~40 000; the test files a few


def test_iter_items_across_chunk_borders():
    text = file_text([item(1), item(2, employer=None), item(3, description=None)])
    for size in (1, 7, 100, len(text)):
        chunks = [text[start:start + size] for start in range(0, len(text), size)]
        assert [vacancy["portalId"] for vacancy in uradprace.iter_items(chunks)] == [1, 2, 3]
    with pytest.raises(ValueError):
        list(uradprace.iter_items([text[:len(text) // 2]]))  # the file ended early
    with pytest.raises(ValueError):
        list(uradprace.iter_items(["<html><body>[]</body></html>"]))  # not the vacancy file


def test_broken_vacancy_does_not_fill_memory(monkeypatch):
    monkeypatch.setattr(uradprace, "MAX_ITEM", 2000)
    text = file_text([item(1)]).replace("]\n}", ', {"broken": tru' + "x" * 100_000 + "]}")
    read = []

    def chunks():
        for start in range(0, len(text), 500):
            read.append(start)
            yield text[start:start + 500]

    with pytest.raises(ValueError):
        list(uradprace.iter_items(chunks()))
    assert len(read) < 20  # gave up soon instead of keeping the rest of the file


def test_pick_it_resolves_regions():
    records = uradprace.pick_it([
        item(1),  # an address in Prague; it also tells that Obec/1 and Okres/1 are in Prague
        item(2, code="51310"),  # a waiter: not an IT job
        item(3, code="25140", region=None, typ="obec", obec="Obec/1"),
        item(4, code="3512", region=None, typ="okres", okresy=["Okres/99", "Okres/1"]),
        item(5, code="13300", region=None, typ="celaCR"),  # anywhere in Czechia
        item(6, code="25110", region=None, typ="neurceno"),  # the place is unknown: dropped
        item(7, region="Kraj/116"),
        item(8, region=None, workplace_obec="Obec/7"),  # the address names the municipality only
        item(9, region=None, typ="okres", okresy=["Okres/1", "Okres/7"]),  # districts in two regions
    ])
    assert {record["id"]: record["regions"] for record in records} == {
        1: ["Kraj/19"], 3: ["Kraj/19"], 4: ["Kraj/19"], 5: ["celaCR"], 7: ["Kraj/116"], 8: ["Kraj/116"],
        9: ["Kraj/116", "Kraj/19"]}


def test_jobs_for_city_fields_and_salary():
    copy = item(8, region="Kraj/116")
    copy["pozadovanaProfese"] = {"cs": "Job 7"}  # the same job as 7 at another workplace: shown once
    records = uradprace.pick_it([item(1, salary_from=75000, salary_to=110000),
                                 item(5, code="13300", region=None, typ="celaCR", employer=None),
                                 item(7, region="Kraj/116"), copy])
    prague = uradprace.jobs_for(records, "Praha")
    assert [job.url for job in prague] == ["https://up.gov.cz/volna-mista-v-cr#/volna-mista-detail/1",
                                           "https://up.gov.cz/volna-mista-v-cr#/volna-mista-detail/5"]
    job = prague[0]
    assert (job.source, job.title, job.company, job.city, job.published, job.description, job.salary) == (
        "Úřad práce", "Job 1", "ACME s.r.o.", "Prague", "2026-10-10", "Python a SQL, programátor",
        "75,000–110,000 CZK / month")
    assert prague[1].company == ""  # an employer that asked not to be named
    brno = uradprace.jobs_for(records, "Brno")
    assert [job.url[-1] for job in brno] == ["5", "7"] and {job.city for job in brno} == {"Brno region"}


def test_load_uses_cache_on_304_and_on_network_error():
    sent = []
    fresh = FakeResponse(200, file_text([item(1)]), {"ETag": "v1", "Last-Modified": "Sat, 17 Oct 2026"})
    assert [record["description"] for record in uradprace.load(answer(fresh))] == ["Python a SQL, programátor"]
    assert fresh.closed

    def not_modified(url, headers=None, **kwargs):
        sent.append(headers)
        return FakeResponse(304)

    assert [record["id"] for record in uradprace.load(not_modified)] == [1]  # the saved selection
    assert sent[-1]["If-None-Match"] == "v1" and sent[-1]["If-Modified-Since"] == "Sat, 17 Oct 2026"

    def offline(url, headers=None, **kwargs):
        raise requests.ConnectionError("no network")

    assert [record["id"] for record in uradprace.load(offline)] == [1]
    config.UP_CACHE.unlink()
    with pytest.raises(requests.ConnectionError):
        uradprace.load(offline)  # nothing saved: an error, like any other site


def test_old_selection_is_not_used_forever():
    uradprace.load(answer(FakeResponse(200, file_text([item(1)]), {"ETag": "v1"})))
    saved = json.loads(config.UP_CACHE.read_text(encoding="utf-8"))
    saved["checked"] = (date.today() - timedelta(days=uradprace.STALE_DAYS + 1)).isoformat()
    config.UP_CACHE.write_text(json.dumps(saved), encoding="utf-8")
    with pytest.raises(requests.ConnectionError):  # days without an answer: the status line shows the error
        uradprace.load(lambda url, headers=None, **kwargs: (_ for _ in ()).throw(requests.ConnectionError("down")))
    uradprace.load(answer(FakeResponse(304)))  # the site answered "not changed": the selection is current again
    assert json.loads(config.UP_CACHE.read_text(encoding="utf-8"))["checked"] == date.today().isoformat()


def test_broken_file_keeps_old_cache():
    uradprace.load(answer(FakeResponse(200, file_text([item(1)]), {"ETag": "v1"})))
    text = file_text([item(2)])
    assert [record["id"] for record in uradprace.load(answer(FakeResponse(200, text[:len(text) // 2]))) ] == [1]
    sent = []
    uradprace.load(lambda url, headers=None, **kwargs: sent.append(headers) or FakeResponse(304))
    assert sent[0]["If-None-Match"] == "v1"  # the old selection is still the saved one


def test_too_few_vacancies_is_not_the_registry(monkeypatch):
    monkeypatch.setattr(uradprace, "MIN_VACANCIES", 2)
    uradprace.load(answer(FakeResponse(200, file_text([item(1), item(2)]), {"ETag": "v1"})))
    # An empty list or a maintenance page must not make every labour office job look taken down
    assert [r["id"] for r in uradprace.load(answer(FakeResponse(200, file_text([]), {"ETag": "v2"})))] == [1, 2]
    assert [r["id"] for r in uradprace.load(answer(FakeResponse(200, "<p>Údržba</p>", {"ETag": "v3"})))] == [1, 2]


def test_cache_write_failure_keeps_fresh_records(monkeypatch):
    def full_disk(data):
        raise OSError("no space left")

    monkeypatch.setattr(uradprace, "_write_cache", full_disk)
    assert [r["id"] for r in uradprace.load(answer(FakeResponse(200, file_text([item(1)]))))] == [1]


def test_bad_cache_is_ignored():
    config.UP_CACHE.parent.mkdir(parents=True)
    for bad in ("[1, 2]", '{"records": "x"}', '{"version": 1, "records": []}', "not json"):
        config.UP_CACHE.write_text(bad, encoding="utf-8")
        assert [r["id"] for r in uradprace.load(answer(FakeResponse(200, file_text([item(1)]))))] == [1]
