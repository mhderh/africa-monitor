"""
Cross-source deduplication: when several outlets report the same incident,
we keep ONE event and mark the others as duplicates of it.

Two events count as the same incident when they have the same country and
event type, are at most N days apart (config/options.yaml), AND at least one
of these is true:
  - they name the same city
  - they report the same number of people killed
  - their headlines share enough words (works within one language)

Duplicates are still saved (so the dashboard can show "reported by 3
sources"), but Telegram only shows the original. If a duplicate reports
higher numbers - e.g. a death toll that has risen - the original is updated.
"""

from datetime import date, timedelta

from monitor import config, db
from monitor.matching import normalize

# Small common words that say nothing about the incident.
STOPWORDS = {
    "the", "and", "for", "with", "from", "after", "over", "into", "says", "say",
    "said", "least", "near", "amid", "has", "have", "are", "was", "were", "its",
    "les", "des", "dans", "une", "pour", "par", "sur", "aux", "avec", "apres",
    "plus", "moins", "selon", "est", "sont", "ont", "qui",
    "في", "من", "على", "الى", "عن", "بعد", "مع",
}


def title_words(title):
    return {w for w in normalize(title).split() if len(w) > 2 and w not in STOPWORDS}


def similarity(title_a, title_b):
    """Share of words in common: 0 = none, 1 = identical (Jaccard index)."""
    a, b = title_words(title_a), title_words(title_b)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def is_same_incident(event, title, other, threshold):
    if event["city"] and event["city"] == other["city"]:
        return True
    if event["killed"] and event["killed"] == other["killed"]:
        return True
    return similarity(title, other["title"]) >= threshold


def find_original(connection, event, title):
    """Return the existing event this one duplicates, or None."""
    options = config.load("options")["deduplication"]
    day = date.fromisoformat(event["event_date"])
    window = timedelta(days=options["max_days_apart"])
    candidates = db.get_candidate_events(
        connection, event["country"], event["event_type"],
        (day - window).isoformat(), (day + window).isoformat())
    for other in candidates:
        if is_same_incident(event, title, other, options["title_similarity"]):
            return other
    return None


def merge_into(connection, original, duplicate):
    """Copy higher casualty figures / severity from a duplicate to the original."""
    updates = {}
    for field in ("killed", "injured", "kidnapped"):
        if duplicate[field] and (original[field] is None or duplicate[field] > original[field]):
            updates[field] = duplicate[field]
    if duplicate["severity"] > original["severity"]:
        updates["severity"] = duplicate["severity"]
        updates["severity_reason"] = duplicate["severity_reason"] + f" (per {duplicate['source']})"
    if not original["city"] and duplicate["city"]:
        for field in ("city", "latitude", "longitude", "location_precision"):
            updates[field] = duplicate[field]
    if updates:
        db.update_event(connection, original["id"], updates)
