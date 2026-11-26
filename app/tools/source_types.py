"""
Classify a URL into a source type + human-readable platform name.

The brief asks us to look at Google reviews, Instagram, websites and booking
platforms. Those are very different kinds of evidence, so every piece of
evidence carries its channel. Reports can then say honestly which channels
were really reached.

source_type values:
    maps      Google Maps / Google Business
    social    Instagram, Facebook, X
    review    Tripadvisor, Zomato, JustDial ...
    booking   Booking.com, Hostelworld, Zostel, MakeMyTrip, Airbnb ...
    forum     Reddit, Quora
    video     YouTube
    official  the property's own website (needs official_domains)
    manual    notes pasted in by the user
    web       everything else (blogs, listicles, news)
"""

from __future__ import annotations

from typing import Iterable, Tuple
from urllib.parse import urlparse

# (substring to look for in "host + path", source_type, platform label)
# Order matters: first match wins.
_RULES: list[Tuple[str, str, str]] = [
    ("google.com/maps", "maps", "Google Maps"),
    ("maps.google", "maps", "Google Maps"),
    ("maps.app.goo.gl", "maps", "Google Maps"),
    ("goo.gl/maps", "maps", "Google Maps"),
    ("g.page", "maps", "Google Maps"),
    ("google.com/travel", "maps", "Google Travel"),
    ("instagram.com", "social", "Instagram"),
    ("facebook.com", "social", "Facebook"),
    ("fb.com", "social", "Facebook"),
    ("twitter.com", "social", "X"),
    ("x.com/", "social", "X"),
    ("youtube.com", "video", "YouTube"),
    ("youtu.be", "video", "YouTube"),
    ("reddit.com", "forum", "Reddit"),
    ("quora.com", "forum", "Quora"),
    ("tripadvisor.", "review", "Tripadvisor"),
    ("zomato.com", "review", "Zomato"),
    ("dineout.co.in", "review", "Dineout"),
    ("justdial.com", "review", "JustDial"),
    ("mouthshut.com", "review", "MouthShut"),
    ("trustpilot.com", "review", "Trustpilot"),
    ("yelp.", "review", "Yelp"),
    ("booking.com", "booking", "Booking.com"),
    ("hostelworld.com", "booking", "Hostelworld"),
    ("zostel.com", "booking", "Zostel"),
    ("makemytrip.com", "booking", "MakeMyTrip"),
    ("goibibo.com", "booking", "Goibibo"),
    ("agoda.com", "booking", "Agoda"),
    ("airbnb.", "booking", "Airbnb"),
    ("expedia.", "booking", "Expedia"),
    ("hotels.com", "booking", "Hotels.com"),
    ("travelocity.", "booking", "Travelocity"),
    ("cleartrip.com", "booking", "Cleartrip"),
    ("ixigo.com", "booking", "ixigo"),
    ("yatra.com", "booking", "Yatra"),
    ("oyorooms.com", "booking", "OYO"),
    ("treebo.com", "booking", "Treebo"),
    ("thehosteller.com", "booking", "The Hosteller"),
]

# Pages we should NOT try to download: they need a login or are rendered by
# JavaScript, so a plain HTTP fetch returns nothing useful. We keep the
# search-engine snippet and tell the user to paste real text via `note`.
_WALLED_TYPES = {"maps", "social", "video"}

# Prior belief about how much to trust a passage from each channel.
_CONFIDENCE = {
    "manual": 0.8,
    "review": 0.65,
    "booking": 0.65,
    "maps": 0.6,
    "official": 0.6,
    "forum": 0.55,
    "web": 0.5,
    "social": 0.5,
    "video": 0.4,
}


def _host_and_path(url: str) -> str:
    parsed = urlparse(url if "://" in url else f"https://{url}")
    host = (parsed.netloc or "").lower()

    if host.startswith("www."):
        host = host[4:]

    return f"{host}{parsed.path.lower()}"


def classify_url(
    url: str,
    official_domains: Iterable[str] = (),
) -> Tuple[str, str]:
    """Return (source_type, platform_label) for a URL."""

    if not url:
        return "web", ""

    haystack = _host_and_path(url)
    host = haystack.split("/")[0]

    for domain in official_domains or ():
        domain = (domain or "").lower().replace("www.", "").strip("/")

        if domain and (host == domain or host.endswith("." + domain)):
            return "official", "Official website"

    for needle, source_type, label in _RULES:
        if needle in haystack:
            return source_type, label

    return "web", host


def is_walled(source_type: str) -> bool:
    """True when the page cannot be fetched with a simple HTTP request."""

    return source_type in _WALLED_TYPES


def source_confidence(source_type: str) -> float:
    """Prior confidence for evidence coming from this kind of source."""

    return _CONFIDENCE.get(source_type, 0.5)


def domain_of(url: str) -> str:
    """'https://www.zostel.com/zostel/manali/' -> 'zostel.com'"""

    if not url:
        return ""

    return _host_and_path(url).split("/")[0]
