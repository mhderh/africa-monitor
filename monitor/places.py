"""
Finds which African country (and, if possible, which city) an article is
about, using config/places.yaml.
"""

from functools import lru_cache

from monitor import config
from monitor.matching import compile_term


class Places:
    def __init__(self):
        data = config.load("places")
        self.countries = data["countries"]                       # name -> details
        self.cities = {city["name"]: city for city in data["cities"]}

        # Every alias, labelled with what it points to.
        aliases = []
        for name, info in self.countries.items():
            aliases += [(alias, "country", name) for alias in info["aliases"]]
        for name, info in self.cities.items():
            aliases += [(alias, "city", name) for alias in info["aliases"]]

        # Longest aliases first, so "South Sudan" is found before "Sudan".
        aliases.sort(key=lambda a: len(a[0]), reverse=True)
        self.patterns = [(compile_term(alias), kind, name) for alias, kind, name in aliases]

    def find(self, text):
        """
        Return (countries, cities) named in the normalized text, each a list
        of names in the order they first appear.
        """
        found = []          # (position in text, "country" or "city", name)
        for regex, kind, name in self.patterns:
            for match in regex.finditer(text):
                found.append((match.start(), kind, name))
            # Blank out what we matched, so "Sudan" inside "South Sudan"
            # isn't counted again by a shorter alias.
            text = regex.sub(lambda m: " " * len(m.group()), text)
        found.sort()
        countries, cities = [], []
        for _, kind, name in found:
            target = countries if kind == "country" else cities
            if name not in target:
                target.append(name)
        return countries, cities

    def locate(self, title, summary):
        """
        Work out the main location of an article (both texts normalized).
        Places named in the title count first. Returns a dict, or None if no
        African place is mentioned.
        """
        title_countries, title_cities = self.find(title)
        summary_countries, summary_cities = self.find(summary)
        countries = title_countries + [c for c in summary_countries if c not in title_countries]
        cities = title_cities + [c for c in summary_cities if c not in title_cities]

        country = countries[0] if countries else None
        city = None
        for name in cities:
            # Use the city only if it's in the article's main country
            # (or if no country was named at all).
            if country is None or self.cities[name]["country"] == country:
                city = self.cities[name]
                country = city["country"]
                break

        if country is None:
            return None

        point = city or self.countries[country]
        return {
            "country": country,
            "region": self.countries[country]["region"],
            "city": city["name"] if city else None,
            "latitude": point["lat"],
            "longitude": point["lon"],
            "location_precision": "city" if city else "country",
        }


@lru_cache(maxsize=None)
def get_places():
    """Build the Places lookup once and reuse it."""
    return Places()
