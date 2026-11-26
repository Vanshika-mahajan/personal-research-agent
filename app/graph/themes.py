"""
Complaint themes + lexicons.

This is deliberately simple and transparent (keyword matching), so that the
"5 most common customer problems" can be explained and checked by a human.
It does not replace the LLM findings; it counts how often each problem shows
up in the raw evidence across properties and sources.

A passage counts toward a theme only when it contains
  (a) a keyword of that theme AND
  (b) a negative cue
because "rooms were clean" contains "clean" but is not a cleanliness complaint.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List

THEMES: Dict[str, List[str]] = {
    "Cleanliness & hygiene": [
        "dirty", "unclean", "filthy", "smell", "stink", "stained", "dust",
        "cockroach", "bedbug", "bed bug", "insect", "cleanliness", "hygiene",
        "unhygienic", "towel", "linen", "sheets", "washroom",
    ],
    "Noise & disturbance": [
        "noise", "noisy", "loud", "music", "party", "disturb", "sleep",
        "thin walls", "late night", "shouting",
    ],
    "Staff behaviour & service": [
        "staff", "rude", "reception", "behaviour", "behavior", "attitude",
        "unhelpful", "ignored", "service", "manager", "check-in", "checkin",
        "check in", "waiting",
    ],
    "Hot water, heating & bathrooms": [
        "hot water", "geyser", "heater", "heating", "cold room", "freezing",
        "bathroom", "toilet", "shower", "blanket", "damp", "mould", "mold",
        "leak", "seepage",
    ],
    "Food & café quality or price": [
        "food", "breakfast", "meal", "menu", "coffee", "kitchen", "taste",
        "stale", "portion", "cafe", "café", "restaurant", "overpriced menu",
    ],
    "Wi-Fi, power & connectivity": [
        "wifi", "wi-fi", "internet", "network", "power cut", "electricity",
        "charging", "signal", "connectivity", "generator", "backup",
    ],
    "Pricing, hidden charges & value": [
        "overpriced", "expensive", "costly", "hidden charge", "extra charge",
        "hidden fee", "extra fee", "price", "pricing", "rip off", "ripoff",
        "not worth", "value for money", "surge", "tax", "charged",
    ],
    "Booking, cancellation & refunds": [
        "booking", "cancel", "cancellation", "refund", "overbooked",
        "advance", "payment", "confirmation", "reservation", "no-show",
        "app", "website", "support", "customer care",
    ],
    "Location, access & parking": [
        "parking", "road", "steep", "walk", "far", "access", "narrow",
        "location", "transport", "taxi", "cab", "traffic", "difficult to reach",
    ],
    "Safety & security": [
        "unsafe", "safety", "security", "theft", "stolen", "lock", "locker",
        "scam", "harass", "drunk", "fire exit",
    ],
    "Overcrowding, space & comfort": [
        "crowded", "overcrowded", "small room", "cramped", "tiny", "bed",
        "mattress", "uncomfortable", "space", "dorm", "privacy", "queue",
    ],
    "Photos & expectations mismatch": [
        "misleading", "not as shown", "not as described", "photos", "pictures",
        "different from", "false advertising", "expectation", "disappointed",
        "disappointing", "not as advertised",
    ],
}

NEGATIVE_CUES = frozenset(
    """
    poor bad worst terrible horrible awful dirty rude slow
    disappointed disappointing disappointment complaint complained complain
    issue issues problem problems overpriced expensive unhelpful uncomfortable
    unsafe unclean unhygienic noisy cold broken delay delayed late missing
    lack lacked lacking stale waste worse avoid unprofessional unacceptable
    pathetic scam cheated overcharged overcharge charged failed fail
    refused refuse ignored mismanaged mismanagement messy smelly smell
    """.split()
)

PRAISE_CUES = frozenset(
    """
    love loved loving amazing awesome great fantastic wonderful friendly
    helpful clean comfortable cozy cosy beautiful stunning delicious lovely
    perfect excellent best recommend recommended vibe vibes atmosphere
    welcoming warm memorable
    """.split()
)

RETENTION_CUES = frozenset(
    """
    offer offers discount loyalty member membership reward rewards cashback
    event events workshop workshops bonfire trek treks tour tours jam open-mic
    revisit return returned again repeat regular referral coupon package
    combo happy-hour live-music
    """.split()
)

GAP_CUES = frozenset(
    """
    wish missing lack lacking should could unavailable nowhere hard difficult
    confusing complicated unclear couldn't cannot can't wasn't weren't
    """.split()
)

_TOKEN = re.compile(r"[a-z0-9][a-z0-9'\-]*")

# "not clean", "wasn't working", "never helpful" ... A bare "no"/"not" is
# NOT a complaint on its own ("no smoking in rooms", "not far from the mall").
_NEGATED_POSITIVE = re.compile(
    r"\b(?:not|no|never|isn'?t|wasn'?t|weren'?t|aren'?t|don'?t|didn'?t|"
    r"doesn'?t|without)\s+(?:\w+\s+){0,2}"
    r"(?:clean|working|available|helpful|friendly|worth|enough|hot|good|great|"
    r"comfortable|safe|fresh|polite|responsive|cooperative|provided|worked|"
    r"as\s+(?:described|shown|advertised))\b"
)


def _norm(text: str) -> str:
    return (text or "").lower().replace("’", "'")


def _tokens(text: str) -> set:
    return set(_TOKEN.findall(_norm(text).replace("'", "")))


def has_negative_cue(text: str) -> bool:
    lowered = _norm(text).replace("'", "'")

    return bool(_tokens(lowered) & NEGATIVE_CUES) or bool(
        _NEGATED_POSITIVE.search(lowered)
    )


def themes_for(text: str) -> List[str]:
    """Complaint themes present in a passage (needs a negative cue)."""

    lowered = _norm(text)

    if not has_negative_cue(lowered):
        return []

    found = []

    for theme, keywords in THEMES.items():
        for keyword in keywords:
            if keyword in lowered:
                found.append(theme)
                break

    return found


def rank_themes(
    passages: Iterable[Dict[str, Any]],
    min_sources: int = 1,
) -> List[Dict[str, Any]]:
    """
    Count complaint themes across passages.

    Each passage is a dict with at least: text, property, source_url.
    Optional: source_title, platform.

    Returns themes ranked by (number of properties affected, number of
    distinct sources, number of passages), each with up to 3 example
    passages so a human can sanity-check the match.
    """

    buckets: Dict[str, Dict[str, Any]] = {}

    for passage in passages:
        text = passage.get("text", "")

        for theme in themes_for(text):
            bucket = buckets.setdefault(
                theme,
                {
                    "theme": theme,
                    "passages": 0,
                    "properties": set(),
                    "sources": set(),
                    "examples": [],
                },
            )

            bucket["passages"] += 1
            bucket["properties"].add(passage.get("property", "") or "unknown")
            bucket["sources"].add(passage.get("source_url", "") or text[:40])

            if len(bucket["examples"]) < 3 and not any(
                example["text"] == text for example in bucket["examples"]
            ):
                bucket["examples"].append(
                    {
                        "text": text,
                        "property": passage.get("property", ""),
                        "source_title": passage.get("source_title", ""),
                        "source_url": passage.get("source_url", ""),
                        "platform": passage.get("platform", ""),
                    }
                )

    ranked = []

    for bucket in buckets.values():
        if len(bucket["sources"]) < min_sources:
            continue

        ranked.append(
            {
                "theme": bucket["theme"],
                "passages": bucket["passages"],
                "properties": sorted(bucket["properties"]),
                "property_count": len(bucket["properties"]),
                "source_count": len(bucket["sources"]),
                "examples": bucket["examples"],
            }
        )

    ranked.sort(
        key=lambda item: (
            item["property_count"],
            item["source_count"],
            item["passages"],
        ),
        reverse=True,
    )

    return ranked


# Words that make a passage worth keeping when we are profiling a venue:
# complaints, praise, retention and gap language all matter.
PROFILE_LEXICON = (
    NEGATIVE_CUES
    | PRAISE_CUES
    | RETENTION_CUES
    | GAP_CUES
    | {
        "review", "reviews", "guests", "guest", "stay", "stayed", "rooms",
        "room", "dorm", "price", "booking", "booked", "checkin", "view",
        "staff", "food", "location", "wifi", "hot", "water",
    }
)
