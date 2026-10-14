"""
Tests for cross-source deduplication and alerts.
They use a temporary database, so your real data/monitor.db is never touched.
"""

import pytest

from monitor import alerts, classify_rules, db, dedupe


@pytest.fixture
def connection(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_FILE", tmp_path / "test.db")
    conn = db.connect()
    yield conn
    conn.close()


def add(connection, title, url, source="Test", summary=""):
    """Save an article, classify it and run deduplication, like main.py does."""
    article = {"title": title, "summary": summary, "url": url, "source": source,
               "published": "2026-10-14T08:00:00+00:00", "language": "en"}
    db.save_articles(connection, [article])
    article_id = connection.execute("SELECT id FROM articles WHERE url = ?", (url,)).fetchone()[0]
    event = classify_rules.classify({**article, "id": article_id})
    original = dedupe.find_original(connection, event, title)
    if original:
        event["duplicate_of"] = original["id"]
        dedupe.merge_into(connection, original, event)
    return db.save_event(connection, event), original


def test_similar_headlines_score_high():
    assert dedupe.similarity("Gunmen kill 12 in Borno village attack",
                             "Gunmen kill 12 villagers in Borno attack") > 0.5
    assert dedupe.similarity("Gunmen kill 12 in Borno", "Election results in Ghana") == 0


def test_same_city_same_day_is_a_duplicate(connection):
    first_id, _ = add(connection, "Jihadists attack army post near Gao, Mali", "https://a.com/1")
    _, original = add(connection, "Mali: attaque contre un poste militaire près de Gao",
                      "https://b.com/2", source="RFI")
    assert original is not None and original["id"] == first_id


def test_rising_death_toll_updates_original(connection):
    first_id, _ = add(connection, "Attack in Borno kills 5", "https://a.com/1")
    add(connection, "Death toll in Borno attack rises to 25", "https://b.com/2")
    row = connection.execute("SELECT killed, severity FROM events WHERE id = ?",
                             (first_id,)).fetchone()
    assert row["killed"] == 25
    assert row["severity"] == 4


def test_different_incidents_are_kept_apart(connection):
    add(connection, "Gunmen attack village in Zamfara", "https://a.com/1")
    _, original = add(connection, "Bomb explodes at market in Maiduguri", "https://b.com/2")
    assert original is None


def test_alert_only_for_serious_unsent_events(connection):
    add(connection, "Jihadists kill 60 civilians in Burkina Faso village", "https://a.com/1")
    add(connection, "Militants attack police station in Cameroon", "https://b.com/2")
    events = db.get_alert_events(connection, "2026-10-01", min_severity=4, limit=10)
    assert len(events) == 1
    text = alerts.format_alert(events[0])
    assert "ALERT · severity 5" in text and "60 killed" in text

    db.mark_alert_sent(connection, events[0]["id"])
    assert db.get_alert_events(connection, "2026-10-01", min_severity=4, limit=10) == []
