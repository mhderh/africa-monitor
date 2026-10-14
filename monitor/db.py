"""
Everything that talks to the database lives in this file.

We use SQLite: the whole database is a single file, data/monitor.db.
Python has SQLite built in, so there is nothing to install. If you ever move
to Supabase/Postgres, this is the only file that needs to change.

Check what's inside the database at any time with:

    python -m monitor.db
"""

import sqlite3
import sys
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from monitor import settings

# data/monitor.db by default; data/local.db if MONITOR_DB is set in .env.
DB_FILE = settings.DB_FILE

# The "articles" table: one row per news article we have ever fetched.
#
#   status tells us how far each article got through the pipeline:
#     "new"           just fetched, not processed yet
#     "filtered_out"  removed by the keyword filter (not relevant)
#     "classified"    relevant - an event was created for it
#     "duplicate"     relevant, but another source already reported the
#                     same incident (its event has duplicate_of set)
#
# "url" is UNIQUE, so the same article can never be stored twice.
#
# The "events" table: one row per relevant article, with everything the
# classifier extracted. Telegram and the dashboard read from this table.
SCHEMA = """
CREATE TABLE IF NOT EXISTS articles (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    url         TEXT NOT NULL UNIQUE,
    source      TEXT NOT NULL,
    title       TEXT NOT NULL,
    summary     TEXT,
    published   TEXT,              -- ISO date in UTC, may be empty
    language    TEXT,
    fetched_at  TEXT NOT NULL,     -- when we first saw it (UTC)
    status      TEXT NOT NULL DEFAULT 'new'
);

CREATE INDEX IF NOT EXISTS idx_articles_status ON articles(status);
CREATE INDEX IF NOT EXISTS idx_articles_published ON articles(published);

CREATE TABLE IF NOT EXISTS events (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    article_id          INTEGER NOT NULL UNIQUE REFERENCES articles(id),
    event_date          TEXT,      -- YYYY-MM-DD
    country             TEXT,
    region              TEXT,
    city                TEXT,
    latitude            REAL,
    longitude           REAL,
    location_precision  TEXT,      -- "city" or "country"
    event_type          TEXT,      -- attack, kidnapping, arrest, military operation, threat, other
    group_names         TEXT,      -- e.g. "JNIM (al-Qaeda Sahel); Islamic State Sahel"
    killed              INTEGER,   -- empty if not reported
    injured             INTEGER,
    kidnapped           INTEGER,
    severity            INTEGER,   -- 1 (low) to 5 (very high)
    severity_reason     TEXT,
    summary             TEXT,
    source              TEXT,
    url                 TEXT,
    language            TEXT,
    classifier          TEXT,      -- "rules" (or "claude" later)
    created_at          TEXT,
    alert_sent          INTEGER NOT NULL DEFAULT 0,   -- 1 = alert message sent
    in_digest           INTEGER NOT NULL DEFAULT 0,   -- 1 = included in a digest
    duplicate_of        INTEGER REFERENCES events(id) -- set if another event already
                                                      -- covers this incident
);

CREATE INDEX IF NOT EXISTS idx_events_date ON events(event_date);
"""

# Columns added after a table was first created. connect() adds any that
# are missing, so older database files keep working.
NEW_COLUMNS = {
    "events": {"duplicate_of": "INTEGER REFERENCES events(id)"},
}

# Bits that websites add to links to track where clicks come from.
# They don't change the article, so we remove them; otherwise the same
# article could be saved twice with slightly different links.
TRACKING_PARAMS_PREFIXES = ("utm_", "at_", "fbclid", "gclid", "ocid", "cmp")


def clean_url(url):
    """Return the link without tracking parameters or #fragments."""
    parts = urlsplit(url.strip())
    kept = [(key, value) for key, value in parse_qsl(parts.query)
            if not key.lower().startswith(TRACKING_PARAMS_PREFIXES)]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(kept), ""))


def connect():
    """Open the database (creating the file and tables the first time)."""
    DB_FILE.parent.mkdir(exist_ok=True)          # make sure data/ exists
    connection = sqlite3.connect(DB_FILE)
    connection.row_factory = sqlite3.Row         # rows behave like dicts
    connection.executescript(SCHEMA)
    _add_missing_columns(connection)
    return connection


def _add_missing_columns(connection):
    for table, columns in NEW_COLUMNS.items():
        existing = {row["name"] for row in connection.execute(f"PRAGMA table_info({table})")}
        for name, definition in columns.items():
            if name not in existing:
                connection.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")
    connection.commit()


def save_articles(connection, articles):
    """
    Save a list of article dictionaries. Articles whose link is already in
    the database are skipped. Returns the list of articles that were new.
    """
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    new_articles = []
    for article in articles:
        url = clean_url(article["url"])
        cursor = connection.execute(
            """
            INSERT OR IGNORE INTO articles
                (url, source, title, summary, published, language, fetched_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (url, article["source"], article["title"], article["summary"],
             article["published"], article["language"], now),
        )
        # rowcount is 1 if the row was inserted, 0 if the URL already existed.
        if cursor.rowcount == 1:
            new_articles.append({**article, "url": url})
    connection.commit()
    return new_articles


def get_articles_by_status(connection, status):
    """Return all articles with the given status, as dictionaries."""
    rows = connection.execute(
        "SELECT * FROM articles WHERE status = ? ORDER BY id", (status,))
    return [dict(row) for row in rows]


def set_article_status(connection, article_id, status):
    connection.execute("UPDATE articles SET status = ? WHERE id = ?", (status, article_id))


def save_event(connection, event):
    """
    Insert one event (a dict whose keys match the events table columns).
    Returns the new event's id.
    """
    event = {**event, "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    columns = ", ".join(event)
    placeholders = ", ".join(f":{key}" for key in event)
    cursor = connection.execute(f"INSERT INTO events ({columns}) VALUES ({placeholders})", event)
    return cursor.lastrowid


def get_candidate_events(connection, country, event_type, date_from, date_to):
    """Original (non-duplicate) events that might describe the same incident."""
    rows = connection.execute(
        """
        SELECT events.*, articles.title
        FROM events JOIN articles ON articles.id = events.article_id
        WHERE events.duplicate_of IS NULL AND events.country = ?
          AND events.event_type = ? AND events.event_date BETWEEN ? AND ?
        """, (country, event_type, date_from, date_to))
    return [dict(row) for row in rows]


def update_event(connection, event_id, fields):
    """Change some columns of an existing event, e.g. {"severity": 4}."""
    assignments = ", ".join(f"{key} = :{key}" for key in fields)
    connection.execute(f"UPDATE events SET {assignments} WHERE id = :id",
                       {**fields, "id": event_id})


# Shared part of the digest and alert queries: events with their headline
# and how many other sources reported the same incident.
EVENTS_WITH_TITLE = """
    SELECT events.*, articles.title,
           (SELECT COUNT(*) FROM events AS d WHERE d.duplicate_of = events.id) AS other_reports
    FROM events JOIN articles ON articles.id = events.article_id
    WHERE events.duplicate_of IS NULL AND events.event_date >= :since
"""


def get_digest_events(connection, since_date, include_sent=False):
    """
    Events dated on/after since_date (YYYY-MM-DD) that haven't been in a
    digest yet - or all of them if include_sent is True (used by --resend).
    """
    only_unsent = "" if include_sent else " AND events.in_digest = 0"
    rows = connection.execute(
        EVENTS_WITH_TITLE + only_unsent +
        " ORDER BY events.severity DESC, events.event_date DESC",
        {"since": since_date})
    return [dict(row) for row in rows]


def get_alert_events(connection, since_date, min_severity, limit):
    """Serious events that haven't had an alert yet, most severe first."""
    rows = connection.execute(
        EVENTS_WITH_TITLE + " AND events.alert_sent = 0 AND events.severity >= :min"
        " ORDER BY events.severity DESC, events.id LIMIT :limit",
        {"since": since_date, "min": min_severity, "limit": limit})
    return [dict(row) for row in rows]


def mark_alert_sent(connection, event_id):
    connection.execute("UPDATE events SET alert_sent = 1 WHERE id = ?", (event_id,))
    connection.commit()


def mark_in_digest(connection, event_ids):
    """Remember that these events were sent, so they're never sent twice."""
    connection.executemany("UPDATE events SET in_digest = 1 WHERE id = ?",
                           [(event_id,) for event_id in event_ids])
    connection.commit()


def reset_for_reprocess(connection):
    """
    Forget all filtering/classification results so every article is checked
    again (useful after editing keywords.yaml or places.yaml).
    Events that were already sent to Telegram are kept.
    """
    connection.execute("DELETE FROM events WHERE alert_sent = 0 AND in_digest = 0")
    connection.execute(
        "UPDATE articles SET status = 'new' "
        "WHERE id NOT IN (SELECT article_id FROM events)")
    connection.commit()


def print_stats(connection):
    """Print a quick overview of what is in the database."""
    total = connection.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
    print(f"Database: {DB_FILE}")
    print(f"Total articles: {total}\n")

    print("By source:")
    for row in connection.execute(
            "SELECT source, COUNT(*) AS n FROM articles GROUP BY source ORDER BY n DESC"):
        print(f"  {row['source']:<30} {row['n']}")

    print("\nBy status:")
    for row in connection.execute(
            "SELECT status, COUNT(*) AS n FROM articles GROUP BY status"):
        print(f"  {row['status']:<30} {row['n']}")

    print("\n5 most recently fetched:")
    for row in connection.execute(
            "SELECT title, source, fetched_at FROM articles ORDER BY id DESC LIMIT 5"):
        print(f"  [{row['fetched_at'][:16]}] {row['title'][:80]}  ({row['source']})")

    events = connection.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    print(f"\nTotal events: {events}")
    print("By country:")
    for row in connection.execute(
            "SELECT country, COUNT(*) AS n FROM events GROUP BY country ORDER BY n DESC"):
        print(f"  {row['country']:<30} {row['n']}")
    print("By severity:")
    for row in connection.execute(
            "SELECT severity, COUNT(*) AS n FROM events GROUP BY severity ORDER BY severity DESC"):
        print(f"  {row['severity']:<30} {row['n']}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    print_stats(connect())
