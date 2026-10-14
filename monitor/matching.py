"""
Text-matching helpers shared by the keyword filter and the classifier.

The trick: before comparing, BOTH the article text and the keywords are
"normalized" the same way - lower case, no accents, no Arabic vowel marks,
punctuation turned into spaces. So "Attaqué", "attaque" and "ATTAQUE" all
become "attaque", and "Côte d'Ivoire" becomes "cote d ivoire".
"""

import re
import unicodedata

# Arabic words are often glued to a short prefix: و (and), ال (the),
# ب (in/with), ل (for)... We let Arabic keywords match with these attached.
ARABIC_PREFIX = r"(?:وال|بال|فال|كال|لل|ال|و|ف|ب|ل)?"


def normalize(text):
    """Make text easy to compare: lower case, no accents, no punctuation."""
    if not text:
        return ""
    # Split letters from their accents/marks (é -> e + ´, أ -> ا + hamza),
    # then drop the marks.
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.replace("ـ", "")                        # Arabic stretch character
    text = text.lower()
    text = re.sub(r"(?<=\d)[,.](?=\d{3}(?!\d))", "", text)   # "1,200" -> "1200"
    text = re.sub(r"[^\w\s]|_", " ", text)                   # punctuation -> space
    return re.sub(r"\s+", " ", text).strip()


def is_arabic(text):
    return any("؀" <= ch <= "ۿ" for ch in text)


def compile_term(term):
    """
    Turn a keyword from the config into a search pattern.
      "kidnap"   -> whole word only
      "kidnap*"  -> any word starting with "kidnap"
    """
    term = term.strip()
    starts_with = term.endswith("*")
    core = normalize(term.rstrip("*"))

    pattern = r"(?<!\w)"              # must start at the beginning of a word
    if is_arabic(core):
        pattern += ARABIC_PREFIX
    pattern += re.escape(core)
    if starts_with:
        pattern += r"\w*"             # take the rest of the word too
    else:
        pattern += r"(?!\w)"          # must end at the end of a word
    return re.compile(pattern)


class TermList:
    """A list of keywords, prepared once, that we can search for in text."""

    def __init__(self, terms):
        self.items = [(term, compile_term(term)) for term in terms]

    def find(self, normalized_text):
        """Return the keywords (as written in the config) found in the text."""
        return [term for term, regex in self.items if regex.search(normalized_text)]

    def words_found(self, normalized_text):
        """
        Return the distinct words in the text that match any keyword.
        "rebelles" matched by both rebel* and rebelle* counts once.
        """
        words = set()
        for _, regex in self.items:
            words.update(match.group() for match in regex.finditer(normalized_text))
        return sorted(words)
