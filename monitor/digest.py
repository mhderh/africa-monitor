"""
Builds the daily Telegram digest: all events not yet sent, grouped by
region, most severe first, each with a link to the source.

Preview it without sending anything:
    python -m monitor.main --dry-run
"""

from datetime import datetime, timedelta
from html import escape
from zoneinfo import ZoneInfo

from monitor import config

TIMEZONE = ZoneInfo("Africa/Casablanca")

SEVERITY_ICONS = {5: "🔴", 4: "🟠", 3: "🟡", 2: "🔵", 1: "⚪"}


def today_local():
    return datetime.now(TIMEZONE).date()


def cutoff_date(today=None):
    """
    Oldest event date (YYYY-MM-DD) allowed in today's digest/alerts - set by
    digest.max_age_days in config/options.yaml.
    """
    max_age_days = config.load("options")["digest"]["max_age_days"]
    return ((today or today_local()) - timedelta(days=max_age_days)).isoformat()


def format_event(event):
    """Three short lines for one event."""
    severity = event["severity"]
    place = ", ".join(p for p in (event["city"], event["country"]) if p)
    header = (f"{SEVERITY_ICONS.get(severity, '')} <b>{severity}</b> · "
              f"{escape(event['event_type'], quote=False)} · {escape(place, quote=False)}")

    title = event["title"]
    if len(title) > 160:
        title = title[:157] + "..."

    facts = []
    for field, label in (("killed", "killed"), ("kidnapped", "kidnapped"), ("injured", "injured")):
        if event[field]:
            facts.append(f"{event[field]} {label}")
    if event["group_names"]:
        facts.append(escape(event["group_names"], quote=False))

    link = f'<a href="{escape(event["url"], quote=True)}">{escape(event["source"], quote=False)}</a>'
    if event.get("other_reports"):
        link += f" (+{event['other_reports']})"     # number of other sources
    footer = " · ".join([link] + facts)
    return f"{header}\n{escape(title, quote=False)}\n{footer}"


def build_digest(events, today=None):
    """Return the digest text (Telegram HTML) for a list of event dicts."""
    today = today or today_local()
    date_text = today.strftime("%a %d %b %Y")

    if not events:
        return (f"📰 <b>Africa security digest</b> · {date_text}\n"
                "No new relevant events since the last digest.")

    # Group by region.
    regions = {}
    for event in events:
        regions.setdefault(event["region"] or "Other", []).append(event)

    # Regions with the most severe events first, then the busiest.
    ordered = sorted(regions.items(),
                     key=lambda item: (-max(e["severity"] for e in item[1]),
                                       -len(item[1]), item[0]))

    min_listed = config.load("options")["digest"]["list_min_severity"]
    high = sum(1 for e in events if e["severity"] >= 4)
    count = f"{len(events)} event" + ("" if len(events) == 1 else "s")
    parts = [f"📰 <b>Africa security digest</b> · {date_text}\n"
             f"{count} · {high} high severity (4–5)"]
    for region, region_events in ordered:
        region_events.sort(key=lambda e: -e["severity"])
        listed = [e for e in region_events if e["severity"] >= min_listed]
        hidden = len(region_events) - len(listed)
        parts.append(f"<b>🌍 {escape(region, quote=False)}</b> ({len(region_events)})")
        parts.extend(format_event(e) for e in listed)
        if hidden:
            parts.append(f"⚪ + {hidden} lower-severity item" + ("" if hidden == 1 else "s"))
    return "\n\n".join(parts)
