"""
Offline stand-ins for the LLM and the web, so the whole pipeline can be
tested without Ollama or internet.
"""

from __future__ import annotations

import json
import re
from typing import List

from app.schemas.source import SearchResult

COMPLAINT_WORDS = re.compile(r"dirty|noisy|rude|cold|overpriced|not working|smelled", re.I)


class FakeLLM:
    """Looks at which prompt it was given and answers like a decent model."""

    def __init__(self):
        self.calls: List[dict] = []

    def __call__(self, prompt: str, json_mode: bool = True, timeout=None) -> str:
        self.calls.append({"prompt": prompt, "json_mode": json_mode})

        if "evidence-grounded research analyst" in prompt:
            claims = dict(re.findall(r"\[(evidence_\d+)\]\nClaim: (.*)\n", prompt))

            findings = []

            for evidence_id, claim in list(claims.items())[:4]:
                category = "COMPLAINT" if COMPLAINT_WORDS.search(claim) else "PRAISE"
                findings.append(
                    {
                        "category": category,
                        "statement": claim[:140],
                        "evidence_ids": [evidence_id],
                        "confidence": 0.8,
                    }
                )

            # One invented finding citing an evidence id that does not exist.
            findings.append(
                {
                    "category": "COMPLAINT",
                    "statement": "Guests hate the parking lot.",
                    "evidence_ids": ["evidence_999"],
                    "confidence": 0.9,
                }
            )

            return json.dumps({"findings": findings})

        if "strict research finding verifier" in prompt:
            ids = re.findall(r"^\[(finding_\d+)\]", prompt, flags=re.M)

            return json.dumps(
                {
                    "verifications": [
                        {"finding_id": fid, "status": "VERIFIED", "reason": "ok"}
                        for fid in ids
                    ]
                }
            )

        if "research synthesis analyst" in prompt:
            return json.dumps(
                {"insights": ["Guests mention cleanliness and staff in several places."]}
            )

        if "executive summary" in prompt:
            return "Guests at this venue mention a mix of problems and praise across several sources."

        if "expert research planner" in prompt:
            return json.dumps(
                {
                    "queries": [
                        {"query": "goa hostels guest complaints", "purpose": "x", "priority": 5},
                        {"query": "goa hostels negative reviews", "purpose": "y", "priority": 4},
                    ],
                    "research_goals": ["find complaints"],
                    "expected_output": "complaints",
                }
            )

        if "follow-up query generator" in prompt:
            return json.dumps({"queries": ["a brand new follow up query reviews"]})

        if "Propose exactly 3 ideas" in prompt:
            return json.dumps(
                {
                    "ideas": [
                        {
                            "title": f"Idea {n}",
                            "problem_addressed": "Cleanliness & hygiene",
                            "how_it_works": "something",
                            "why_different": "something else",
                        }
                        for n in (1, 2, 3)
                    ]
                }
            )

        if "hard_to_find" in prompt:
            return json.dumps(
                {
                    "hard_to_find": ["competitor rates"],
                    "one_dashboard": ["demand trend"],
                    "morning_hooks": ["three actions"],
                }
            )

        return json.dumps({})


ZOSTEL_PAGE = (
    "Zostel Old Manali has a rooftop cafe and a garden. "
    "One guest wrote that the bathroom was dirty and the hot water was not working for two days. "
    "Another said the reception staff were rude when we asked for a refund. "
    "The location in Old Manali is great and the staff organised a fun bonfire night."
)


def fake_search_web(query: str, max_results: int = 5, official_domains=()):
    """Returns different, realistic-looking hits depending on the query."""

    q = query.lower()

    if "instagram" in q:
        return [
            SearchResult(
                title="Zostel Old Manali (@zostel) • Instagram photos",
                url="https://www.instagram.com/zostel/",
                snippet="Zostel Old Manali bonfire nights and weekly events for travellers.",
                source_type="social",
                platform="Instagram",
            )
        ]

    if "complaints" in q or "reddit" in q:
        return [
            SearchResult(
                title="Zostel Old Manali reviews - Hostelworld",
                url="https://www.hostelworld.com/hostels/p/267409/zostel-old-manali/",
                snippet="Zostel Old Manali guests complained the dorm was noisy and the bathroom was dirty.",
                source_type="booking",
                platform="Hostelworld",
            ),
            SearchResult(
                title="Best hostels in Manali - TravelBlog",
                url="https://travelblog.example.com/best-hostels-manali",
                snippet="Moustache Hostel Manali has dirty rooms and rude staff according to some guests.",
                source_type="web",
                platform="travelblog.example.com",
            ),
        ]

    return [
        SearchResult(
            title="Zostel Old Manali - Booking.com",
            url="https://www.booking.com/hotel/in/zostel-old-manali.html",
            snippet="Zostel Old Manali is in Old Manali with a garden cafe.",
            source_type="booking",
            platform="Booking.com",
        ),
        SearchResult(
            title="Zostel Old Manali Reviews - Tripadvisor",
            url="https://www.tripadvisor.in/Hotel_Review-Zostel-Old-Manali.html",
            snippet="Zostel Old Manali staff were rude and the room was cold at night.",
            source_type="review",
            platform="Tripadvisor",
        ),
    ]


def fake_fetch_page_text(url: str, max_chars: int = 20000) -> str:
    if "booking.com" in url:
        return ZOSTEL_PAGE

    return ""
