"""
The keyword filter: a quick, free check that throws away articles that are
clearly not about terrorism or armed violence in Africa.

An article is kept only if:
  1. its link isn't a sport/culture page,
  2. it doesn't contain an excluded phrase ("heart attack" ...),
  3. it names an African country or city, and
  4. it contains a STRONG violence keyword, or a WEAK one (like "attack")
     confirmed by a second sign (another weak keyword, a context word such
     as "killed" or "soldiers", or a known armed-group name).
All the word lists live in config/keywords.yaml and config/places.yaml.
"""

from functools import lru_cache

from monitor import classify_rules, config
from monitor.matching import TermList, normalize
from monitor.places import get_places


def _flatten(by_language):
    return [word for words in by_language.values() for word in words]


@lru_cache(maxsize=None)
def _lists():
    """Prepare the keyword lists once."""
    keywords = config.load("keywords")
    violence = keywords["violence_keywords"]
    return {
        "strong": TermList(_flatten(violence["strong"])),
        "weak": TermList(_flatten(violence["weak"])),
        "context": TermList(keywords["violence_context"]),
        "exclude": TermList(keywords["exclude_phrases"]),
        "exclude_url_parts": keywords["exclude_url_parts"],
    }


def check(article):
    """
    Decide whether an article is worth classifying.
    Returns (True/False, a short reason) - the reason helps when tuning keywords.
    """
    lists = _lists()

    for part in lists["exclude_url_parts"]:
        if part in article["url"]:
            return False, f"excluded link ({part})"

    title = normalize(article["title"])
    summary = normalize(article["summary"])
    text = f"{title} {summary}"

    excluded = lists["exclude"].find(text)
    if excluded:
        return False, f"excluded phrase: {excluded[0]}"

    strong = lists["strong"].find(text)
    weak = lists["weak"].words_found(text)      # distinct words, e.g. ["attack", "clashes"]
    if not strong and not weak:
        return False, "no violence keyword"

    location = get_places().locate(title, summary)
    if location is None:
        return False, f"keyword '{(strong or weak)[0]}' but no African place"
    where = location["country"]

    if strong:
        return True, f"keyword '{strong[0]}' in {where}"

    # Only weak keywords: look for a second sign of real violence.
    if len(weak) >= 2:
        return True, f"keywords '{weak[0]}' + '{weak[1]}' in {where}"
    context = lists["context"].find(text)
    if context:
        return True, f"keyword '{weak[0]}' + '{context[0]}' in {where}"
    groups = classify_rules.find_groups(text, where)
    if groups:
        return True, f"keyword '{weak[0]}' + group {groups[0]} in {where}"
    return False, f"only weak keyword '{weak[0]}', nothing confirms violence"
