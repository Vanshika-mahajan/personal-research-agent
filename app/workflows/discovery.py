"""
Property discovery - let the agent find properties worth studying.

Instead of you hand-picking five properties, give it a PLACE:

    python -m app.main discover "Manali" --stays 3 --cafes 2

and it will

  1. SEARCH for candidates: "best hostels in Manali", Tripadvisor / Booking /
     Hostelworld / Zomato listings, "best cafes in Manali" articles ...
  2. EXTRACT candidate names - from the property pages those platforms
     return and from the headings of "best of" articles (no LLM involved, so
     it works with any model and is easy to test).
  3. PROBE every strong candidate with two more searches and read what the
     result snippets show: rating, number of reviews, "since 2014".
  4. SCORE how much evidence there is to study (see SCORE_WEIGHTS) and
     SELECT the top ones that clear a minimum bar. If fewer clear it, you get
     fewer - the list is never padded with weak picks (use --allow-thin to
     override).

What the score means - and does not mean
----------------------------------------
It measures how much material exists to study (reach, review volume, rating
after shrinkage, history). It does NOT say the place is good. A famous
disaster would score high - which is exactly what you want to study.

What the numbers are
--------------------
Everything comes from search-result text. Google Maps and Instagram are not
readable by this agent, so their review counts are usually not visible.
"not shown" means we did not see it, never that it is zero. Nothing is
estimated or invented.

The chosen list is saved to research/selections/<place>.json so re-running
the brief studies the SAME properties (profiles are cached). Use
--rediscover to search again.
"""

from __future__ import annotations

import difflib
import math
import re
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import unquote, urlparse

from app.config import get_settings
from app.storage import read_json, research_dir, slugify, write_json
from app.tools.source_types import classify_url, domain_of, is_walled
from app.tools.web_search import SearchUnavailable, search_web
from app.tools.webpage_reader import fetch_headings
from app.workflows.profiles import PropertySpec, profile_property

# ------------------------------------------------------------------
# Tunables (documented in the report so the scoring is never a black box)
# ------------------------------------------------------------------

SCORE_WEIGHTS = {
    "reach": 30,    # independent sites that mention it (10+ = full marks)
    "volume": 35,   # reviews visible across platforms (5,000+ = full marks, log scale)
    "rating": 20,   # rating after shrinking towards 4.0 so 5.0 from 3 reviews cannot win
    "history": 15,  # years operating, when a "since 20xx" date was seen (12+ years = full)
}

REACH_FULL = 10
VOLUME_FULL = 5000
HISTORY_FULL_YEARS = 12
RATING_PRIOR = 4.0
RATING_PRIOR_WEIGHT = 30
RATING_UNKNOWN_COUNT_WEIGHT = 10  # a rating with no visible count is treated as 10 reviews
RATING_FLOOR, RATING_CEIL = 3.5, 4.8

KIND_LABEL = {"stay": "stays", "cafe": "cafes"}

# ------------------------------------------------------------------
# Words
# ------------------------------------------------------------------

FILLER = {"the", "a", "an", "and", "of", "in", "at", "by", "for", "on", "to", "with", "near", "n"}

TYPE_WORDS = {
    "hostel", "hostels", "hotel", "hotels", "cafe", "cafes", "café", "cafés",
    "restaurant", "restaurants", "resort", "resorts", "homestay", "homestays",
    "stay", "stays", "guesthouse",
}

GEO = {
    "old", "new", "north", "south", "east", "west", "valley", "road", "beach",
    "market", "town", "village", "city", "mall", "bazaar", "bazar", "hills",
    "hill", "district", "himachal", "pradesh", "india", "kullu", "goa", "kerala",
    "rajasthan", "uttarakhand", "karnataka", "maharashtra", "kashmir", "ladakh",
    "punjab", "hp", "ca",
}

# A heading that starts with one of these is an article section, not a venue.
STOP_START = {
    "best", "top", "how", "why", "what", "where", "when", "which", "things", "tips",
    "conclusion", "faq", "faqs", "frequently", "final", "read", "related", "book",
    "contact", "about", "introduction", "summary", "also", "note", "check",
    "getting", "is", "are", "popular", "famous", "must", "most", "budget",
    "luxury", "cheap", "affordable", "recommended", "other", "more", "see",
    "visit", "explore", "plan", "planning", "share", "leave", "comments",
    "comment", "subscribe", "follow", "join", "eat", "drink", "cafes", "hostels",
    "hotels", "restaurants", "places", "our", "your", "you", "we",
}

# Words that only appear in sentences / section titles, never in venue names.
SENTENCE_WORDS = {
    "is", "are", "you", "your", "we", "our", "can", "will", "how", "why", "what",
    "when", "where", "which", "should", "could", "would", "have", "has", "get",
    "make", "need", "tips", "guide", "things", "places", "ways", "reasons", "faq",
    "conclusion", "summary", "introduction", "booking", "contact",
}

_LISTING_START = re.compile(
    r"^(?:the\s+)?\d+\s+(?:best|top|most|hostels|hotels|cafes|cafés|restaurants|places)\b",
    re.I,
)

LISTICLE_TITLE = re.compile(
    r"\b(best|top|popular|where to stay|recommended|famous|must[- ]?visit|favou?rite|"
    r"\d{1,2}\s+(?:places|hotels|hostels|cafes|cafés|restaurants|stays)|guide to)\b",
    re.I,
)

CAFE_WORDS = re.compile(
    r"\b(cafe|café|coffee|bakery|bistro|roaster|roasters|espresso|brunch|patisserie|"
    r"eatery|brew|tea house|baking)\b",
    re.I,
)

HOSTEL_WORDS = re.compile(r"\b(hostel|zostel|hosteller|backpacker|bunk|dorm)\w*", re.I)
HOMESTAY_WORDS = re.compile(r"\b(homestay|guest\s?house|bnb|b&b)\b", re.I)
RESORT_WORDS = re.compile(r"\b(resort|cottages?|camp)\b", re.I)

_NUMBERED = re.compile(r"^\s*(?:no\.?\s*)?#?\d{1,2}\s*[\.\)\:\-–—]\s*\S", re.I)
_NUMBER_PREFIX = re.compile(r"^\s*(?:no\.?\s*)?#?\d{1,2}\s*[\.\)\:\-–—]\s*", re.I)
_SPLIT_TITLE = re.compile(r"\s[-–—|•·]\s|\s:\s|:\s")
_REVIEW_TAIL = re.compile(r"\s+(?:reviews?|photos?|prices?|menu|price list)$", re.I)


# ------------------------------------------------------------------
# Text helpers
# ------------------------------------------------------------------

def _norm(text: str) -> str:
    text = (text or "").lower().replace("’", "").replace("'", "").replace("&", " and ")

    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def place_tokens(place: str) -> set:
    return {t for t in _norm(place).split() if t not in FILLER}


def distinctive_tokens(name: str, place: str) -> List[str]:
    """The words that identify a venue: its name minus type words, filler and place words."""

    skip = FILLER | TYPE_WORDS | GEO | place_tokens(place)

    return [t for t in _norm(name).split() if t not in skip and len(t) >= 2]


def candidate_key(name: str, place: str) -> str:
    return " ".join(distinctive_tokens(name, place))


def valid_name(name: str, place: str) -> bool:
    """Is this string plausibly the name of ONE venue (not a sentence or section title)?"""

    name = (name or "").strip()

    if not (2 <= len(name) <= 60):
        return False

    words = name.split()

    if len(words) > 8:
        return False

    if any(ch in name for ch in "?!") or name.endswith(":") or ". " in name:
        return False

    if not any(ch.isupper() for ch in name):
        return False

    if _LISTING_START.match(name):
        return False

    normed = _norm(name).split()

    if not normed or normed[0] in STOP_START:
        return False

    if any(token in SENTENCE_WORDS for token in normed):
        return False

    return bool(distinctive_tokens(name, place))


def _is_geo_part(part: str, place: str) -> bool:
    tokens = _norm(part).split()

    if not tokens:
        return True

    skip = FILLER | TYPE_WORDS | GEO | place_tokens(place)

    return all(token in skip for token in tokens)


def _strip_geo_tail(name: str, place: str) -> str:
    """'Cafe 1947, Old Manali, Manali' -> 'Cafe 1947'"""

    parts = [p.strip() for p in name.split(",")]

    while len(parts) > 1 and _is_geo_part(parts[-1], place):
        parts.pop()

    return ", ".join(parts)


def _fix_shouting(name: str) -> str:
    letters = [c for c in name if c.isalpha()]

    if len(letters) >= 4 and all(c.isupper() for c in letters):
        return " ".join(word.capitalize() for word in name.split(" "))

    return name


def _tidy(name: str, place: str) -> str:
    name = re.sub(r"\(.*?\)", "", name)
    name = _strip_geo_tail(name, place)
    name = _REVIEW_TAIL.sub("", name)
    name = name.strip(" ,.-–—\"'“”‘’")

    return _fix_shouting(re.sub(r"\s+", " ", name))


def name_from_title(title: str, place: str) -> str:
    head = _SPLIT_TITLE.split(title or "", maxsplit=1)[0]

    return _tidy(head, place)


def name_from_heading(heading: str, place: str) -> str:
    text = _NUMBER_PREFIX.sub("", heading or "")
    head = _SPLIT_TITLE.split(text, maxsplit=1)[0]

    return _tidy(head, place)


def is_numbered(heading: str) -> bool:
    return bool(_NUMBERED.match(heading or ""))


# ------------------------------------------------------------------
# Sites and property pages
# ------------------------------------------------------------------

_MULTI_PART_SLD = {"co", "com", "org", "net", "gov", "ac", "edu"}


def site_key(url: str) -> str:
    """One label per independent site: all Tripadvisor domains count once."""

    source_type, platform = classify_url(url)

    if source_type != "web" and platform:
        return platform

    host = domain_of(url)
    parts = host.split(".")

    if len(parts) >= 3 and parts[-2] in _MULTI_PART_SLD:
        return ".".join(parts[-3:])

    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def property_page(url: str, title: str, place: str) -> Optional[Tuple[Optional[str], str]]:
    """
    If `url` is the page of ONE venue on a known platform return
    (kind or None, name). Otherwise None.
    """

    lowered = (url or "").lower()
    parsed = urlparse(lowered)
    segments = [s for s in parsed.path.split("/") if s]

    kind: Optional[str] = None
    name = ""
    matched = False

    if "tripadvisor." in lowered:
        if "hotel_review" in lowered or "vacationrentalreview" in lowered:
            kind, matched = "stay", True
        elif "restaurant_review" in lowered:
            kind, matched = "cafe", True

    elif "booking.com" in lowered and "/hotel/" in lowered:
        kind, matched = "stay", True

    elif "hostelworld.com" in lowered and ("/hostels/p/" in lowered or "hosteldetails" in lowered):
        kind, matched = "stay", True

    elif "agoda.com" in lowered and "/hotel/" in lowered:
        kind, matched = "stay", True

    elif "zomato.com" in lowered and len(segments) >= 2:
        if segments[-1] not in {"restaurants", "cafes", "order", "reviews", "menu", "photos", "info"} and not segments[-1].startswith(("best-", "top-")):
            kind, matched = "cafe", True

    elif "google.com/maps/place/" in lowered:
        matched = True
        original = urlparse(url).path.split("/place/", 1)[-1].split("/", 1)[0]
        name = unquote(original).replace("+", " ")

    if not matched:
        return None

    if not name:
        name = name_from_title(title, place)
    else:
        name = _tidy(name, place)

    return kind, name


# ------------------------------------------------------------------
# Reading ratings, review counts and dates out of snippets
# ------------------------------------------------------------------

def parse_count(raw: str) -> Optional[int]:
    """'1,234' -> 1234 ; '1.2K' -> 1200 ; '12k' -> 12000"""

    raw = (raw or "").strip().lower().replace(" ", "")

    if not raw:
        return None

    multiplier = 1

    if raw.endswith("k"):
        multiplier, raw = 1000, raw[:-1]

    raw = raw.replace(",", "")

    try:
        value = float(raw) * multiplier
    except ValueError:
        return None

    value = int(round(value))

    return value if 0 < value <= 500_000 else None


_REVIEW_COUNT_PATTERNS = [
    re.compile(
        r"(\d[\d,\.]*\s?[kK]?)\+?\s*(?:google\s+|traveller\s+|traveler\s+|guest\s+|verified\s+)?"
        r"(?:reviews?|ratings?)\b"
    ),
    re.compile(r"\b(?:reviews?|ratings?)\s*[:\(]\s*(\d[\d,\.]*\s?[kK]?)"),
    re.compile(r"\bbased on\s+(\d[\d,\.]*\s?[kK]?)"),
]

_GOOGLE_STYLE = re.compile(r"\b(\d\.\d)\s*[★⭐]\s*[\(\[]?\s*(\d[\d,\.]*\s?[kK]?)\s*[\)\]]?")
_PAREN_STYLE = re.compile(r"\b(\d\.\d)\s*\(\s*(\d[\d,\.]*\s?[kK]?)\s*\)")

_NOT_A_RATING = r"(?!\s*(?:hotels|hostels|restaurants|cafes|places|b&bs|lodging|things|\d))"

_RATED_OF_5 = re.compile(r"\brated\s+(\d(?:\.\d)?)\s+(?:out\s+)?of\s+5\b", re.I)
_X_OF_Y = re.compile(r"(?<![#\d\.])(\d(?:\.\d{1,2})?)\s*(?:/|out of|of)\s*(5|10)\b" + _NOT_A_RATING, re.I)
_LABELLED = re.compile(
    r"\b(?:rating|rated|score|scored|review score)\s*[:\-]?\s*(\d{1,2}(?:\.\d{1,2})?)\b(?!\s*(?:out of|/|of|-?\s*star))",
    re.I,
)


def parse_signals(text: str) -> Tuple[Optional[float], str, Optional[int]]:
    """
    Return (rating out of 5 or None, raw rating text like '8.8/10', review count or None)
    from a title + snippet.
    """

    text = text or ""

    rating: Optional[float] = None
    raw = ""
    count: Optional[int] = None

    match = _GOOGLE_STYLE.search(text) or _PAREN_STYLE.search(text)

    if match:
        value = float(match.group(1))

        if 0 < value <= 5:
            rating, raw = value, f"{value:g}/5"
            count = parse_count(match.group(2))

    if rating is None:
        match = _RATED_OF_5.search(text)

        if match:
            value = float(match.group(1))
            rating, raw = value, f"{value:g}/5"

    if rating is None:
        match = _X_OF_Y.search(text)

        if match:
            value, scale = float(match.group(1)), int(match.group(2))

            if 0 < value <= scale:
                rating, raw = value / scale * 5, f"{value:g}/{scale}"

    if rating is None:
        match = _LABELLED.search(text)

        if match:
            value = float(match.group(1))

            if 0 < value <= 10:
                scale = 5 if value <= 5 else 10
                rating, raw = value / scale * 5, f"{value:g}/{scale}"

    if count is None:
        for pattern in _REVIEW_COUNT_PATTERNS:
            match = pattern.search(text)

            if match:
                count = parse_count(match.group(1))

                if count:
                    break

    return rating, raw, count


_YEAR_SINCE = re.compile(
    r"\b(?:since|established(?:\s+in)?|est\.?|opened(?:\s+in)?|founded(?:\s+in)?|"
    r"operating\s+since|serving\s+since|running\s+since|started\s+in)\s*[:\-]?\s*"
    r"(19[5-9]\d|20[0-2]\d)\b",
    re.I,
)

_YEARS_OPERATING = re.compile(
    r"\b(?:serving|operating|running|open|in business|established)\s+(?:for\s+)?"
    r"(?:over\s+|more than\s+)?(\d{1,2})\+?\s+years\b",
    re.I,
)


def parse_start_year(text: str, now_year: int) -> Optional[int]:
    """Earliest 'since 2014' / 'serving for 10 years' style start year in a text."""

    years = []

    for match in _YEAR_SINCE.finditer(text or ""):
        year = int(match.group(1))

        if 1950 <= year <= now_year:
            years.append(year)

    for match in _YEARS_OPERATING.finditer(text or ""):
        age = int(match.group(1))

        if 1 <= age <= 70:
            years.append(now_year - age)

    return min(years) if years else None


# ------------------------------------------------------------------
# Candidates
# ------------------------------------------------------------------

@dataclass
class Mention:
    site: str
    url: str
    via: str                     # property_page | listicle | probe
    title: str = ""
    numbered: bool = False
    cafe_hint: bool = False


@dataclass
class Signal:
    platform: str
    rating: Optional[float] = None     # out of 5
    rating_raw: str = ""
    reviews: Optional[int] = None
    url: str = ""


@dataclass
class Candidate:
    key: str
    kind: str
    names: Counter = field(default_factory=Counter)
    mentions: List[Mention] = field(default_factory=list)
    signals: List[Signal] = field(default_factory=list)
    years: List[int] = field(default_factory=list)
    probed: bool = False

    # filled by score_candidate
    score: float = 0.0
    components: Dict[str, float] = field(default_factory=dict)

    @property
    def name(self) -> str:
        # most frequent spelling; ties -> the longer (usually fuller) name
        return sorted(self.names.items(), key=lambda kv: (-kv[1], -len(kv[0]), kv[0]))[0][0]

    @property
    def sites(self) -> List[str]:
        return sorted({m.site for m in self.mentions if m.site})

    def has_cafe_hint(self) -> bool:
        return any(m.cafe_hint for m in self.mentions) or bool(CAFE_WORDS.search(self.name))

    def venue_type(self) -> str:
        if self.kind == "cafe":
            return "cafe"

        name = self.name

        if HOSTEL_WORDS.search(name) or "Hostelworld" in self.sites:
            return "hostel"

        if HOMESTAY_WORDS.search(name):
            return "homestay"

        if RESORT_WORDS.search(name):
            return "resort"

        return "hotel"

    def prelim(self) -> float:
        property_page_sites = {m.site for m in self.mentions if m.via == "property_page"}
        numbered = sum(1 for m in self.mentions if m.numbered)

        return 2 * len(self.sites) + 2 * len(property_page_sites) + 0.25 * numbered

    def platform_signals(self) -> Dict[str, Dict[str, Any]]:
        merged: Dict[str, Dict[str, Any]] = {}

        for signal in self.signals:
            entry = merged.setdefault(
                signal.platform,
                {"reviews": None, "rating": None, "rating_raw": "", "url": signal.url},
            )

            if signal.reviews and (entry["reviews"] is None or signal.reviews > entry["reviews"]):
                entry["reviews"] = signal.reviews
                entry["url"] = signal.url

            if signal.rating is not None and entry["rating"] is None:
                entry["rating"] = signal.rating
                entry["rating_raw"] = signal.rating_raw

        return merged


class Registry:
    """Candidates of one kind, merged by normalised name."""

    def __init__(self, place: str, kind: str):
        self.place = place
        self.kind = kind
        self.by_key: Dict[str, Candidate] = {}

    def _find(self, key: str) -> Optional[Candidate]:
        if key in self.by_key:
            return self.by_key[key]

        for existing_key, candidate in self.by_key.items():
            if difflib.SequenceMatcher(None, key, existing_key).ratio() >= 0.9:
                return candidate

        return None

    def add(self, name: str, mention: Mention) -> Optional[Candidate]:
        if not valid_name(name, self.place):
            return None

        key = candidate_key(name, self.place)

        candidate = self._find(key)

        if candidate is None:
            candidate = Candidate(key=key, kind=self.kind)
            self.by_key[key] = candidate

        # The same page often comes back for several queries; it is one
        # mention, not several (otherwise popular pages skew names and ranking).
        if any(m.url == mention.url and m.via == mention.via for m in candidate.mentions):
            return candidate

        candidate.names[name] += 1
        candidate.mentions.append(mention)

        return candidate

    def all(self) -> List[Candidate]:
        return list(self.by_key.values())


def text_mentions(text: str, candidate: Candidate, place: str) -> bool:
    """Does `text` talk about this venue in this place (not another branch elsewhere)?"""

    tokens = distinctive_tokens(candidate.name, place)

    if not tokens:
        return False

    words = set(_norm(text).split())

    needed = max(1, math.ceil(0.8 * len(tokens)))

    if sum(1 for token in tokens if token in words) < needed:
        return False

    required_place = {t for t in place_tokens(place) if t not in GEO} or place_tokens(place)

    return not required_place or bool(required_place & words)


# ------------------------------------------------------------------
# Scoring
# ------------------------------------------------------------------

def score_candidate(candidate: Candidate, now_year: int) -> Dict[str, Any]:
    """Fill candidate.score / .components and return the numbers behind them."""

    platform_data = candidate.platform_signals()

    total_reviews = sum(entry["reviews"] or 0 for entry in platform_data.values())

    rated = [entry for entry in platform_data.values() if entry["rating"] is not None]

    avg_rating: Optional[float] = None
    adjusted: Optional[float] = None

    if rated:
        weights = [entry["reviews"] or RATING_UNKNOWN_COUNT_WEIGHT for entry in rated]
        avg_rating = sum(e["rating"] * w for e, w in zip(rated, weights)) / sum(weights)
        n = sum(weights)
        adjusted = (avg_rating * n + RATING_PRIOR * RATING_PRIOR_WEIGHT) / (n + RATING_PRIOR_WEIGHT)

    earliest = min(candidate.years) if candidate.years else None
    age = (now_year - earliest) if earliest else None

    reach = min(len(candidate.sites), REACH_FULL) / REACH_FULL * SCORE_WEIGHTS["reach"]

    volume = (
        min(1.0, math.log10(1 + total_reviews) / math.log10(1 + VOLUME_FULL)) * SCORE_WEIGHTS["volume"]
        if total_reviews
        else 0.0
    )

    rating = (
        max(0.0, min(1.0, (adjusted - RATING_FLOOR) / (RATING_CEIL - RATING_FLOOR))) * SCORE_WEIGHTS["rating"]
        if adjusted is not None
        else 0.0
    )

    history = (
        min(max(age, 0), HISTORY_FULL_YEARS) / HISTORY_FULL_YEARS * SCORE_WEIGHTS["history"]
        if age is not None
        else 0.0
    )

    candidate.components = {
        "reach": round(reach, 1),
        "volume": round(volume, 1),
        "rating": round(rating, 1),
        "history": round(history, 1),
    }
    candidate.score = round(sum(candidate.components.values()), 1)

    return {
        "total_reviews": total_reviews,
        "avg_rating": round(avg_rating, 2) if avg_rating is not None else None,
        "earliest_year": earliest,
        "age_years": age,
        "platforms": platform_data,
    }


def eligibility(
    candidate: Candidate,
    stats: Dict[str, Any],
    *,
    min_sites: int,
    min_reviews: int,
    strong_sites: int = 5,
) -> Tuple[bool, str]:
    """Does this candidate have enough visible material to be worth studying?"""

    sites = len(candidate.sites)

    if candidate.kind == "cafe" and not candidate.has_cafe_hint():
        return False, "does not look like a cafe (no cafe/coffee/bakery wording seen)"

    if not candidate.probed:
        return False, "not checked (ranked too low on first pass)"

    # A real venue has a listing on a review/booking platform or a visible
    # rating / review count. This keeps landmarks and areas ("Solang Valley",
    # "Mall Road") that merely appear in many articles out of the list.
    if not (any(m.via == "property_page" for m in candidate.mentions) or candidate.signals):
        return False, "no platform listing or visible review count found (may not be a reviewable venue)"

    if sites < min_sites:
        return False, f"only {sites} independent source(s) mention it (need {min_sites})"

    reviews = stats["total_reviews"]

    if reviews >= min_reviews or sites >= strong_sites:
        return True, ""

    if reviews:
        return False, f"only {reviews} reviews visible (need {min_reviews}) and fewer than {strong_sites} sources"

    return False, f"no review count visible and fewer than {strong_sites} sources"


# ------------------------------------------------------------------
# Searching
# ------------------------------------------------------------------

def discovery_queries(place: str, kind: str) -> List[str]:
    if kind == "stay":
        return [
            f"best hostels in {place}",
            f"best hotels in {place}",
            f"top rated budget hotels and hostels {place} reviews",
            f"site:tripadvisor.com {place} hotel reviews",
            f"site:tripadvisor.in {place} hostel reviews",
            f"site:booking.com {place} hotel",
            f"site:hostelworld.com {place}",
            f"oldest famous hotels in {place} established since",
        ]

    return [
        f"best cafes in {place}",
        f"top rated cafes in {place} reviews",
        f"site:tripadvisor.com {place} cafe reviews",
        f"site:tripadvisor.in {place} cafes",
        f"site:zomato.com {place} cafe",
        f"famous cafes in {place} must visit",
        f"best coffee shops in {place}",
        f"oldest cafes in {place} established since",
    ]


def probe_queries(name: str, place: str, kind: str) -> List[str]:
    # First query is an exact phrase (precise); the second is not, so a
    # different spelling of the same venue name still finds its listings.
    if kind == "stay":
        return [
            f'"{name}" {place} reviews rating',
            f"{name} {place} tripadvisor booking.com hostelworld",
        ]

    return [
        f'"{name}" {place} reviews rating',
        f"{name} {place} tripadvisor zomato google reviews",
    ]


# Stop after this many searches in a row fail even after their retries: the engine is
# blocking us (or the internet is down) and carrying on only wastes the user's time.
MAX_CONSECUTIVE_SEARCH_FAILURES = 8

# A run where at least this share of searches failed is marked as unreliable.
DEGRADED_FAILURE_SHARE = 0.25


class _Search:
    """search_web with a polite delay, failure counting and a log."""

    def __init__(self, log):
        self.log = log
        self.queries = 0
        self.results = 0
        self.failed = 0
        self.in_a_row = 0
        self.last_error = ""
        self._first = True

    @property
    def degraded(self) -> bool:
        return (
            self.queries >= 8
            and self.failed / self.queries >= DEGRADED_FAILURE_SHARE
        )

    def __call__(self, query: str, max_results: int = 8):
        settings = get_settings()

        if not self._first and settings.search_delay:
            time.sleep(settings.search_delay)

        self._first = False
        self.queries += 1

        try:
            results = search_web(query, max_results=max_results)
        except Exception as exc:  # network / rate limit: keep going, but not forever
            self.failed += 1
            self.in_a_row += 1
            self.last_error = f"{exc.__class__.__name__}: {str(exc).strip()[:120]}".rstrip(": ")
            self.log(f"   ! search failed ({exc.__class__.__name__}): {query}")
            results = None
        else:
            self.in_a_row = 0

        if results is None:
            if self.in_a_row >= MAX_CONSECUTIVE_SEARCH_FAILURES:
                raise SearchUnavailable(
                    f"Web search failed {self.in_a_row} times in a row ({self.last_error}). "
                    "DuckDuckGo is probably slowing you down or your internet is off. "
                    "Wait a few minutes and try again; nothing was saved. "
                    "Raising SEARCH_TIMEOUT or SEARCH_DELAY in .env can also help."
                )

            return []

        self.results += len(results)

        return results


def _listicle_candidates(
    pages: List[Tuple[str, str]],
    registry: Registry,
    place: str,
) -> int:
    """Read headings of 'best of' articles in parallel and add their names."""

    if not pages:
        return 0

    with ThreadPoolExecutor(max_workers=4) as pool:
        all_headings = list(pool.map(lambda page: fetch_headings(page[0]), pages))

    added = 0

    for (url, title), headings in zip(pages, all_headings):
        site = site_key(url)
        cafe_hint = bool(CAFE_WORDS.search(title))

        for heading in headings:
            name = name_from_heading(heading, place)

            mention = Mention(
                site=site,
                url=url,
                via="listicle",
                title=title,
                numbered=is_numbered(heading),
                cafe_hint=cafe_hint or bool(CAFE_WORDS.search(heading)),
            )

            if registry.add(name, mention):
                added += 1

    return added


def _collect(
    place: str,
    kind: str,
    search: _Search,
    registry: Registry,
    *,
    fetch_lists: bool,
    max_listicles: int,
    now_year: int,
    log,
) -> None:
    pages: List[Tuple[str, str]] = []
    seen_pages = set()

    for query in discovery_queries(place, kind):
        for result in search(query):
            found = property_page(result.url, result.title, place)

            if found:
                page_kind, name = found

                if page_kind is not None and page_kind != kind:
                    continue

                text = f"{result.title}. {result.snippet}"

                mention = Mention(
                    site=site_key(result.url),
                    url=result.url,
                    via="property_page",
                    title=result.title,
                    cafe_hint=bool(CAFE_WORDS.search(text)),
                )

                candidate = registry.add(name, mention)

                if candidate:
                    _record_signals(candidate, result, text, now_year)

                continue

            source_type = result.source_type or classify_url(result.url)[0]

            if (
                LISTICLE_TITLE.search(result.title or "")
                and source_type in {"web", "review", "booking"}
                and not is_walled(source_type)
                and result.url not in seen_pages
            ):
                seen_pages.add(result.url)
                pages.append((result.url, result.title))

    if fetch_lists:
        added = _listicle_candidates(pages[:max_listicles], registry, place)
        log(f"   read {min(len(pages), max_listicles)} 'best of' pages -> {added} name mentions")
    elif pages:
        log("   (page fetching is off: 'best of' articles skipped, only platform pages used)")


def _record_signals(candidate: Candidate, result, text: str, now_year: Optional[int] = None) -> None:
    source_type = result.source_type or classify_url(result.url)[0]

    if source_type in {"review", "booking", "maps"}:
        rating, raw, reviews = parse_signals(text)

        if rating is not None or reviews:
            candidate.signals.append(
                Signal(
                    platform=site_key(result.url),
                    rating=rating,
                    rating_raw=raw,
                    reviews=reviews,
                    url=result.url,
                )
            )

    year = parse_start_year(text, now_year or datetime.now().year)

    if year:
        candidate.years.append(year)


def _probe(
    candidate: Candidate,
    place: str,
    search: _Search,
    now_year: int,
) -> None:
    """Two searches about ONE candidate: how many independent sources, what numbers?"""

    candidate.probed = True

    for query in probe_queries(candidate.name, place, candidate.kind):
        for result in search(query):
            text = f"{result.title}. {result.snippet}"

            if not text_mentions(f"{text} {result.url}", candidate, place):
                continue

            found = property_page(result.url, result.title, place)
            is_listing = bool(found) and found[0] in (None, candidate.kind)

            candidate.mentions.append(
                Mention(
                    site=site_key(result.url),
                    url=result.url,
                    via="property_page" if is_listing else "probe",
                    title=result.title,
                    cafe_hint=bool(CAFE_WORDS.search(text)),
                )
            )

            _record_signals(candidate, result, text, now_year)


# ------------------------------------------------------------------
# Selection
# ------------------------------------------------------------------

def _describe(candidate: Candidate, stats: Dict[str, Any], *, thin: bool = False) -> Dict[str, Any]:
    urls = []

    for mention in candidate.mentions:
        if mention.url not in urls:
            urls.append(mention.url)

    platforms = {
        platform: {
            "reviews": entry["reviews"],
            "rating": entry["rating_raw"] or None,
            "url": entry["url"],
        }
        for platform, entry in stats["platforms"].items()
    }

    return {
        "name": candidate.name,
        "key": candidate.key,
        "kind": candidate.kind,
        "type": candidate.venue_type(),
        "score": candidate.score,
        "components": candidate.components,
        "sites": candidate.sites,
        "site_count": len(candidate.sites),
        "total_reviews": stats["total_reviews"],
        "avg_rating_5": stats["avg_rating"],
        "platforms": platforms,
        "earliest_year": stats["earliest_year"],
        "age_years": stats["age_years"],
        "thin": thin,
        "evidence_urls": urls[:8],
    }


def _select_kind(
    registry: Registry,
    *,
    wanted: int,
    search: _Search,
    place: str,
    probe: bool,
    probe_limit: int,
    min_sites: int,
    min_reviews: int,
    allow_thin: bool,
    now_year: int,
    log,
) -> Dict[str, Any]:
    candidates = sorted(registry.all(), key=lambda c: (-c.prelim(), c.name))

    log(f"   {len(candidates)} candidate names found")

    if probe:
        for index, candidate in enumerate(candidates[:probe_limit], start=1):
            log(f"   checking {index}/{min(len(candidates), probe_limit)}: {candidate.name}")
            _probe(candidate, place, search, now_year)
    else:
        for candidate in candidates:
            candidate.probed = True

    scored = []

    for candidate in candidates:
        stats = score_candidate(candidate, now_year)
        ok, reason = eligibility(candidate, stats, min_sites=min_sites, min_reviews=min_reviews)
        scored.append((candidate, stats, ok, reason))

    eligible = sorted(
        [row for row in scored if row[2]],
        key=lambda row: (-row[0].score, -row[1]["total_reviews"], row[0].name),
    )

    chosen = eligible[:wanted]
    reserves = eligible[wanted: wanted + 4]

    selected = [_describe(c, s) for c, s, _, _ in chosen]

    shortfall = wanted - len(selected)

    if shortfall > 0 and allow_thin:
        thin_pool = sorted(
            [row for row in scored if not row[2] and row[0].probed and row[3].startswith(("only", "no review count"))],
            key=lambda row: (-row[0].score, row[0].name),
        )

        for candidate, stats, _, _ in thin_pool[:shortfall]:
            selected.append(_describe(candidate, stats, thin=True))

    chosen_names = {item["name"] for item in selected}
    reserve_names = {c.name for c, _, _, _ in reserves}

    rejected = []

    for candidate, stats, ok, reason in sorted(scored, key=lambda row: -row[0].score):
        if candidate.name in chosen_names:
            continue

        if candidate.name in reserve_names:
            reason = "eligible, ranked below the top picks (kept as a reserve)"
        elif ok:
            reason = "eligible but ranked below the reserves"

        rejected.append(
            {
                "name": candidate.name,
                "score": candidate.score,
                "site_count": len(candidate.sites),
                "total_reviews": stats["total_reviews"],
                "reason": reason,
            }
        )

    return {
        "requested": wanted,
        "selected": selected,
        "reserves": [_describe(c, s) for c, s, _, _ in reserves],
        "rejected": rejected[:15],
        "qualified": len(chosen),
        "shortfall": max(0, wanted - len(selected)),
    }


def discover(
    place: str,
    *,
    stays: int = 3,
    cafes: int = 2,
    min_sites: int = 3,
    min_reviews: int = 50,
    allow_thin: bool = False,
    probe: bool = True,
    probe_limit: Optional[int] = None,
    max_listicles: int = 8,
    now_year: Optional[int] = None,
    log=print,
) -> Dict[str, Any]:
    """
    Find the properties in `place` with enough material to study.

    Returns the selection dict (also written by save_selection).
    """

    now_year = now_year or datetime.now().year
    settings = get_settings()
    search = _Search(log)

    selection: Dict[str, Any] = {
        "place": place,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "params": {
            "stays": stays,
            "cafes": cafes,
            "min_sites": min_sites,
            "min_reviews": min_reviews,
            "allow_thin": allow_thin,
            "probe": probe,
        },
        "notes": [],
    }

    for kind, wanted in (("stay", stays), ("cafe", cafes)):
        label = KIND_LABEL[kind]

        if wanted <= 0:
            selection[label] = {"requested": 0, "selected": [], "reserves": [], "rejected": [], "qualified": 0, "shortfall": 0}
            continue

        log(f"\nDiscovering {label} in {place} ...")

        registry = Registry(place, kind)

        _collect(
            place,
            kind,
            search,
            registry,
            fetch_lists=settings.fetch_pages,
            max_listicles=max_listicles,
            now_year=now_year,
            log=log,
        )

        selection[label] = _select_kind(
            registry,
            wanted=wanted,
            search=search,
            place=place,
            probe=probe,
            probe_limit=probe_limit or max(wanted * 3, 8),
            min_sites=min_sites,
            min_reviews=min_reviews,
            allow_thin=allow_thin,
            now_year=now_year,
            log=log,
        )

        block = selection[label]

        if block["qualified"] < wanted:
            selection["notes"].append(
                f"Only {block['qualified']} of the "
                f"{wanted} requested {label} had enough visible material "
                f"(at least {min_sites} independent sources and {min_reviews}+ reviews, or 5+ sources). "
                "The list was not padded. Lower --min-reviews / --min-sources, use --allow-thin, "
                "or add notes yourself with the `note` command."
            )

    selection["search_stats"] = {
        "queries": search.queries,
        "results": search.results,
        "failed_queries": search.failed,
        "degraded": search.degraded,
    }

    if search.queries and not search.results:
        selection["notes"].append(
            "Web search returned nothing at all. Check your internet connection and run "
            "`python -m app.main check`."
        )
    elif search.degraded:
        selection["notes"].append(
            f"WARNING: {search.failed} of {search.queries} searches failed even after retrying, so "
            "this list is unreliable (strong venues may be missing or look weaker than they are). "
            "Wait a few minutes and run the discovery again with 'Search for properties again' "
            "(--rediscover)."
        )
        log(
            f"   WARNING: {search.failed} of {search.queries} searches failed. "
            "Treat this list as unreliable and run discovery again in a few minutes."
        )
    elif search.failed:
        selection["notes"].append(
            f"{search.failed} of {search.queries} searches failed (usually rate limiting); "
            "results may be incomplete. Re-run with --rediscover after a few minutes."
        )

    if not settings.fetch_pages:
        selection["notes"].append(
            "Page fetching was off, so 'best of' articles were not read; candidates come from "
            "platform pages (Tripadvisor, Booking, Hostelworld, Zomato) only."
        )

    return selection


# ------------------------------------------------------------------
# Saving / loading
# ------------------------------------------------------------------

def selection_path(place: str) -> Path:
    folder = research_dir() / "selections"
    folder.mkdir(parents=True, exist_ok=True)

    return folder / f"{slugify(place)}.json"


def save_selection(selection: Dict[str, Any]) -> Path:
    return write_json(selection_path(selection["place"]), selection)


def load_selection(place: str) -> Optional[Dict[str, Any]]:
    path = selection_path(place)

    if not path.exists():
        return None

    try:
        return read_json(path)
    except Exception:
        return None


def _unreliable_and_untouched(selection: Dict[str, Any]) -> bool:
    """A saved list from a run where many searches failed, which nobody has edited by hand."""

    if not (selection.get("search_stats") or {}).get("degraded"):
        return False

    return not any(str(note).startswith("Edited by hand") for note in selection.get("notes", []))


def get_selection(
    place: str,
    *,
    stays: int = 3,
    cafes: int = 2,
    rediscover: bool = False,
    log=print,
    **kwargs,
) -> Dict[str, Any]:
    """Saved selection when there is one for these settings, otherwise discover."""

    cached = load_selection(place)

    if cached and not rediscover and _unreliable_and_untouched(cached):
        log(f"The saved selection for {place} came from a run where many searches failed, "
            "so it is being redone.")
        cached = None

    if (
        cached
        and not rediscover
        and cached.get("params", {}).get("stays") == stays
        and cached.get("params", {}).get("cafes") == cafes
    ):
        log(f"Using the saved selection for {place} from {cached.get('created_at', '?')} "
            "(--rediscover to search again).")
        return cached

    selection = discover(place, stays=stays, cafes=cafes, log=log, **kwargs)
    save_selection(selection)

    return selection


# ------------------------------------------------------------------
# From selection to specs, with evidence-sufficiency backfill
# ------------------------------------------------------------------

def _spec_for(item: Dict[str, Any], place: str) -> PropertySpec:
    return PropertySpec(name=item["name"], place=place, type=item.get("type", "hotel"))


def evidence_ok(profile: Dict[str, Any], min_items: int = 8, min_sites: int = 3) -> Tuple[bool, str]:
    """After profiling: did the research actually collect enough to study?"""

    if (profile.get("manual_note_count") or 0) >= 3:
        return True, ""

    items = profile.get("evidence", [])

    sites = {site_key(i["source_url"]) for i in items if i.get("source_url")}

    if len(items) >= min_items and len(sites) >= min_sites:
        return True, ""

    return False, f"only {len(items)} evidence passages from {len(sites)} source(s)"


def current_names(block: Dict[str, Any]) -> List[str]:
    """Names being studied: the explicit final list (even if empty), else the original picks."""

    if "final" in block:
        return list(block["final"])

    return [item["name"] for item in block.get("selected", [])]


def edit_selection(selection: Dict[str, Any], action: str, name: str) -> Dict[str, Any]:
    """
    Change the list by hand, e.g. from the interface.

        remove  stop studying `name` (it stays available as a reserve)
        add     study `name` instead - it must be one of the picks or reserves

    The change is recorded in the report's notes. Research already saved for
    a property is kept; newly added ones are researched on the next run.
    """

    if action not in ("remove", "add"):
        raise ValueError(f"Unknown action: {action}")

    for label in ("stays", "cafes"):
        block = selection.get(label) or {}
        lookup = {i["name"]: i for i in block.get("selected", []) + block.get("reserves", [])}
        names = current_names(block)

        if action == "remove" and name in names:
            names.remove(name)
            block["final"] = names
            selection.setdefault("notes", []).append(f"Edited by hand: stopped studying {name}.")
            return selection

        if action == "add" and name in lookup and name not in names:
            names.append(name)
            block["final"] = names
            selection.setdefault("notes", []).append(f"Edited by hand: added {name}.")
            return selection

    raise ValueError(f"'{name}' cannot be {action}ed: not found in this selection.")


def write_discovery_report(selection: Dict[str, Any]) -> Path:
    """research/reports/discovery_<place>.md - what was chosen, rejected and why."""

    path = research_dir() / "reports" / f"discovery_{slugify(selection['place'])}.md"
    path.write_text(
        "# Property discovery\n\n" + render_selection_markdown(selection),
        encoding="utf-8",
    )

    return path


def selected_specs(selection: Dict[str, Any]) -> List[PropertySpec]:
    """The properties to study: the final (post-profiling) list if present, else the picks."""

    place = selection["place"]
    specs = []

    for label in ("stays", "cafes"):
        block = selection.get(label) or {}
        lookup = {i["name"]: i for i in block.get("selected", []) + block.get("reserves", [])}
        names = current_names(block)

        specs += [_spec_for(lookup[name], place) for name in names if name in lookup]

    return specs


def profile_selection(
    selection: Dict[str, Any],
    *,
    depth: str = "standard",
    refresh: bool = False,
    render_only: bool = False,
    min_items: int = 8,
    min_sites: int = 3,
    log=print,
) -> List[PropertySpec]:
    """
    Research every selected property. A property whose research turns out
    thin (few passages / sources) is swapped for the next reserve, so the
    final list is what could really be studied. The final list is saved.
    """

    place = selection["place"]
    dropped = {c["dropped"] for c in selection.get("profiling_changes", [])}
    changes = list(selection.get("profiling_changes", []))

    specs: List[PropertySpec] = []

    for label in ("stays", "cafes"):
        block = selection.get(label) or {}
        lookup = {i["name"]: i for i in block.get("selected", []) + block.get("reserves", [])}

        names = current_names(block)
        queue = [lookup[n] for n in names if n in lookup]

        reserve_q = [
            item for item in block.get("reserves", [])
            if item["name"] not in names and item["name"] not in dropped
        ]

        final: List[str] = []

        while queue:
            item = queue.pop(0)
            spec = _spec_for(item, place)

            if render_only:
                final.append(item["name"])
                specs.append(spec)
                continue

            profile = profile_property(spec, depth=depth, refresh=refresh, log=log)

            ok, why = evidence_ok(profile, min_items, min_sites)

            if ok or not reserve_q:
                if not ok:
                    note = f"{item['name']}: kept, but {why} - treat its findings as thin."
                    log(f"   ! {note}")
                    selection.setdefault("notes", []).append(note)

                final.append(item["name"])
                specs.append(spec)
                continue

            replacement = reserve_q.pop(0)
            log(f"   ! {item['name']}: {why}. Swapping in {replacement['name']}.")
            changes.append({"dropped": item["name"], "reason": why, "replaced_by": replacement["name"]})
            dropped.add(item["name"])
            queue.insert(0, replacement)

        block["final"] = final

    selection["profiling_changes"] = changes

    if not render_only:
        save_selection(selection)

    return specs


# ------------------------------------------------------------------
# Report
# ------------------------------------------------------------------

def _platform_text(item: Dict[str, Any]) -> str:
    parts = []

    for platform, data in item.get("platforms", {}).items():
        bits = []

        if data.get("rating"):
            bits.append(data["rating"])

        if data.get("reviews"):
            bits.append(f"{data['reviews']:,} reviews")

        if bits:
            parts.append(f"{platform} {', '.join(bits)}")

    return " · ".join(parts) or "not shown"


def _table(items: List[Dict[str, Any]]) -> List[str]:
    lines = [
        "| # | Property | Type | Score | Independent sources | Reviews / ratings seen | Oldest date seen |",
        "|---|---|---|---|---|---|---|",
    ]

    for index, item in enumerate(items, start=1):
        year = item.get("earliest_year")
        age = item.get("age_years")
        history = f"since {year} ({age} yrs)" if year else "not shown"
        flag = " ⚠️ thin" if item.get("thin") else ""

        lines.append(
            f"| {index} | {item['name']}{flag} | {item['type']} | {item['score']:g}/100 | "
            f"{item['site_count']} | {_platform_text(item)} | {history} |"
        )

    return lines


def render_selection_markdown(selection: Dict[str, Any], heading_level: int = 2) -> str:
    h = "#" * heading_level
    sub = "#" * (heading_level + 1)

    params = selection.get("params", {})
    stats = selection.get("search_stats", {})

    weights = SCORE_WEIGHTS

    lines = [
        f"{h} How these properties were chosen (auto-discovery)",
        "",
        f"**RESEARCHED** - the agent searched for properties in **{selection['place']}** "
        f"({stats.get('queries', 0)} searches, {stats.get('results', 0)} results, "
        f"{selection.get('created_at', '')}) rather than using a hand-written list.",
        "",
        "Each candidate was scored for **how much evidence exists to study**, not for how good it is "
        f"(out of 100): independent sources that mention it ({weights['reach']}), reviews visible "
        f"across platforms ({weights['volume']}), rating after shrinking towards {RATING_PRIOR:g} so a "
        f"perfect score from a handful of reviews cannot win ({weights['rating']}), and years operating "
        f"when a 'since 20xx' date was seen ({weights['history']}). A candidate had to appear on at "
        f"least {params.get('min_sites', 3)} independent sources and show "
        f"{params.get('min_reviews', 50)}+ reviews (or appear on 5+ sources) to qualify.",
        "",
        "> **Read the numbers carefully.** They come only from search-result text. Google Maps and "
        "Instagram cannot be read by this agent, so their review counts are usually missing. "
        "Counts are copied as the snippet shows them (a platform may show a floor such as 3,000+). "
        "*not shown* means we did not see it - not that it is zero.",
        "",
    ]

    for label, title in (("stays", "Hotels and hostels"), ("cafes", "Cafes")):
        block = selection.get(label) or {}

        if not block.get("requested"):
            continue

        lines += [f"{sub} {title}", ""]

        if block["selected"]:
            lines += _table(block["selected"])
        else:
            lines.append("*Nothing cleared the evidence bar.*")

        final = block.get("final")

        if final is not None and final != [i["name"] for i in block["selected"]]:
            lines += ["", f"The list being studied is now: {', '.join(final) or '(none)'}."]

        if block.get("reserves"):
            lines += ["", "Reserves (used if a pick turns out thin): "
                      + ", ".join(f"{i['name']} ({i['score']:g})" for i in block["reserves"])]

        lines.append("")

    rejected = [
        (label, item)
        for label in ("stays", "cafes")
        for item in (selection.get(label) or {}).get("rejected", [])
    ]

    if rejected:
        lines += [
            f"{sub} Considered but not chosen",
            "",
            "| Candidate | Score | Sources | Reviews seen | Why not |",
            "|---|---|---|---|---|",
        ]

        for _, item in rejected[:20]:
            lines.append(
                f"| {item['name']} | {item['score']:g} | {item['site_count']} | "
                f"{item['total_reviews'] or 'not shown'} | {item['reason']} |"
            )

        lines.append("")

    if selection.get("profiling_changes"):
        lines += [f"{sub} Swapped after profiling", ""]

        for change in selection["profiling_changes"]:
            lines.append(
                f"- {change['dropped']} -> {change['replaced_by']} ({change['reason']})"
            )

        lines.append("")

    if selection.get("notes"):
        lines += [f"{sub} Notes", ""]
        lines += [f"- {note}" for note in selection["notes"]]
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"
