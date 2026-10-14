"""
Fetch recent reports from the ReliefWeb API (UN OCHA).
Docs: https://apidoc.reliefweb.int/

Requires a free, approved "app name" in .env:  RELIEFWEB_APPNAME=...
Without it this source is skipped.
"""

from datetime import datetime, timedelta, timezone

import requests

from monitor import settings
from monitor.fetchers.rss import TIMEOUT_SECONDS, USER_AGENT, clean_text

API_URL = "https://api.reliefweb.int/v2/reports"


def fetch(options):
    """Return article dictionaries (see rss.py) for reports from the last 2 days."""
    if not settings.RELIEFWEB_APPNAME:
        print("  (ReliefWeb skipped: no RELIEFWEB_APPNAME in .env)")
        return []

    since = (datetime.now(timezone.utc) - timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    body = {
        "limit": options.get("max_records", 100),
        "sort": ["date.created:desc"],
        "fields": {"include": ["title", "url_alias", "url", "date.created",
                               "body", "source.shortname", "language.code"]},
        "filter": {
            "operator": "AND",
            "conditions": [
                {"field": "primary_country.iso3", "value": options["countries"],
                 "operator": "OR"},
                {"field": "date.created", "value": {"from": since}},
            ],
        },
    }
    try:
        response = requests.post(API_URL, params={"appname": settings.RELIEFWEB_APPNAME},
                                 json=body, timeout=TIMEOUT_SECONDS * 2,
                                 headers={"User-Agent": USER_AGENT})
        response.raise_for_status()
        data = response.json()
    except (requests.RequestException, ValueError) as error:
        print(f"  ! ReliefWeb skipped this run: {str(error)[:120]}")
        return []

    articles = []
    for item in data.get("data", []):
        fields = item.get("fields", {})
        url = fields.get("url_alias") or fields.get("url")
        if not url or not fields.get("title"):
            continue
        sources = fields.get("source") or [{}]
        languages = fields.get("language") or [{}]
        articles.append({
            "source": f"ReliefWeb: {sources[0].get('shortname', 'unknown')}",
            "title": clean_text(fields["title"]),
            "url": url,
            "summary": clean_text(fields.get("body", ""))[:500],
            "published": (fields.get("date") or {}).get("created"),
            "language": languages[0].get("code", "en"),
        })
    return articles
