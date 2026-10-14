"""
Entry point of the pipeline. Run it from the project folder with:

    python -m monitor.main               # normal run
    python -m monitor.main --verbose     # also show why each article was kept/dropped
    python -m monitor.main --reprocess   # re-check all stored articles (after editing keywords)
    python -m monitor.main --dry-run     # print the Telegram digest instead of sending it
    python -m monitor.main --no-telegram # skip Telegram completely
    python -m monitor.main --resend      # only re-send the last digest (e.g. to a new
                                         # channel); fetches nothing, changes nothing

What it does:
  1. fetch all enabled sources in config/sources.yaml (RSS, GDELT, ReliefWeb)
  2. save new articles to the database (data/monitor.db)
  3. keyword filter: drop articles that aren't about armed violence in Africa
  4. classify the remaining ones (rule-based) and save them as events,
     marking repeats of an incident already reported by another source
  5. send an alert for each new severity 4-5 event
  6. send the daily digest to Telegram
"""

import argparse
import sys

from monitor import alerts, classify_rules, config, db, dedupe, digest, prefilter, telegram
from monitor.fetchers import gdelt, reliefweb
from monitor.fetchers.rss import fetch_feed


def fetch_all():
    """Step 1: download every enabled source."""
    sources = config.load("sources")
    articles = []
    for source in sources.get("rss", []):
        if not source.get("enabled", True):
            continue
        print(f"Fetching {source['name']} ...")
        fetched = fetch_feed(source)
        print(f"  -> {len(fetched)} articles")
        articles.extend(fetched)

    # The two APIs: each has its own section in sources.yaml.
    for name, module in (("gdelt", gdelt), ("reliefweb", reliefweb)):
        options = sources.get(name) or {}
        if options.get("enabled"):
            print(f"Fetching {name.capitalize()} ...")
            fetched = module.fetch(options)
            print(f"  -> {len(fetched)} articles")
            articles.extend(fetched)
    return articles


def process_new_articles(connection, verbose):
    """
    Steps 3 and 4: filter and classify every article with status 'new'.
    Returns (number checked, new events, number of duplicates).
    """
    pending = db.get_articles_by_status(connection, "new")
    events, duplicates = [], 0
    for article in pending:
        relevant, reason = prefilter.check(article)
        if verbose:
            mark = "KEEP" if relevant else "drop"
            print(f"  [{mark}] {article['title'][:70]:<70}  <- {reason}")
        if not relevant:
            db.set_article_status(connection, article["id"], "filtered_out")
            continue

        event = classify_rules.classify(article)
        original = dedupe.find_original(connection, event, article["title"])
        if original:
            # Same incident as an event we already have: save it as a
            # duplicate and pass on any higher figures to the original.
            event["duplicate_of"] = original["id"]
            db.save_event(connection, event)
            dedupe.merge_into(connection, original, event)
            db.set_article_status(connection, article["id"], "duplicate")
            duplicates += 1
            if verbose:
                print(f"         ^ duplicate of: {original['title'][:70]}")
        else:
            db.save_event(connection, event)
            db.set_article_status(connection, article["id"], "classified")
            events.append(event)

    connection.commit()
    return len(pending), events, duplicates


def print_events(events):
    """Show the events, most severe first."""
    for event in sorted(events, key=lambda e: e["severity"], reverse=True):
        place = ", ".join(p for p in (event["city"], event["country"]) if p)
        print(f"\n[Severity {event['severity']}] {event['event_type'].upper()} - {place}"
              f" ({event['region']})")
        print(f"   {event['summary']}")
        details = []
        if event["group_names"]:
            details.append(f"Group: {event['group_names']}")
        for field in ("killed", "injured", "kidnapped"):
            if event[field] is not None:
                details.append(f"{field.capitalize()}: {event[field]}")
        if details:
            print("   " + " | ".join(details))
        print(f"   Why: {event['severity_reason']}")
        print(f"   {event['event_date']} | {event['source']} | {event['url']}")


def send_digest(connection, dry_run):
    """Step 6: build the digest from unsent events and send it (or print it)."""
    events = db.get_digest_events(connection, digest.cutoff_date())
    text = digest.build_digest(events)

    if dry_run:
        print("\n----- Digest preview (not sent) -----")
        print(text)
        print("-------------------------------------")
        return

    try:
        telegram.send_message(text)
    except telegram.TelegramError as error:
        # Don't mark anything as sent - it will be retried on the next run.
        print(f"\n! Digest NOT sent: {error}")
        return
    db.mark_in_digest(connection, [e["id"] for e in events])
    print(f"\nDigest sent to Telegram ({len(events)} events).")


def resend_digest(connection, dry_run):
    """
    Send again the digest of the last days (digest.max_age_days), including
    events that were already sent - useful after moving to a new Telegram
    channel. Nothing is fetched and the database is not changed.
    """
    events = db.get_digest_events(connection, digest.cutoff_date(), include_sent=True)
    text = digest.build_digest(events)
    if dry_run:
        print("\n----- Digest preview (resend, not sent) -----")
        print(text)
        return
    try:
        telegram.send_message(text)
    except telegram.TelegramError as error:
        print(f"\n! Digest NOT re-sent: {error}")
        sys.exit(1)
    print(f"\nDigest re-sent to Telegram ({len(events)} events).")


def main():
    # Make sure French accents and Arabic text print correctly on Windows.
    sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="Africa security news monitor")
    parser.add_argument("--verbose", action="store_true",
                        help="show the keep/drop decision for every article")
    parser.add_argument("--reprocess", action="store_true",
                        help="re-check all stored articles (after editing the keyword files)")
    parser.add_argument("--dry-run", action="store_true",
                        help="print the Telegram alerts and digest instead of sending them")
    parser.add_argument("--no-telegram", action="store_true",
                        help="don't send any Telegram messages")
    parser.add_argument("--resend", action="store_true",
                        help="only re-send the digest of the last days, including events "
                             "already sent; fetches nothing and changes nothing")
    args = parser.parse_args()

    connection = db.connect()

    if args.resend:
        resend_digest(connection, args.dry_run)
        connection.close()
        return

    # Steps 1-2: fetch and save. Only articles we have never seen come back.
    articles = fetch_all()
    new_articles = db.save_articles(connection, articles)
    print(f"\nFetched {len(articles)} articles: {len(new_articles)} new, "
          f"{len(articles) - len(new_articles)} already in the database.")

    if args.reprocess:
        db.reset_for_reprocess(connection)
        print("Reprocessing: all stored articles will be checked again.")

    # Steps 3-4: filter and classify.
    print("\nFiltering and classifying ...")
    checked, events, duplicates = process_new_articles(connection, args.verbose)
    print(f"\nChecked {checked} articles: {len(events)} new events, "
          f"{duplicates} duplicates of known events, "
          f"{checked - len(events) - duplicates} filtered out.")
    print_events(events)

    # Steps 5-6: Telegram alerts, then the digest.
    if not args.no_telegram:
        alerts.send_alerts(connection, args.dry_run)
        send_digest(connection, args.dry_run)

    connection.close()


if __name__ == "__main__":
    main()
