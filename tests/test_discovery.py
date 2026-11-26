"""
Property discovery - tested offline against a small fake "Manali".

The fake web contains real-looking platform pages (Tripadvisor, Booking,
Hostelworld, Zomato) and two "best of" articles, plus traps:
  * a landmark ("Solang Valley") that appears in an article heading
  * a venue with 3 reviews and a perfect rating
  * a venue named only in articles, with no platform listing
  * a steakhouse that is not a cafe
  * another branch of a chain in a different town (must not be counted)
"""

import json
from pathlib import Path

import pytest

from app.schemas.source import SearchResult
from app.tools.source_types import classify_url
from app.tools.web_search import SearchUnavailable
from app.workflows import discovery as d
from app.workflows import vibers_brief

NOW = 2026
PLACE = "Manali"


def R(title, url, snippet):
    source_type, platform = classify_url(url)

    return SearchResult(title=title, url=url, snippet=snippet, source_type=source_type, platform=platform)


TA = "https://www.tripadvisor.in/"

STAY_DISCOVERY = [
    R("ZOSTEL MANALI - Updated 2025 Prices & Hostel Reviews (India)",
      TA + "Hotel_Review-g304552-d111-Reviews-Zostel_Manali-Manali.html",
      "Zostel Manali, Manali: Rated 4.5 of 5 at Tripadvisor. See 1,234 reviews."),
    R("The Hosteller Manali, Old Manali - Hostel Reviews",
      TA + "Hotel_Review-g304552-d222-Reviews-The_Hosteller_Manali-Manali.html",
      "The Hosteller Manali: Rated 4.4 of 5. 820 reviews."),
    R("Johnson Lodge - Hotel in Manali",
      "https://www.booking.com/hotel/in/johnson-lodge.html",
      "Johnson Lodge Manali. Scored 8.4 · 650 reviews. Serving guests since 1996."),
    R("Hotel Obscure, Manali – Updated Prices",
      "https://www.booking.com/hotel/in/hotel-obscure.html",
      "Hotel Obscure Manali. Rated 5.0 of 5. 3 reviews."),
    R("10 Best Hostels in Manali (2025 guide)",
      "https://travelblog.example.com/best-hostels-manali", "A guide to hostels."),
    R("Top hotels in Manali - backpacker picks",
      "https://wanderers.example.org/top-hotels-manali", "Our favourite hotels."),
]

STAY_HEADINGS = {
    "https://travelblog.example.com/best-hostels-manali": [
        "Introduction", "1. Zostel Manali", "2. The Hosteller – Old Manali", "3. Solang Valley",
        "4. Moustache Hostel Manali", "5. Hotel Obscure", "Conclusion", "FAQs",
    ],
    "https://wanderers.example.org/top-hotels-manali": [
        "Zostel Manali", "Johnson's Lodge", "Moustache Hostel Manali", "Why Stay in Old Manali?",
    ],
}

CAFE_DISCOVERY = [
    R("Cafe 1947, Old Manali, Manali - Restaurant Reviews - Tripadvisor",
      TA + "Restaurant_Review-g304552-d333-Reviews-Cafe_1947-Manali.html",
      "Cafe 1947 Manali: Rated 4.5 of 5. 1,800 reviews. Coffee and breakfast."),
    R("Dylan's Toasted & Roasted, Manali - Zomato",
      "https://www.zomato.com/manali/dylans-toasted-roasted-old-manali",
      "Dylan's Toasted & Roasted coffee shop in Old Manali. 4.2 ★ (900)"),
    R("Random Grill Manali, Manali - Tripadvisor",
      TA + "Restaurant_Review-g304552-d444-Reviews-Random_Grill-Manali.html",
      "Random Grill Manali: Rated 4.6 of 5. 700 reviews. Steakhouse."),
    R("Best cafes in Manali - 12 cafes you must visit",
      "https://cafeguide.example.com/best-cafes-manali", "Cafes."),
    R("Top coffee shops in Manali",
      "https://coffee.example.net/top-coffee-manali", "Coffee."),
]

CAFE_HEADINGS = {
    "https://cafeguide.example.com/best-cafes-manali": [
        "1. Cafe 1947", "2. Dylan's Toasted & Roasted", "3. Mall Road", "Conclusion"],
    "https://coffee.example.net/top-coffee-manali": ["Cafe 1947", "Dylan's Toasted & Roasted"],
}

PROBES = {
    "zostel manali": [
        R("Zostel Manali - Hostel in Manali | Hostelworld",
          "https://www.hostelworld.com/hostels/p/267409/zostel-manali/",
          "Zostel Manali, Old Manali. Rating 9.1 (3,000+ reviews)."),
        R("Zostel Manali reviews - Booking.com",
          "https://www.booking.com/hotel/in/zostel-manali.html",
          "Zostel Manali Scored 8.8 · 2,100 reviews. Opened in 2014."),
        R("Zostel Manali : r/manali", "https://www.reddit.com/r/manali/comments/x/zostel_manali/",
          "stayed at zostel manali last year, loved it"),
        # another town: must be ignored even though it has far more reviews
        R("Zostel Kasol - Hostelworld", "https://www.hostelworld.com/hostels/p/1/zostel-kasol/",
          "Zostel Kasol in the Parvati valley. Rating 9.0 (9,000+ reviews)."),
    ],
    "the hosteller manali": [
        R("The Hosteller Manali - Booking.com", "https://www.booking.com/hotel/in/the-hosteller-manali.html",
          "The Hosteller Manali, Old Manali. Scored 8.6 · 1,100 reviews."),
        R("The Hosteller Manali : r/manali", "https://www.reddit.com/r/manali/comments/y/",
          "The Hosteller Manali was clean"),
        R("The Hosteller Manali Instagram", "https://www.instagram.com/thehosteller/",
          "The Hosteller Manali events"),
    ],
    "johnson's lodge": [
        R("Johnson's Lodge Manali - Tripadvisor", TA + "Hotel_Review-g304552-d555-Reviews-Johnson_s_Lodge-Manali.html",
          "Johnson's Lodge Manali: Rated 4.2 of 5. 640 reviews."),
        R("Johnson's Lodge, Manali - Agoda", "https://www.agoda.com/johnsons-lodge/hotel/manali-in.html",
          "Johnson's Lodge Manali, a riverside hotel."),
    ],
    "hotel obscure": [],
    "moustache hostel manali": [
        R("Moustache Hostel Manali blog", "https://blog.example.com/moustache-manali", "Moustache Hostel Manali is fun."),
    ],
    "solang valley": [
        R("Solang Valley, Manali - travel guide", "https://guide.example.com/solang", "Solang Valley near Manali."),
        R("Solang Valley Manali - blog", "https://one.example.com/solang", "Solang Valley Manali adventure."),
        R("Solang Valley Manali - blog 2", "https://two.example.com/solang", "Solang Valley Manali snow."),
        R("Solang Valley Manali - blog 3", "https://three.example.com/solang", "Solang Valley Manali ropeway."),
        R("Solang Valley Manali - blog 4", "https://four.example.com/solang", "Solang Valley Manali skiing."),
    ],
    "cafe 1947": [
        R("Cafe 1947 - Zomato", "https://www.zomato.com/manali/cafe-1947-old-manali",
          "Cafe 1947 Old Manali Manali. 4.4 ★ (2.3K). Serving guests since 2009."),
        R("Cafe 1947 Manali blog", "https://food.example.com/cafe-1947", "Cafe 1947 in Manali is a river-view cafe."),
    ],
    "dylan's toasted & roasted": [
        R("Dylan's Toasted & Roasted Manali - Tripadvisor",
          TA + "Restaurant_Review-g304552-d666-Reviews-Dylan_s_Toasted_Roasted-Manali.html",
          "Dylan's Toasted & Roasted Manali: Rated 4.3 of 5. 500 reviews."),
        R("Dylan's Toasted & Roasted Manali review", "https://food.example.com/dylans",
          "Dylan's Toasted & Roasted Manali has great coffee."),
    ],
    "random grill manali": [],
}


class FakeWeb:
    def __init__(self):
        self.queries = []

    def search(self, query, max_results=5, official_domains=()):
        self.queries.append(query)

        normalised = d._norm(query)

        for name, results in PROBES.items():
            if d._norm(name) in normalised:
                return list(results)

        q = query.lower()

        if "cafe" in q or "coffee" in q:
            return list(CAFE_DISCOVERY)

        return list(STAY_DISCOVERY)

    def headings(self, url, max_headings=80):
        return list({**STAY_HEADINGS, **CAFE_HEADINGS}.get(url, []))


@pytest.fixture
def web(monkeypatch):
    fake = FakeWeb()

    monkeypatch.setattr("app.workflows.discovery.search_web", fake.search)
    monkeypatch.setattr("app.workflows.discovery.fetch_headings", fake.headings)

    return fake


def run(**kwargs):
    return d.discover(PLACE, now_year=NOW, log=lambda *_: None, **kwargs)


# ------------------------------------------------------------------
# Pure helpers
# ------------------------------------------------------------------

@pytest.mark.parametrize(
    "text, rating, count",
    [
        ("Zostel Manali: Rated 4.5 of 5 at Tripadvisor. See 1,234 reviews.", 4.5, 1234),
        ("Rating 9.1 (3,000+ reviews) Hostelworld", 4.55, 3000),
        ("Cafe 1947 4.4 ★ (2.3K) Cafe Old Manali", 4.4, 2300),
        ("Scored 8.8 · 1,204 reviews - Booking.com", 4.4, 1204),
        ("#3 of 10 hostels in Manali - 215 reviews", None, 215),   # a rank is not a rating
        ("A highly rated 4 star hotel with a garden", None, None),  # star class is not a rating
        ("5 star reviews from happy guests", None, None),
    ],
)
def test_parse_signals(text, rating, count):
    got_rating, _, got_count = d.parse_signals(text)

    assert (round(got_rating, 2) if got_rating is not None else None) == rating
    assert got_count == count


def test_parse_count_handles_k_and_commas():
    assert d.parse_count("1,234") == 1234
    assert d.parse_count("2.3K") == 2300
    assert d.parse_count("12k") == 12000
    assert d.parse_count("nonsense") is None
    assert d.parse_count("9999999") is None  # implausible


def test_parse_start_year():
    assert d.parse_start_year("serving guests since 1996", NOW) == 1996
    assert d.parse_start_year("Established in 2012 in Old Manali", NOW) == 2012
    assert d.parse_start_year("operating for over 15 years", NOW) == NOW - 15
    assert d.parse_start_year("opened in 2031", NOW) is None
    assert d.parse_start_year("stay for 3 years", NOW) is None


@pytest.mark.parametrize(
    "name, ok",
    [
        ("Zostel Old Manali", True), ("The Hosteller Manali", True), ("Johnson's Lodge", True),
        ("Cafe 1947", True), ("Dylan's Toasted & Roasted", True),
        ("Old Manali", False), ("Mall Road", False), ("Hostels in Manali", False),
        ("10 Best Hostels in Manali", False), ("Why Stay in Old Manali", False),
        ("Is Manali safe?", False), ("Frequently Asked Questions", False), ("Conclusion", False),
    ],
)
def test_valid_name(name, ok):
    assert d.valid_name(name, PLACE) is ok


def test_names_from_titles_and_headings():
    assert d.name_from_title("ZOSTEL MANALI - Updated 2025 Prices & Hostel Reviews (India)", PLACE) == "Zostel Manali"
    assert d.name_from_title("Cafe 1947, Old Manali, Manali - Restaurant Reviews", PLACE) == "Cafe 1947"
    assert d.name_from_title("Zostel Manali, Manali – Updated 2025 Prices", PLACE) == "Zostel Manali"
    assert d.name_from_heading("2) The Hosteller – Old Manali", PLACE) == "The Hosteller"
    assert d.name_from_heading("3. Cafe 1947 (Old Manali)", PLACE) == "Cafe 1947"
    assert d.is_numbered("1. Zostel") and not d.is_numbered("10 Best Hostels")


def test_chain_branches_and_spellings_merge_but_other_venues_do_not():
    assert d.candidate_key("Zostel Manali", PLACE) == d.candidate_key("Zostel Old Manali", PLACE)
    assert d.candidate_key("The Hosteller Manali, Old Manali", PLACE) == d.candidate_key("The Hosteller", PLACE)
    assert d.candidate_key("Cafe 1947", PLACE) != d.candidate_key("Cafe 1948", PLACE)


def test_property_page_recognises_platform_pages_only():
    stay = d.property_page(TA + "Hotel_Review-g1-d2-Reviews-Zostel_Manali-Manali.html", "ZOSTEL MANALI - Updated", PLACE)
    cafe = d.property_page(TA + "Restaurant_Review-g1-d2-Reviews-Cafe_1947-Manali.html", "Cafe 1947, Manali - Tripadvisor", PLACE)

    assert stay == ("stay", "Zostel Manali")
    assert cafe == ("cafe", "Cafe 1947")
    assert d.property_page("https://www.booking.com/hotel/in/x.html", "Hotel X, Manali – Prices", PLACE) == ("stay", "Hotel X")
    assert d.property_page(TA + "Hotels-g304552-Manali-Hotels.html", "THE 10 BEST Manali Hotels", PLACE) is None
    assert d.property_page("https://www.zomato.com/manali/restaurants", "Best restaurants", PLACE) is None
    assert d.property_page("https://travelblog.example.com/best", "Best hostels", PLACE) is None
    assert d.property_page("https://www.google.com/maps/place/Zostel+Manali/@1,2", "x", PLACE) == (None, "Zostel Manali")


def test_site_key_counts_each_platform_once():
    assert d.site_key("https://in.tripadvisor.com/x") == d.site_key("https://www.tripadvisor.in/y") == "Tripadvisor"
    assert d.site_key("https://blog.example.co.in/p") == "example.co.in"


# ------------------------------------------------------------------
# Discovery end to end
# ------------------------------------------------------------------

def test_discovers_the_strongest_properties_without_a_list(web):
    selection = run(stays=3, cafes=2)

    stays = [i["name"] for i in selection["stays"]["selected"]]
    cafes = [i["name"] for i in selection["cafes"]["selected"]]

    assert set(stays) == {"Zostel Manali", "The Hosteller Manali", "Johnson's Lodge"}
    assert set(cafes) == {"Cafe 1947", "Dylan's Toasted & Roasted"}

    # the strongest evidence ranks first
    assert stays[0] == "Zostel Manali"
    assert selection["notes"] == []
    assert selection["stays"]["qualified"] == 3 and selection["stays"]["shortfall"] == 0


def test_numbers_come_from_the_pages_and_other_towns_are_ignored(web):
    selection = run(stays=3, cafes=2)

    zostel = next(i for i in selection["stays"]["selected"] if i["name"] == "Zostel Manali")

    # Tripadvisor 1,234 + Hostelworld 3,000 + Booking 2,100 - Kasol's 9,000 is NOT included
    assert zostel["total_reviews"] == 1234 + 3000 + 2100
    assert zostel["earliest_year"] == 2014 and zostel["age_years"] == NOW - 2014
    assert zostel["type"] == "hostel"
    assert zostel["platforms"]["Tripadvisor"]["reviews"] == 1234
    assert zostel["score"] == pytest.approx(sum(zostel["components"].values()), abs=0.2)
    assert all(0 <= v <= w for v, w in
               ((zostel["components"][k], d.SCORE_WEIGHTS[k]) for k in d.SCORE_WEIGHTS))

    johnson = next(i for i in selection["stays"]["selected"] if i["name"] == "Johnson's Lodge")
    assert johnson["earliest_year"] == 1996
    assert johnson["type"] == "hotel"


def test_traps_are_rejected_with_a_reason(web):
    selection = run(stays=3, cafes=2)

    reasons = {r["name"]: r["reason"] for r in selection["stays"]["rejected"]}

    assert "Hotel Obscure" in reasons and "independent source" in reasons["Hotel Obscure"]      # 3 reviews, 2 sources
    assert "Moustache Hostel Manali" in reasons and "platform listing" in reasons["Moustache Hostel Manali"]
    assert "Solang Valley" in reasons and "platform listing" in reasons["Solang Valley"]        # landmark, not a venue

    cafe_reasons = {r["name"]: r["reason"] for r in selection["cafes"]["rejected"]}

    assert "does not look like a cafe" in cafe_reasons["Random Grill Manali"]
    assert "Mall Road" not in cafe_reasons  # never even a candidate


def test_a_perfect_rating_from_three_reviews_cannot_win():
    strong = d.Candidate(key="a", kind="stay")
    strong.signals = [d.Signal("Tripadvisor", 4.4, "4.4/5", 2000)]
    tiny = d.Candidate(key="b", kind="stay")
    tiny.signals = [d.Signal("Tripadvisor", 5.0, "5/5", 3)]

    d.score_candidate(strong, NOW)
    d.score_candidate(tiny, NOW)

    assert strong.components["rating"] > tiny.components["rating"]
    assert strong.score > tiny.score


def test_missing_evidence_scores_zero_not_a_guess():
    empty = d.Candidate(key="x", kind="stay")

    stats = d.score_candidate(empty, NOW)

    assert empty.score == 0 and stats["total_reviews"] == 0
    assert stats["avg_rating"] is None and stats["earliest_year"] is None


def test_shortfall_is_reported_not_padded(web):
    selection = run(stays=5, cafes=2)

    assert len(selection["stays"]["selected"]) == 3
    assert selection["stays"]["qualified"] == 3 and selection["stays"]["shortfall"] == 2
    assert any("Only 3 of the 5 requested stays" in note for note in selection["notes"])


def test_allow_thin_fills_with_flagged_real_venues_only(web):
    selection = run(stays=5, cafes=2, allow_thin=True)

    selected = selection["stays"]["selected"]
    thin = [i for i in selected if i["thin"]]
    names = {i["name"] for i in selected}

    assert [i["name"] for i in thin] == ["Hotel Obscure"]
    assert "Solang Valley" not in names and "Moustache Hostel Manali" not in names  # not reviewable venues
    assert selection["stays"]["shortfall"] == 1


def test_lower_thresholds_admit_more(web):
    strict = run(stays=3, cafes=0, min_sites=3)
    lax = run(stays=3, cafes=0, min_sites=2, min_reviews=1)

    assert "Hotel Obscure" not in [i["name"] for i in strict["stays"]["selected"]]
    assert "Hotel Obscure" in [i["name"] for i in lax["stays"]["selected"]] or lax["stays"]["reserves"]


def test_silence_from_the_search_engine_is_reported(monkeypatch):
    monkeypatch.setattr("app.workflows.discovery.search_web", lambda *a, **k: [])
    monkeypatch.setattr("app.workflows.discovery.fetch_headings", lambda url, max_headings=80: [])

    selection = run(stays=3, cafes=2)

    assert selection["stays"]["selected"] == [] and selection["cafes"]["selected"] == []
    assert any("returned nothing" in note for note in selection["notes"])


def test_a_blocked_search_engine_stops_the_run_with_advice(monkeypatch):
    calls = []

    def broken(query, max_results=5, official_domains=()):
        calls.append(query)
        raise ConnectionError("blocked")

    monkeypatch.setattr("app.workflows.discovery.search_web", broken)
    monkeypatch.setattr("app.workflows.discovery.fetch_headings", lambda url, max_headings=80: [])

    with pytest.raises(SearchUnavailable) as caught:
        run(stays=3, cafes=2)

    assert "in a row" in str(caught.value) and "nothing was saved" in str(caught.value)
    assert len(calls) == d.MAX_CONSECUTIVE_SEARCH_FAILURES        # it did not carry on regardless
    assert d.load_selection(PLACE) is None


def test_patchy_searching_is_flagged_as_unreliable_but_finishes(web, monkeypatch):
    real = web.search
    counter = {"n": 0}

    def patchy(query, max_results=5, official_domains=()):
        counter["n"] += 1

        if counter["n"] % 3 == 0:                      # every third search fails
            raise TimeoutError("timed out")

        return real(query, max_results=max_results, official_domains=official_domains)

    monkeypatch.setattr("app.workflows.discovery.search_web", patchy)

    lines = []
    selection = d.discover(PLACE, stays=3, cafes=2, now_year=NOW, log=lines.append)

    stats = selection["search_stats"]

    assert stats["failed_queries"] > 0 and stats["degraded"] is True
    assert any(note.startswith("WARNING") for note in selection["notes"])
    assert any("WARNING" in line for line in lines)
    assert "failed even after retrying" in d.render_selection_markdown(selection)


def test_one_or_two_failed_searches_are_not_called_unreliable(web, monkeypatch):
    real = web.search
    counter = {"n": 0}

    def once(query, max_results=5, official_domains=()):
        counter["n"] += 1

        if counter["n"] == 2:
            raise TimeoutError("timed out")

        return real(query, max_results=max_results, official_domains=official_domains)

    monkeypatch.setattr("app.workflows.discovery.search_web", once)

    selection = d.discover(PLACE, stays=3, cafes=2, now_year=NOW, log=lambda *_: None)

    assert selection["search_stats"]["failed_queries"] == 1
    assert selection["search_stats"]["degraded"] is False
    assert not any(note.startswith("WARNING") for note in selection["notes"])


def test_an_unreliable_saved_selection_is_redone_unless_edited_by_hand(web):
    selection = d.discover(PLACE, stays=3, cafes=2, now_year=NOW, log=lambda *_: None)
    selection["search_stats"]["degraded"] = True
    d.save_selection(selection)

    before = len(web.queries)
    d.get_selection(PLACE, stays=3, cafes=2, now_year=NOW, log=lambda *_: None)

    assert len(web.queries) > before                  # searched again

    saved = d.load_selection(PLACE)
    saved["search_stats"]["degraded"] = True
    d.edit_selection(saved, "remove", saved["stays"]["selected"][0]["name"])
    d.save_selection(saved)

    before = len(web.queries)
    again = d.get_selection(PLACE, stays=3, cafes=2, now_year=NOW, log=lambda *_: None)

    assert len(web.queries) == before                 # the user's hand edit is respected
    assert any(note.startswith("Edited by hand") for note in again["notes"])


# ------------------------------------------------------------------

def test_selection_is_saved_and_reused_without_searching_again(web):
    first = d.get_selection(PLACE, stays=3, cafes=2, now_year=NOW, log=lambda *_: None)

    searches = len(web.queries)

    again = d.get_selection(PLACE, stays=3, cafes=2, now_year=NOW, log=lambda *_: None)

    assert len(web.queries) == searches
    assert again["created_at"] == first["created_at"]
    assert d.load_selection(PLACE)["stays"]["selected"] == first["stays"]["selected"]

    d.get_selection(PLACE, stays=3, cafes=2, rediscover=True, now_year=NOW, log=lambda *_: None)

    assert len(web.queries) > searches


def test_report_is_honest_about_what_it_is(web):
    text = d.render_selection_markdown(run(stays=3, cafes=2))

    assert "**RESEARCHED**" in text
    assert "not shown" in text                       # unknown, not zero
    assert "Zostel Manali" in text and "since 2014" in text
    assert "not for how good it is" in text          # the score is evidence volume
    assert "Considered but not chosen" in text and "Solang Valley" in text
    assert "Google Maps and Instagram cannot be read" in text


# ------------------------------------------------------------------
# From selection to studied properties
# ------------------------------------------------------------------

def _profile(name, items, sites):
    evidence = [
        {"claim": f"{name} passage {i}", "source_url": f"https://{sites[i % len(sites)]}/p{i}"}
        for i in range(items)
    ]

    return {"key": name, "spec": {"name": name}, "evidence": evidence, "manual_note_count": 0}


def _fake_selection():
    def item(name):
        return {"name": name, "type": "hostel", "kind": "stay", "score": 50, "thin": False}

    return {
        "place": PLACE,
        "created_at": "now",
        "params": {"stays": 3, "cafes": 0},
        "notes": [],
        "stays": {"requested": 3, "selected": [item("A"), item("B"), item("C")],
                  "reserves": [item("D")], "rejected": []},
        "cafes": {"requested": 0, "selected": [], "reserves": [], "rejected": []},
    }


def test_thin_research_swaps_in_a_reserve_and_the_final_list_is_saved(monkeypatch):
    thin = {"A"}

    def fake_profile(spec, depth="standard", refresh=False, log=print):
        if spec.name in thin:
            return _profile(spec.name, 2, ["x.com"])

        return _profile(spec.name, 10, ["a.com", "b.com", "c.com", "d.com"])

    monkeypatch.setattr("app.workflows.discovery.profile_property", fake_profile)

    selection = _fake_selection()

    specs = d.profile_selection(selection, log=lambda *_: None)

    assert sorted(s.name for s in specs) == ["B", "C", "D"]
    assert selection["profiling_changes"] == [
        {"dropped": "A", "reason": "only 2 evidence passages from 1 source(s)", "replaced_by": "D"}
    ]
    assert d.load_selection(PLACE)["stays"]["final"] == ["D", "B", "C"]

    # a later run keeps the same final list and does not retry the dropped one
    again = d.profile_selection(d.load_selection(PLACE), log=lambda *_: None)

    assert sorted(s.name for s in again) == ["B", "C", "D"]


def test_thin_property_with_no_reserve_is_kept_and_flagged(monkeypatch):
    monkeypatch.setattr(
        "app.workflows.discovery.profile_property",
        lambda spec, depth="standard", refresh=False, log=print: _profile(spec.name, 1, ["x.com"]),
    )

    selection = _fake_selection()
    selection["stays"]["reserves"] = []

    specs = d.profile_selection(selection, log=lambda *_: None)

    assert [s.name for s in specs] == ["A", "B", "C"]
    assert any("treat its findings as thin" in note for note in selection["notes"])


def test_manual_notes_count_as_enough_evidence():
    profile = _profile("A", 1, ["x.com"])
    profile["manual_note_count"] = 3

    assert d.evidence_ok(profile)[0] is True
    assert d.evidence_ok(_profile("A", 1, ["x.com"]))[0] is False


def test_render_only_never_researches(monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("must not research in render-only mode")

    monkeypatch.setattr("app.workflows.discovery.profile_property", boom)

    specs = d.profile_selection(_fake_selection(), render_only=True, log=lambda *_: None)

    assert [s.name for s in specs] == ["A", "B", "C"]


# ------------------------------------------------------------------
# The brief and the study use discovery
# ------------------------------------------------------------------

def test_brief_discovers_its_own_properties(web, world, isolated_research_dir, monkeypatch):
    monkeypatch.setattr("app.workflows.discovery.evidence_ok", lambda *a, **k: (True, ""))

    written = vibers_brief.run_brief(place=PLACE, depth="quick", log=lambda *_: None)

    part1 = Path(written["part1"]).read_text()
    part2 = Path(written["part2"]).read_text()
    selection_doc = Path(written["selection"]).read_text()

    assert "How these properties were chosen (auto-discovery)" in part1
    assert part1.index("How these properties were chosen") < part1.index("Channel key")

    for name in ("Zostel Manali", "The Hosteller Manali", "Cafe 1947", "Dylan's Toasted & Roasted"):
        assert name in part1

    assert "If I owned Zostel Manali" in part2          # owners come from the discovered stays
    assert "Which properties were studied, and why" in selection_doc

    # the choice is saved, so a re-render studies the same properties
    again = vibers_brief.run_brief(place=PLACE, render_only=True, use_llm=False, log=lambda *_: None)

    assert "Zostel Manali" in Path(again["part1"]).read_text()


def test_brief_render_only_without_a_selection_explains_itself(isolated_research_dir):
    with pytest.raises(ValueError, match="Run without --render-only first"):
        vibers_brief.run_brief(place="Nowhere", render_only=True, log=lambda *_: None)


def test_brief_stops_clearly_when_nothing_qualifies(monkeypatch, isolated_research_dir):
    monkeypatch.setattr("app.workflows.discovery.search_web", lambda *a, **k: [])
    monkeypatch.setattr("app.workflows.discovery.fetch_headings", lambda *a, **k: [])

    with pytest.raises(ValueError, match="cleared the evidence bar"):
        vibers_brief.run_brief(place=PLACE, log=lambda *_: None)


def test_manual_properties_file_still_overrides_discovery(world, isolated_research_dir, tmp_path, monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("discovery must not run when a file is given")

    monkeypatch.setattr("app.workflows.discovery.search_web", boom)

    props = tmp_path / "mine.json"
    props.write_text(json.dumps({
        "place": "Manali",
        "properties": [{"name": "Zostel Old Manali", "type": "hostel"},
                       {"name": "A", "type": "hotel"}, {"name": "B", "type": "hotel"}],
    }))

    written = vibers_brief.run_brief(props, part="1", depth="quick", log=lambda *_: None)

    assert "selection" not in written
    assert "auto-discovery" not in Path(written["part1"]).read_text()


def test_study_writes_one_report_for_any_place(web, world, isolated_research_dir, monkeypatch):
    from app.workflows.study import run_study

    monkeypatch.setattr("app.workflows.discovery.evidence_ok", lambda *a, **k: (True, ""))

    written = run_study(PLACE, stays=3, cafes=2, depth="quick", log=lambda *_: None)

    report = Path(written["study"]).read_text()

    assert report.startswith("# Property study - Manali")
    assert "How these properties were chosen" in report
    assert "## Most common customer problems" in report
    assert "Zostel Manali" in report and "Cafe 1947" in report


def test_cli_discover_prints_and_saves(web, isolated_research_dir, capsys):
    from app.main import main

    code = main(["discover", PLACE, "--stays", "3", "--cafes", "2"])

    out = capsys.readouterr().out

    assert code == 0
    assert "Zostel Manali" in out and "Cafe 1947" in out
    assert (isolated_research_dir / "selections" / "manali.json").exists()
    assert (isolated_research_dir / "reports" / "discovery_manali.md").exists()
