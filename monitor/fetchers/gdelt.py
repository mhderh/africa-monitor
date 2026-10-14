"""
Fetch articles from the GDELT DOC 2.0 API - a free index of news websites
worldwide. No key needed. Docs: https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/

GDELT only gives the headline (no description), so the keyword filter and
classifier work from the title alone for these articles.
GDELT asks for at most one request every 5 seconds; we make one per run.
"""

import time
from datetime import datetime, timezone

import requests

from monitor.fetchers.rss import TIMEOUT_SECONDS, USER_AGENT

API_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
LANGUAGES = {"English": "en", "French": "fr", "Arabic": "ar"}


def _or_group(words):
    """["a", "b c"] -> '(a OR "b c")'"""
    quoted = [f'"{w}"' if " " in w else w for w in words]
    return "(" + " OR ".join(quoted) + ")"


def _parse_date(seendate):
    """GDELT dates look like 20261014T183000Z."""
    try:
        return datetime.strptime(seendate, "%Y%m%dT%H%M%SZ").replace(
            tzinfo=timezone.utc).isoformat()
    except (TypeError, ValueError):
        return None


def fetch(options):
    """Run one GDELT search and return article dictionaries (see rss.py)."""
    params = {
        "query": f"{_or_group(options['keywords'])} {_or_group(options['places'])}",
        "mode": "artlist",
        "format": "json",
        "maxrecords": options.get("max_records", 150),
        "timespan": options.get("timespan", "24h"),
        "sort": "datedesc",
    }

    data = None
    for attempt in (1, 2):                      # try twice at most
        try:
            response = requests.get(API_URL, params=params, timeout=TIMEOUT_SECONDS * 2,
                                    headers={"User-Agent": USER_AGENT})
            if response.status_code == 429 and attempt == 1:
                time.sleep(6)                   # GDELT asks for 5 s between requests
                continue
            response.raise_for_status()
            data = response.json()
            break
        except (requests.RequestException, ValueError) as error:
            print(f"  ! GDELT skipped this run: {str(error)[:120]}")
            return []
    if data is None:
        print("  ! GDELT skipped this run: too many requests (it is busy - will retry next run)")
        return []

    blocked = set(options.get("blocked_domains", []))
    articles = []
    for item in data.get("articles", []):
        domain = item.get("domain", "")
        if not item.get("url") or not item.get("title") or domain in blocked:
            continue
        articles.append({
            "source": f"GDELT: {domain}",
            "title": item["title"].strip(),
            "url": item["url"],
            "summary": "",
            "published": _parse_date(item.get("seendate")),
            "language": LANGUAGES.get(item.get("language"), "other"),
        })
    return articles
