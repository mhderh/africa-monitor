"""Tests for the Telegram digest text and message splitting."""

from datetime import date

from monitor import digest, telegram


def make_event(region, severity, title, **extra):
    event = {"id": 1, "region": region, "severity": severity, "title": title,
             "event_type": "attack", "city": None, "country": "Mali",
             "killed": None, "injured": None, "kidnapped": None,
             "group_names": None, "url": "https://example.com/a?x=1&y=2",
             "source": "Test News"}
    event.update(extra)
    return event


def test_empty_digest_says_so():
    text = digest.build_digest([], today=date(2026, 10, 15))
    assert "No new relevant events" in text


def test_regions_with_most_severe_events_come_first():
    events = [
        make_event("North Africa", 2, "Minor incident"),
        make_event("Sahel", 5, "Major attack", killed=60),
        make_event("Sahel", 3, "Smaller attack"),
    ]
    text = digest.build_digest(events, today=date(2026, 10, 15))
    assert text.index("Sahel") < text.index("North Africa")
    assert text.index("Major attack") < text.index("Smaller attack")
    assert "3 events · 1 high severity" in text
    assert "60 killed" in text


def test_special_characters_are_escaped():
    text = digest.build_digest([make_event("Sahel", 3, "Army <says> A & B")],
                               today=date(2026, 10, 15))
    assert "Army &lt;says&gt; A &amp; B" in text
    assert 'href="https://example.com/a?x=1&amp;y=2"' in text


def test_long_messages_are_split():
    text = "\n\n".join(f"block {i} " + "x" * 300 for i in range(40))
    pieces = telegram.split_message(text, limit=1000)
    assert len(pieces) > 1
    assert all(len(p) <= 1000 for p in pieces)
    assert "".join(pieces).count("block") == 40
