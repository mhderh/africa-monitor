"""
High-severity alerts: every event at or above alerts.min_severity
(config/options.yaml, default 4) gets its own short Telegram message,
sent before the daily digest. Each event is alerted only once.
"""

from html import escape

from monitor import config, db, digest, telegram


def format_alert(event):
    place = ", ".join(p for p in (event["city"], event["country"]) if p)
    facts = []
    for field in ("killed", "kidnapped", "injured"):
        if event[field]:
            facts.append(f"{event[field]} {field}")
    if event["group_names"]:
        facts.append(escape(event["group_names"], quote=False))

    lines = [
        f"🚨 <b>ALERT · severity {event['severity']}</b> · {escape(event['event_type'], quote=False)}",
        f"📍 {escape(place, quote=False)} ({escape(event['region'] or '', quote=False)})",
        f"<b>{escape(event['title'], quote=False)}</b>",
    ]
    if facts:
        lines.append(" · ".join(facts))
    lines.append(f"Why: {escape(event['severity_reason'], quote=False)}")
    sources = f'<a href="{escape(event["url"], quote=True)}">{escape(event["source"], quote=False)}</a>'
    if event.get("other_reports"):
        sources += f" (+{event['other_reports']} other sources)"
    lines.append(sources)
    return "\n".join(lines)


def send_alerts(connection, dry_run):
    """Send one message per new high-severity event. Returns how many."""
    options = config.load("options")["alerts"]
    events = db.get_alert_events(connection, digest.cutoff_date(),
                                 options["min_severity"], options["max_per_run"])
    sent = 0
    for event in events:
        text = format_alert(event)
        if dry_run:
            print("\n----- Alert preview (not sent) -----")
            print(text)
            continue
        try:
            telegram.send_message(text)
        except telegram.TelegramError as error:
            print(f"\n! Alert NOT sent (will retry next run): {error}")
            break
        db.mark_alert_sent(connection, event["id"])
        sent += 1
    if not dry_run:
        print(f"\nAlerts sent: {sent}")
    return sent
