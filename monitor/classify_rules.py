"""
Rule-based classifier: turns a relevant article into an "event" using
keyword lists and simple patterns - free, no API key needed.

It fills in the same fields Claude would:
  date, country, region, city, coordinates, event type, group(s),
  killed / injured / kidnapped, severity (1-5) + one-line reason,
  short summary, source, link, language.

Limits to know about (Claude would do better on these):
  - the summary is the feed's own headline + description, not a rewrite
  - numbers are only found when written like "12 killed" / "killing 12"
  - the date is the article's publication date, not the exact event date

To switch to Claude later, we'll add classify_claude.py with a classify()
function returning the same dictionary, and choose it in main.py.
"""

import re
from datetime import datetime, timezone
from functools import lru_cache

from monitor import config
from monitor.matching import TermList, normalize
from monitor.places import get_places

# ---------------------------------------------------------------------------
# Numbers written as words
# ---------------------------------------------------------------------------
NUMBER_WORDS = {
    # English
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
    "fifteen": 15, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
    "hundred": 100, "dozen": 12, "dozens": 24, "scores": 40, "hundreds": 200,
    # French ("un/une" left out: they usually just mean "a")
    "deux": 2, "trois": 3, "quatre": 4, "cinq": 5, "sept": 7, "huit": 8,
    "neuf": 9, "dix": 10, "onze": 11, "douze": 12, "quinze": 15, "vingt": 20,
    "trente": 30, "quarante": 40, "cinquante": 50, "cent": 100,
    "dizaine": 10, "dizaines": 20, "centaine": 100, "centaines": 200,
    # Arabic ("dozens")
    "عشرات": 20,
}

NUMBER = r"(?P<num>\d{1,5}|" + "|".join(NUMBER_WORDS) + r")"
# Words like "at least", "about" that may sit between a verb and the number.
QUALIFIER = r"(?:(?:at least|about|around|some|more than|over|au moins|plus de|pres de|environ|ما لا يقل عن|نحو|اكثر من)\s+)?"
NOT_A_DURATION = r"(?!\s+(?:year|years|ans|an|day|days|jours|month|months|mois|km)\b)"


def _patterns(words_after, words_before):
    """
    Build two patterns for one kind of casualty, e.g. for "killed":
      "<number> ... killed"   -> "12 soldiers were killed", "30 tues"
      "killing <number>"      -> "killing at least 12", "مقتل 15"
    The words in between may not be numbers, so in "182 suspects, 31
    kidnapped" only 31 is linked to "kidnapped".
    """
    after = (r"(?<!\w)" + NUMBER + NOT_A_DURATION
             + r"(?:\s+(?!\d)\w+){0,4}?\s+(?:" + words_after + r")(?!\w)")
    before = (r"(?<!\w)(?:" + words_before + r")\s+" + QUALIFIER + NUMBER + r"(?!\w)")
    return [re.compile(after), re.compile(before)]


KILLED = _patterns(
    words_after="killed|dead|died|deaths|bodies|tues|tuees|morts|قتيلا|قتلى|قتيل",
    words_before="killed|killing|kills|kill|tuant|tue|tuent|مقتل|قتل",
) + [re.compile(r"(?<!\w)(?:death toll|toll|bilan)(?:\s+\w+){0,5}?\s+" + NUMBER + r"(?!\w)")]

INJURED = _patterns(
    words_after="wounded|injured|hurt|blesses|blessees|جرحى|جريحا|مصابين|مصابا",
    words_before="wounding|injuring|injured|wounded|blessant|اصابة|واصابة",
)

KIDNAPPED = _patterns(
    words_after="kidnapped|abducted|enleves|enlevees|kidnappes|مختطفين|مختطفا|رهائن",
    words_before="kidnapped|kidnapping|kidnap|kidnaps|abducted|abducting|abduct|abducts|"
                 "enleve|enlevent|اختطاف|خطف",
)


# Numbers this big are almost always running totals ("3,900 killed this
# year"), not one incident, so we ignore them.
MAX_SINGLE_INCIDENT = 1000

# Words right after a number that show it's a running total, not one event.
CUMULATIVE = re.compile(
    r"^\W*(?:\w+\W+){0,4}?(?:since|so far|this year|in recent|over the past|"
    r"depuis|cette annee|منذ|هذا العام)")


def _to_number(word):
    if word.isdigit():
        return int(word)           # also works for Arabic digits like ١٢
    return NUMBER_WORDS.get(word)


def extract_count(text, patterns, skip_if_before=None):
    """
    Return the largest number found by the patterns, or None.
    `skip_if_before` (a TermList) ignores numbers that have one of its words
    just before them - e.g. "rescued 31 kidnapped" isn't a new kidnapping.
    """
    best = None
    for regex in patterns:
        for match in regex.finditer(text):
            value = _to_number(match.group("num"))
            if value is None or 1900 <= value <= 2100:   # skip years like 2024
                continue
            if value >= MAX_SINGLE_INCIDENT:
                continue
            if CUMULATIVE.match(text[match.end():]):
                continue
            if skip_if_before and skip_if_before.find(text[max(0, match.start() - 30):match.start()]):
                continue
            if best is None or value > best:
                best = value
    return best


# ---------------------------------------------------------------------------
# Event type, groups, severity
# ---------------------------------------------------------------------------

@lru_cache(maxsize=None)
def _rules():
    """Prepare the keyword lists from config/keywords.yaml once."""
    keywords = config.load("keywords")
    return {
        "event_types": [(name, TermList(words))
                        for name, words in keywords["event_types"].items()],
        "severe_terms": TermList(keywords["severe_terms"]),
        "death_words": TermList(keywords["death_words"]),
        "rescue_words": TermList(keywords["rescue_words"]),
        "groups": [(group, TermList(group["aliases"])) for group in keywords["groups"]],
    }


def find_event_type(text):
    for name, terms in _rules()["event_types"]:     # in the order of the config file
        if terms.find(text):
            return name
    return "other"


def find_groups(text, country):
    """Return the names of groups mentioned, e.g. ["JNIM (al-Qaeda Sahel)"]."""
    groups = _rules()["groups"]
    found = []
    for group, aliases in groups:
        if "only_countries" in group and country not in group["only_countries"]:
            continue
        if "not_countries" in group and country in group["not_countries"]:
            continue
        if aliases.find(text):
            found.append(group)
    # Drop "Islamic State (unspecified)" etc. if a specific group was found.
    specific = [g for g in found if not g.get("generic")]
    return [g["name"] for g in (specific or found)]


def score_severity(event_type, killed, injured, kidnapped, severe_words, deaths_mentioned=False):
    """Return (severity 1-5, one-line reason)."""
    killed, injured, kidnapped = killed or 0, injured or 0, kidnapped or 0

    if killed >= 50:
        return 5, f"Mass-casualty event: {killed} killed reported"
    if kidnapped >= 50:
        return 5, f"Mass kidnapping: {kidnapped} abducted reported"
    if killed >= 10:
        return 4, f"{killed} killed reported"
    if kidnapped >= 10:
        return 4, f"{kidnapped} people kidnapped reported"
    if severe_words:
        return 4, f"Serious attack type reported ({severe_words[0].rstrip('*')})"
    if killed >= 1:
        return 3, f"{killed} killed reported"
    if deaths_mentioned and event_type != "threat":
        return 3, "Deaths reported (number not given)"
    if kidnapped >= 1 or event_type == "kidnapping":
        return 3, "Kidnapping reported"
    if injured >= 5:
        return 3, f"{injured} injured reported, no deaths reported"
    if event_type in ("attack", "military operation", "arrest"):
        return 2, f"{event_type.capitalize()} with no casualties reported"
    if event_type == "threat":
        return 1, "Threat or warning, no violence reported"
    return 1, "Security-related news, no violent incident identified"


def make_summary(title, summary, max_length=350):
    """Headline + feed description, shortened to about 2-3 sentences."""
    text = title.strip()
    if not text.endswith((".", "?", "!")):
        text += "."
    if summary and summary.lower() not in title.lower():
        text += " " + summary.strip()
    if len(text) <= max_length:
        return text
    cut = text[:max_length]
    last_full_stop = cut.rfind(". ")
    if last_full_stop > len(title):
        return cut[:last_full_stop + 1]
    return cut.rsplit(" ", 1)[0] + "..."


def classify(article):
    """
    Turn one article (a dict with title, summary, url, source, published,
    language) into an event dict ready to be saved in the events table.
    Returns None if no African location can be found.
    """
    title = normalize(article["title"])
    summary = normalize(article["summary"])
    text = f"{title} {summary}"

    location = get_places().locate(title, summary)
    if location is None:
        return None

    rules = _rules()
    event_type = find_event_type(text)
    killed = extract_count(text, KILLED)
    injured = extract_count(text, INJURED)
    kidnapped = extract_count(text, KIDNAPPED, skip_if_before=rules["rescue_words"])
    severity, reason = score_severity(event_type, killed, injured, kidnapped,
                                      rules["severe_terms"].find(text),
                                      deaths_mentioned=bool(rules["death_words"].find(text)))

    event_date = (article.get("published") or article.get("fetched_at")
                  or datetime.now(timezone.utc).isoformat())[:10]

    return {
        "article_id": article.get("id"),
        "event_date": event_date,
        **location,
        "event_type": event_type,
        "group_names": "; ".join(find_groups(text, location["country"])) or None,
        "killed": killed,
        "injured": injured,
        "kidnapped": kidnapped,
        "severity": severity,
        "severity_reason": reason,
        "summary": make_summary(article["title"], article["summary"]),
        "source": article["source"],
        "url": article["url"],
        "language": article["language"],
        "classifier": "rules",
    }
