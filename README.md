# Africa Security News Monitor

Collects open-source news about terrorism, armed attacks, kidnappings and
extremist-group activity in Africa, classifies each relevant story (country,
city, event type, group, casualties, severity 1-5), sends a daily Telegram
digest, and feeds a dashboard.

Classification is **rule-based and free** (no API key needed). Claude can be
switched on later for better summaries and accuracy.

**Parts:** a Python pipeline (fetch -> filter -> classify -> deduplicate ->
Telegram), run daily by GitHub Actions, and a Streamlit web dashboard.

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
dashboard/app.py             <- the web dashboard (Streamlit)
dashboard/requirements.txt   <- packages for the dashboard
.streamlit/config.toml       <- dashboard colours/theme
.github/workflows/daily.yml  <- the daily GitHub Actions schedule
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

## Running it every day on GitHub (GitHub Actions)

GitHub runs the monitor on its own computers every day at **07:00 UTC =
08:00 Casablanca** (07:00 Casablanca during Ramadan, when Morocco moves to
UTC+0), so it works when your computer is off. The instructions are in
`.github/workflows/daily.yml`. A private repository gets 2,000 free minutes
a month; one run takes about 1-2 minutes.

### 1. Create the repository on GitHub (once)
1. Sign in at https://github.com (create a free account if needed).
2. Click **+** (top right) -> **New repository**.
3. Name it, e.g. `africa-monitor`, choose **Private**, and do **not** tick
   "Add a README" (the project already has one). Click **Create repository**.

### 2. Upload the project (once)
In PowerShell, in the project folder (replace `YOUR-USERNAME`):

```powershell
git remote add origin https://github.com/YOUR-USERNAME/africa-monitor.git
git push -u origin main
```

The first push opens a browser window asking you to sign in to GitHub -
that's Git Credential Manager, part of Git for Windows. Refresh the GitHub
page afterwards: your files are there. `.env` is **not** uploaded
(it's listed in `.gitignore`).

### 3. Add your secrets to GitHub (once)
Repository -> **Settings** -> **Secrets and variables** -> **Actions** ->
**New repository secret**. Add each one (name exactly as written, value
copied from your `.env`):

| Name | Value |
|---|---|
| `TELEGRAM_BOT_TOKEN` | your bot token |
| `TELEGRAM_CHAT_ID` | your chat ID |
| `RELIEFWEB_APPNAME` | *(optional)* your ReliefWeb app name |

Do **not** add `MONITOR_DB` - GitHub must use the official database.
Secrets are encrypted; GitHub hides them as `***` in logs.

### 4. Run it by hand to check it works
1. Repository -> **Actions** tab. If asked, click
   **"I understand my workflows, go ahead and enable them"**.
2. Click **Daily monitor** (left) -> **Run workflow** (right).
3. First tick **Dry run** -> **Run workflow**. Nothing is sent; the
   messages appear in the log.
4. Then run it again **without** Dry run - you should get the digest on
   Telegram.

### 5. Check that the scheduled runs worked
- **Actions** tab: each run has a green ✓ (worked) or red ✗ (failed).
  Click a run, then **run-monitor**, then a step to read its log.
- After each real run, the repository shows a new commit
  **"Update database YYYY-MM-DD"** made by `github-actions[bot]`.
- If a run fails, you get a ⚠️ Telegram message with a link to the log,
  and GitHub also emails you.
- The first automatic run happens at the next 07:00 UTC. GitHub can start
  scheduled runs 5-30 minutes late at busy times - that's normal.
- GitHub pauses schedules in repositories with no activity for 60 days; the
  daily database commit counts as activity, so this shouldn't happen.

### Working on your computer after this
- The **official database** (`data/monitor.db`) now lives on GitHub and is
  updated every day. Add this line to your `.env`, so your local test runs
  use a separate copy (`data/local.db`) and never clash with it:
  ```
  MONITOR_DB=data/local.db
  ```
- **Before changing anything**, get the latest version from GitHub:
  `git pull`
- After changing code or config, upload it:
  ```powershell
  git add -A
  git commit -m "Describe what you changed"
  git push
  ```

## The dashboard

A dark, "intelligence platform" style web page to browse the events:

- **Filter rail** (left): time window, region, country, event type, group,
  minimum severity and a headline search.
- **Indicator tiles**: events, high/critical events, reported killed and
  kidnapped, countries affected - each compared with the previous period.
- **Operational map**: *Events* mode shows each report (colour and size =
  severity: 1 Low, 2 Guarded, 3 Elevated, 4 High, 5 Critical); *Heat* mode
  shows where activity concentrates.
- **Flash reports**: the most recent serious events, with links to sources.
- **Activity timeline** by region, **most affected regions**, **event types**
  and **most active groups**.
- **Event log**: searchable table with links to every source and a CSV export.

Colours and the dark theme are set in `.streamlit/config.toml` and at the top
of `dashboard/app.py`.

It only *reads* the official database `data/monitor.db` - it never changes it.

### Run it on your computer
```powershell
git pull                                  # get the latest data from GitHub
pip install -r dashboard/requirements.txt # once
streamlit run dashboard/app.py
```
It opens in your browser at http://localhost:8501. Press `Ctrl+C` in
PowerShell to stop it. Tips: drag the map to move it, use the + / - buttons
(or double-click) to zoom, and hover over a dot, bar or row for details.

### Put it online for free (Streamlit Community Cloud)
1. Go to https://share.streamlit.io and **sign in with GitHub**. When asked,
   allow Streamlit to see your **private** repositories.
2. Click **Create app** -> **Deploy a public app from GitHub** (the name is
   misleading - an app from a private repository stays private; see step 4).
3. Fill in:
   - Repository: `mhderh/africa-monitor`
   - Branch: `main`
   - Main file path: `dashboard/app.py`
   - App URL: pick a name you like
   - *Advanced settings* -> Python version **3.12**
   Click **Deploy**. The first start takes 2-3 minutes.
4. **Keep it private:** in the app, click **Share** (top right). Make sure it
   is *not* set to public, and invite the email addresses of the people
   allowed to view it (they sign in to see it). No secrets are needed - the
   dashboard only reads the database file.
5. **Updates are automatic:** every daily "Update database" commit from
   GitHub Actions makes Streamlit reload the app with the new data.
   If nobody opens the app for a while, Streamlit puts it to sleep; the next
   visitor clicks "wake up" and waits about 30 seconds.

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
