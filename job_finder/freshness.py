"""How fresh a job is, the Found filters and the time-left estimate (spec section 14). No Qt, no database."""
import math
from datetime import date

# (segment label, tooltip, days; None = any time)
FRESHNESS = [("7d", "Last 7 days", 7), ("14d", "Last 14 days", 14), ("30d", "Last 30 days", 30),
             ("All", "Any time", None)]
ORDERS = ["Best", "Newest"]
REPOST_DAYS = 2  # the site's date may move this much without the job counting as reposted


def _parse(day: str) -> date | None:
    try:
        return date.fromisoformat(day)
    except (TypeError, ValueError):
        return None


def job_date(published: str, first_seen: str) -> str:
    """The job's date for age, filters and sorting: the earlier of the site's date and when the app first saw it."""
    known = [day for day in (published, first_seen) if _parse(day)]
    return min(known) if known else ""


def age_days(day: str, today: date) -> int | None:
    """Days since a date; None if there is no valid date. A date in the future counts as today."""
    parsed = _parse(day)
    return None if parsed is None else max(0, (today - parsed).days)


def age_text(day: str, today: date) -> str:
    """"today", "1 day ago", "N days ago" or "—"."""
    days = age_days(day, today)
    if days is None:
        return "—"
    if days == 0:
        return "today"
    return "1 day ago" if days == 1 else f"{days} days ago"


def is_reposted(published: str, first_seen: str) -> bool:
    """The site shows the job as newer than the app has known it: its date moved more than REPOST_DAYS later."""
    site, seen = _parse(published), _parse(first_seen)
    return bool(site and seen) and (site - seen).days > REPOST_DAYS


def visible_rows(rows: list[dict], query: str, days: int | None, order: str, today: date) -> list[dict]:
    """Found rows that pass the search and freshness filters, in the chosen order ("Best" or "Newest")."""
    needle = query.strip().lower()
    shown = []
    for row in rows:
        if needle and needle not in f"{row['title']}\n{row['company']}\n{row['city']}".lower():
            continue
        age = age_days(job_date(row["published"], row.get("first_seen", "")), today)
        if days is not None and age is not None and age > days:
            continue
        shown.append(row)

    def key(row):
        day = job_date(row["published"], row.get("first_seen", ""))  # "" sorts below any date
        return (day, row["score"]) if order == "Newest" else (row["score"], day)

    return sorted(shown, key=key, reverse=True)


def time_left_text(elapsed: float, done: int, total: int) -> str:
    """"~K min left" from the average time per job so far (after three jobs), "<1 min left", or ""."""
    if done < 3:
        return ""
    left = elapsed / done * (total - done)
    return "<1 min left" if left < 60 else f"~{math.ceil(left / 60)} min left"
