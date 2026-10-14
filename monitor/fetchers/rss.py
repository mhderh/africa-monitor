"""
Fetch articles from RSS feeds.

Every article is turned into a plain Python dictionary with the same keys,
whatever feed it came from:

    {
        "source":    "BBC News Africa",
        "title":     "Gunmen attack village in ...",
        "url":       "https://www.bbc.com/news/...",
        "summary":   "Short description from the feed (no HTML)",
        "published": "2026-10-14T06:30:00+00:00",   # ISO date in UTC, or None
        "language":  "en",
    }
"""

import html
import re
from datetime import datetime, timezone

import feedparser
import requests

# Some websites block requests that don't say who they are, so we identify
# ourselves politely. Change the text if you like.
USER_AGENT = "AfricaSecurityMonitor/0.1 (personal news-monitoring project)"

# Give up on a feed if it hasn't answered within this many seconds.
TIMEOUT_SECONDS = 20


def clean_text(text):
    """Remove HTML tags and extra spaces from a piece of feed text."""
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", text)   # drop <tags>
    text = html.unescape(text)             # turn &amp; into &, etc.
    return re.sub(r"\s+", " ", text).strip()


def parse_date(entry):
    """Return the entry's publication date as an ISO string in UTC, or None."""
    # feedparser gives dates as a time tuple in "published_parsed"
    # (or "updated_parsed" if the feed only has an update date).
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if not parsed:
        return None
    return datetime(*parsed[:6], tzinfo=timezone.utc).isoformat()


def fetch_feed(source):
    """
    Download one RSS feed and return a list of article dictionaries.

    `source` is one entry from config/sources.yaml, e.g.
    {"name": "BBC News Africa", "url": "...", "language": "en"}.
    If the feed is unreachable we print a warning and return an empty list,
    so one broken feed never stops the whole pipeline.
    """
    try:
        response = requests.get(
            source["url"],
            headers={"User-Agent": USER_AGENT},
            timeout=TIMEOUT_SECONDS,
        )
        response.raise_for_status()   # treat 404, 500, ... as errors
    except requests.RequestException as error:
        print(f"  ! Could not fetch {source['name']}: {error}")
        return []

    feed = feedparser.parse(response.content)

    articles = []
    for entry in feed.entries:
        url = entry.get("link")
        title = clean_text(entry.get("title"))
        if not url or not title:
            continue   # skip broken entries
        articles.append({
            "source": source["name"],
            "title": title,
            "url": url,
            "summary": clean_text(entry.get("summary")),
            "published": parse_date(entry),
            "language": source.get("language", "en"),
        })
    return articles
