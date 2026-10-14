"""
Automatic tests for the keyword filter and the rule-based classifier.
Each test feeds in a made-up headline and checks the result.

Run them from the project folder with:   python -m pytest
When you change keywords.yaml or places.yaml, run them again: if a test
fails, your change broke something that used to work.
"""

from monitor import classify_rules, prefilter


def make_article(title, summary="", url="https://example.com/news/1"):
    return {"id": 1, "title": title, "summary": summary, "url": url,
            "source": "Test", "published": "2026-10-14T06:00:00+00:00",
            "language": "en"}


def classify(title, summary=""):
    article = make_article(title, summary)
    relevant, reason = prefilter.check(article)
    assert relevant, f"should be relevant but was dropped: {reason}"
    return classify_rules.classify(article)


# ---- Keyword filter -------------------------------------------------------

def test_health_news_is_dropped():
    relevant, _ = prefilter.check(make_article("Kenya confirms second Ebola case"))
    assert not relevant


def test_heart_attack_is_dropped():
    relevant, _ = prefilter.check(
        make_article("Former Nigerian minister dies of heart attack"))
    assert not relevant


def test_sport_pages_are_dropped():
    article = make_article("Nigeria's attack leads to win over Ghana",
                           url="https://www.bbc.co.uk/sport/football/123")
    relevant, _ = prefilter.check(article)
    assert not relevant


def test_violence_outside_africa_is_dropped():
    relevant, _ = prefilter.check(make_article("Gunmen attack bank in Brazil"))
    assert not relevant


# ---- Classification -------------------------------------------------------

def test_english_attack_in_nigeria():
    event = classify("Gunmen kill 12 villagers in attack in Borno state")
    assert event["country"] == "Nigeria"
    assert event["region"] == "Lake Chad Basin"
    assert event["city"] == "Borno State"
    assert event["event_type"] == "attack"
    assert event["killed"] == 12
    assert event["severity"] == 4


def test_french_attack_in_mali():
    event = classify("Mali : au moins 30 soldats tués dans une attaque jihadiste près de Gao")
    assert event["country"] == "Mali"
    assert event["city"] == "Gao"
    assert event["event_type"] == "attack"
    assert event["killed"] == 30
    assert event["severity"] == 4


def test_arabic_al_shabaab_in_mogadishu():
    event = classify("مقتل 15 شخصا في هجوم لحركة الشباب في مقديشو")
    assert event["country"] == "Somalia"          # found through the city
    assert event["group_names"] == "al-Shabaab"
    assert event["killed"] == 15
    assert event["event_type"] == "attack"


def test_kidnapping_counts_and_severity():
    event = classify("Kidnappers abduct 20 students in Nigeria's Zamfara state")
    assert event["event_type"] == "kidnapping"
    assert event["kidnapped"] == 20
    assert event["severity"] == 4


def test_niger_is_not_nigeria():
    event = classify("Attack on army post in Niger's Tillaberi region")
    assert event["country"] == "Niger"
    assert event["region"] == "Sahel"


def test_shabaab_in_mozambique_is_islamic_state_mozambique():
    event = classify("Insurgents known locally as al-Shabaab attack Mocímboa da Praia")
    assert event["country"] == "Mozambique"
    assert event["group_names"] == "Islamic State Mozambique"


def test_specific_islamic_state_branch_wins_over_generic():
    event = classify("Islamic State West Africa Province fighters attack base in Borno")
    assert event["group_names"] == "ISWAP"


def test_mass_casualty_is_severity_5():
    event = classify("Jihadists kill more than 100 civilians in Burkina Faso village")
    assert event["killed"] == 100
    assert event["severity"] == 5


def test_year_is_not_a_death_toll():
    event = classify("Mali: anniversary of the 2012 attack that killed soldiers in Kidal")
    assert event["killed"] is None


def test_sahara_places_belong_to_morocco():
    event = classify("Rocket attack on Smara leaves one dead")
    assert event["country"] == "Morocco"
    assert event["city"] == "Smara"
    event = classify("Explosions et deux morts près de Dakhla, au Sahara occidental")
    assert event["country"] == "Morocco"


def test_numbers_are_not_linked_across_other_numbers():
    event = classify("Nigeria: Police arrest 182 suspects, rescue 31 kidnapped victims")
    assert event["kidnapped"] is None          # 182 are suspects; 31 were rescued


def test_running_totals_are_ignored():
    event = classify("Fighting in eastern DR Congo: 3,900 killed since January, UN says")
    assert event["killed"] is None
    event = classify("Mali: 45 soldiers killed since the start of the year in Menaka attacks")
    assert event["killed"] is None


def test_deaths_without_number_give_severity_3():
    event = classify("Sudan: driver killed in drone attack on aid trucks in El Fasher")
    assert event["killed"] is None
    assert event["severity"] == 3


def test_political_attack_is_dropped():
    relevant, _ = prefilter.check(make_article(
        "Kenya: Gachagua steps up his attacks on Ruto over fuel prices"))
    assert not relevant


def test_one_word_is_not_two_signs():
    # "rebelles" matches both rebel* and rebelle*, but it's still one word.
    relevant, _ = prefilter.check(make_article(
        "RDC : un ancien ministre rejoint les rebelles, selon un communiqué"))
    assert not relevant


def test_weak_keyword_with_context_is_kept():
    relevant, _ = prefilter.check(make_article("Clashes leave soldiers dead in Tillaberi"))
    assert relevant


def test_attack_without_casualties_is_severity_2():
    event = classify("Militants attack police station in Cameroon, no casualties")
    assert event["severity"] == 2
