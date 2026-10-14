# Africa Security News Monitor

Collects open-source news about terrorism, armed attacks, kidnappings and
extremist-group activity in Africa, classifies each relevant story (country,
city, event type, group, casualties, severity 1-5), sends a daily Telegram
digest, and feeds a dashboard.

Classification is **rule-based and free** (no API key needed). Claude can be
switched on later for better summaries and accuracy.

> Work in progress - built in phases. This README grows with each phase.

## Project layout

```
config/sources.yaml          <- news sources: RSS feeds, GDELT, ReliefWeb
config/keywords.yaml         <- violence keywords, event types, armed groups
config/places.yaml           <- countries, regions, cities and coordinates
config/options.yaml          <- digest, alert and deduplication settings
monitor/main.py              <- runs the pipeline
monitor/fetchers/rss.py      <- downloads and reads RSS feeds
monitor/fetchers/gdelt.py    <- GDELT news search
monitor/fetchers/reliefweb.py<- ReliefWeb (UN OCHA) reports
monitor/db.py                <- all database code (SQLite)
monitor/prefilter.py         <- keyword filter (keep / drop)
monitor/classify_rules.py    <- rule-based classifier (builds the events)
monitor/dedupe.py            <- spots the same incident reported by several sources
monitor/alerts.py            <- severity 4-5 alert messages
monitor/digest.py            <- builds the daily Telegram digest
monitor/telegram.py          <- sends Telegram messages; chat-ID helper
monitor/settings.py          <- reads secrets from .env
monitor/places.py            <- finds the country/city an article is about
monitor/matching.py          <- text-matching helpers (accents, Arabic, ...)
monitor/config.py            <- reads the YAML files
tests/                       <- automatic tests (python -m pytest)
data/monitor.db              <- the database file (created on first run)
requirements.txt             <- Python packages needed
.env.example                 <- template for secret keys (copy to .env)
```

## Setup from scratch (Windows)

### 1. Install Python and Git
- **Python 3.11 or newer**: https://www.python.org/downloads/ - during
  installation tick **"Add python.exe to PATH"**.
- **Git**: https://git-scm.com/download/win (default options are fine).

Check both work by opening **PowerShell** and typing:

```powershell
python --version
git --version
```

### 2. Create the virtual environment (once)
A *virtual environment* is a private folder (`.venv`) holding this project's
packages, so they don't mix with other Python projects.

```powershell
cd C:\Users\saada\AGENTVEILLE
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

After activation your prompt starts with `(.venv)`. Activate it again every
time you open a new PowerShell window.

> If PowerShell says "running scripts is disabled", either run this once:
> `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`
> or skip activation and type `.\.venv\Scripts\python.exe` instead of
> `python` in every command below.

### 3. Run it

```powershell
python -m monitor.main               # fetch, filter, classify, print events
python -m monitor.main --verbose     # also show why each article was kept/dropped
python -m monitor.main --reprocess   # re-check every stored article (after editing keywords)
python -m monitor.main --dry-run     # print the Telegram digest instead of sending it
python -m monitor.main --no-telegram # skip Telegram completely
python -m monitor.db                 # what's in the database
python -m pytest                     # run the automatic tests
```

### 4. Set up the Telegram bot (once)
1. In Telegram, open a chat with **@BotFather** (blue tick), send `/newbot`,
   choose a display name and a username ending in `bot`.
   BotFather replies with a **token** like `123456789:ABC...`.
   Treat it like a password - anyone with it can control your bot.
2. In the project folder, copy `.env.example` to `.env`:
   ```powershell
   Copy-Item .env.example .env
   notepad .env
   ```
   Paste the token after `TELEGRAM_BOT_TOKEN=` (no quotes, no spaces). Save.
3. In Telegram, search for your bot's username, open it and press **Start**
   (or send "hi"). A bot can't message you until you've messaged it first.
4. Get your chat ID:
   ```powershell
   python -m monitor.telegram --get-chat-id
   ```
   Copy the `TELEGRAM_CHAT_ID=...` line it prints into `.env`. Save.
5. Check it works:
   ```powershell
   python -m monitor.telegram --test
   ```

## Telegram: alerts and the daily digest
**Alerts** - every new event with severity 4 or 5 gets its own short message
(place, headline, casualties, group, why it scored high, source link), sent
before the digest. At most 10 per run; each event is alerted only once.

**Digest** - one message with every event not yet sent, published in the
last 2 days, grouped by region: regions with the most severe events first,
and inside each region the most severe events first. Each event is three
short lines: severity and type, the headline, and a source link with
casualties and group if known. `(+2)` after a source means two other
outlets reported the same incident. Severity-1 items aren't listed one by
one - each region just shows "+ N lower-severity items".
Severity icons: 🔴 5 · 🟠 4 · 🟡 3 · 🔵 2 · ⚪ 1.

All of these numbers can be changed in `config/options.yaml`.

Events are marked as sent only after Telegram confirms delivery, so nothing
is sent twice and nothing is lost if Telegram is down. If there's nothing
new, you still get a short "no new events" message - so you know the system
ran.

## How an article becomes an event

1. **Fetch** - every enabled source in `config/sources.yaml` is downloaded:
   17 RSS feeds (English, French, Arabic), plus GDELT and ReliefWeb (below).
2. **Save** - new articles go into the `articles` table; links already
   stored are skipped (tracking bits like `?utm_source=` are removed first).
3. **Keyword filter** (`prefilter.py`) - an article is kept only if it
   names an African country or city **and** contains either a *strong*
   violence keyword (jihadist, kidnapped, gunmen, attentat, اختطاف ...) or a
   *weak* one (attack, clashes, rebels ...) confirmed by a second sign
   (another weak keyword, a word like killed/soldiers/army, or a known group).
   Sport pages and phrases like "heart attack" are thrown away.
4. **Classify** (`classify_rules.py`) - for each kept article:
   - **location**: country, region and city from `places.yaml`, with map
     coordinates (city if named, otherwise the country's centre)
   - **event type**: the first matching list in `keywords.yaml`
     (kidnapping, attack, military operation, arrest, threat, otherwise "other")
   - **group**: matched against the `groups` list
   - **killed / injured / kidnapped**: numbers written like "12 killed",
     "killing at least 30", "30 soldats tués", "مقتل 15"
   - **severity**:

     | Severity | Rule |
     |---|---|
     | 5 | 50+ killed, or 50+ kidnapped |
     | 4 | 10+ killed, 10+ kidnapped, or suicide bombing / car bomb / massacre |
     | 3 | 1-9 killed, any kidnapping, or 5+ injured |
     | 2 | attack, military operation or arrest with no casualties reported |
     | 1 | threats, warnings, other security news |

   Deaths mentioned without a number ("driver killed") count as severity 3.
   Running totals ("3,900 killed since January") and numbers of 1,000+ are
   ignored, because they aren't a single incident.

   The result is saved in the `events` table.
5. **Deduplication** (`dedupe.py`) - if an event has the same country and
   type as one from the day before/after, **and** the same city, the same
   death toll or a very similar headline, it's saved as a *duplicate* of
   that event. Telegram shows only the original (with "+N" sources). If the
   duplicate reports a higher toll, the original is updated.

**Known limits of the free rules:** the summary is the feed's own headline
and description (not a rewrite); numbers written in unusual ways are missed;
the event date is the publication date; and stories that only mention an
African place in passing can slip through; negations aren't understood
("the terrorism theory was ruled out" still matches *terror*); and two
different attacks in the same city on the same day would be merged.
Switching on Claude later fixes most of this.

## Tuning the keywords
1. Run `python -m monitor.main --verbose` and look at the `[KEEP]` / `[drop]`
   lines and their reasons.
2. Edit `config/keywords.yaml` or `config/places.yaml` (instructions are at
   the top of each file).
3. Run `python -m monitor.main --reprocess` to re-check stored articles.
4. Run `python -m pytest` to make sure nothing that used to work broke.

## The database
Everything is saved in `data/monitor.db` (SQLite - one file, nothing to
install). Tables: `articles` (everything fetched) and `events` (relevant
articles with the extracted details; duplicates have `duplicate_of` set).

To browse the data visually, install the free
[DB Browser for SQLite](https://sqlitebrowser.org/) and open `data/monitor.db`.
To start over, close any program using the file and delete `data/monitor.db`;
it is recreated on the next run.

## GDELT and ReliefWeb
- **GDELT** (free, no key) runs one search per run with the words and places
  listed in `sources.yaml`. It is popular and often answers
  "429 Too Many Requests"; the pipeline then prints a warning and carries on
  without it - nothing to fix on your side.
- **ReliefWeb** (UN OCHA) needs a free *app name*. Request one at
  https://apidoc.reliefweb.int/parameters#appname, then add
  `RELIEFWEB_APPNAME=your-app-name` to `.env`. Until then it is skipped.

## Adding a news source
Open `config/sources.yaml`, copy an existing block, change `name`, `url` and
`language`, and save. Set `enabled: false` to switch a source off.
Only add open, reputable sources, and leave out any site that blocks
automated access.
