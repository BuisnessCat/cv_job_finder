from datetime import date

from job_finder.freshness import age_text, is_reposted, job_date, time_left_text, visible_rows

TODAY = date(2026, 10, 17)


def r(url, score=7, published="2026-10-15", first_seen="2026-10-15", title=None, company="ACME", city="Prague"):
    return {"url": url, "score": score, "published": published, "first_seen": first_seen,
            "title": title or f"Job {url}", "company": company, "city": city}


def urls(rows):
    return [row["url"] for row in rows]


def test_job_date_and_age():
    assert job_date("2026-10-15", "2026-09-10") == "2026-09-10"
    assert job_date("", "2026-09-10") == "2026-09-10" and job_date("", "") == ""
    assert [age_text(d, TODAY) for d in ("2026-10-17", "2026-10-16", "2026-10-12", "2026-10-20", "")] == [
        "today", "1 day ago", "5 days ago", "today", "—"]


def test_reposted_needs_more_than_two_days():
    assert is_reposted("2026-10-15", "2026-09-10")
    assert not is_reposted("2026-10-12", "2026-10-10")
    assert not is_reposted("", "2026-10-10") and not is_reposted("2026-10-10", "")


def test_search_is_plain_substring_over_title_company_location():
    rows = [r("a", title="C++ Developer"), r("b", company="Prague Labs (remote)"), r("c", city="Brno")]
    assert urls(visible_rows(rows, "c++", None, "Best", TODAY)) == ["a"]
    assert urls(visible_rows(rows, "(REMOTE)", None, "Best", TODAY)) == ["b"]
    assert urls(visible_rows(rows, "brno", None, "Best", TODAY)) == ["c"]


def test_freshness_uses_job_date_and_keeps_undated():
    rows = [r("fresh"), r("bumped", published="2026-10-16", first_seen="2026-09-01"),
            r("undated", published="", first_seen="")]
    assert urls(visible_rows(rows, "", 7, "Best", TODAY)) == ["fresh", "undated"]


def test_orders():
    rows = [r("old_best", score=9, published="2026-10-01", first_seen="2026-10-01"),
            r("new_ok", score=6, published="2026-10-16", first_seen="2026-10-16"),
            r("undated", score=8, published="", first_seen="")]
    assert urls(visible_rows(rows, "", None, "Best", TODAY)) == ["old_best", "undated", "new_ok"]
    assert urls(visible_rows(rows, "", None, "Newest", TODAY)) == ["new_ok", "old_best", "undated"]


def test_time_left():
    assert time_left_text(20.0, 2, 10) == ""
    assert time_left_text(30.0, 3, 213) == "~35 min left"  # 10 s per job, 210 left
    assert time_left_text(30.0, 3, 6) == "<1 min left"
