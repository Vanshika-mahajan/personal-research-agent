"""
Turn raw sources into a ranked, capped list of evidence passages.

Why this exists
---------------
The first version put EVERY search snippet into the LLM prompt. With a small
local model that overflows the context window and the model quietly ignores
most of the evidence. Here we
  1. split pages into passages,
  2. drop navigation / cookie noise,
  3. (property mode) drop passages that are about OTHER venues,
  4. rank by relevance and cap per source and in total, so every source gets
     a fair share.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Set

from app.graph.themes import PROFILE_LEXICON
from app.tools.source_types import source_confidence
from app.tools.webpage_reader import split_passages

NOISE_PHRASES = (
    "cookie policy",
    "privacy policy",
    "terms of use",
    "terms and conditions",
    "sign in",
    "log in",
    "subscribe",
    "all rights reserved",
    "accept cookies",
    "enable javascript",
    "download the app",
)

STOPWORDS = frozenset(
    """
    a an and are as at be by for from has have in is it its of on or that the
    their there this to was were will with you your our we they them i not but
    if so than then too very can could would should about into over under out
    up down more most some any all each other such only own same just also how
    what which who whom when where why
    """.split()
)

GENERIC_NAME_WORDS = frozenset(
    """
    hostel hostels hotel hotels cafe cafes lodge resort resorts homestay stay
    stays inn house restaurant coffee roasters the and of in by at
    """.split()
)

_TOKEN = re.compile(r"[a-z0-9][a-z0-9\-]*")


def _normalise(text: str) -> str:
    return (
        (text or "")
        .lower()
        .replace("’", "")
        .replace("'", "")
        .replace("é", "e")  # café -> cafe
    )


def tokens(text: str) -> List[str]:
    return _TOKEN.findall(_normalise(text))


def keywords(text: str) -> Set[str]:
    return {token for token in tokens(text) if token not in STOPWORDS}


def subject_tokens(subject: str, place: str = "") -> List[str]:
    """
    Distinctive words of a venue name, in order.

    "Zostel Old Manali"           -> ["zostel"]  (place words removed)
    "The Hosteller Manali"        -> ["hosteller"]
    "Cafe 1947"                   -> ["1947"]
    "Dylan's Toasted & Roasted"   -> ["dylans", "toasted", "roasted"]
    """

    place_words = set(tokens(place)) | {"old", "new"}

    picked = [
        token
        for token in tokens(subject)
        if token not in GENERIC_NAME_WORDS
        and token not in STOPWORDS
        and token not in place_words
    ]

    if not picked:
        picked = [token for token in tokens(subject) if token not in STOPWORDS]

    return picked


def mentions_subject(
    text: str,
    subject: str,
    place: str = "",
) -> bool:
    """Does this text talk about the named venue?"""

    picked = subject_tokens(subject, place)

    if not picked:
        return True

    haystack = set(tokens(text))
    primary = picked[0]

    if primary.isdigit():
        # "1947" alone is far too ambiguous - need the whole name.
        return _normalise(subject) in _normalise(text) or (
            len(set(picked) & haystack) >= 1
            and bool(haystack & {"cafe", "restaurant"})
        )

    if primary in haystack:
        return True

    return len(set(picked) & haystack) >= 2


def _is_noise(passage: str) -> bool:
    lowered = passage.lower()

    if len(passage) < 40:
        return True

    if any(phrase in lowered for phrase in NOISE_PHRASES):
        return True

    letters = sum(char.isalpha() for char in passage)

    return letters / max(len(passage), 1) < 0.55


def _score(passage: str, focus: Set[str], lexicon: Set[str]) -> float:
    words = set(tokens(passage))

    return (
        2.0 * len(words & focus)
        + 1.0 * len(words & lexicon)
        + min(len(passage), 400) / 400
    )


def _get(source: Any, key: str, default: Any = "") -> Any:
    if isinstance(source, dict):
        return source.get(key, default) or default

    return getattr(source, key, default) or default


def build_evidence(
    sources: Iterable[Any],
    *,
    focus_text: str = "",
    subject: str = "",
    place: str = "",
    manual: Optional[List[Dict[str, Any]]] = None,
    max_total: int = 60,
    per_source: int = 4,
    per_page: int = 6,
    use_profile_lexicon: bool = False,
) -> List[Dict[str, Any]]:
    """
    Return evidence dicts:

        evidence_id, claim, source_title, source_url, source_type,
        platform, origin ("snippet" | "page" | "manual"), confidence

    Manual notes (text you pasted in) always come first and are never
    filtered by subject - you wrote them about this venue.
    """

    focus = keywords(focus_text) | set(subject_tokens(subject, place))
    lexicon = set(PROFILE_LEXICON) if use_profile_lexicon else set()

    candidates: List[Dict[str, Any]] = []
    seen: Set[str] = set()

    def _remember(passage: str) -> bool:
        key = re.sub(r"\W+", " ", passage.lower())[:140]

        if key in seen:
            return False

        seen.add(key)
        return True

    # ---- manual notes ------------------------------------------------
    manual_items: List[Dict[str, Any]] = []

    for note in manual or []:
        text = (note.get("text") or "").strip()

        if len(text) < 10 or not _remember(text):
            continue

        manual_items.append(
            {
                "claim": text[:1000],
                "source_title": note.get("platform") or "Manual note",
                "source_url": note.get("source_url") or "manual-note",
                "source_type": "manual",
                "platform": note.get("platform") or "Manual note",
                "origin": "manual",
                "confidence": source_confidence("manual"),
            }
        )

    # ---- web sources -------------------------------------------------
    for source in sources:
        title = str(_get(source, "title"))
        url = str(_get(source, "url"))
        snippet = str(_get(source, "snippet") or _get(source, "content_snippet"))
        content = str(_get(source, "content"))
        source_type = str(_get(source, "source_type", "web"))
        platform = str(_get(source, "platform"))

        about_subject = bool(subject) and mentions_subject(
            f"{title} {url}", subject, place
        )

        texts = []

        if snippet:
            texts.append(("snippet", snippet))

        if content:
            texts.append(("page", content))

        local: List[Dict[str, Any]] = []

        for origin, text in texts:
            for passage in split_passages(text):
                passage = passage.strip()

                if _is_noise(passage):
                    continue

                if (
                    subject
                    and not about_subject
                    and not mentions_subject(passage, subject, place)
                ):
                    continue

                if not _remember(passage):
                    continue

                local.append(
                    {
                        "claim": passage[:1000],
                        "source_title": title or "Unknown source",
                        "source_url": url,
                        "source_type": source_type or "web",
                        "platform": platform,
                        "origin": origin,
                        "confidence": source_confidence(source_type),
                        "_score": _score(passage, focus, lexicon),
                    }
                )

        local.sort(key=lambda item: item["_score"], reverse=True)

        limit = per_page if content else per_source

        candidates.extend(local[:limit])

    candidates.sort(key=lambda item: item["_score"], reverse=True)

    room = max(max_total - len(manual_items), 0)

    chosen = manual_items + candidates[:room]

    evidence = []

    for index, item in enumerate(chosen, start=1):
        item = {key: value for key, value in item.items() if key != "_score"}
        item["evidence_id"] = f"evidence_{index}"
        evidence.append(item)

    return evidence
