"""Finding categories shared by the analyzer, the report and the briefs."""

from __future__ import annotations

from typing import Dict, Tuple

# category -> (heading used in reports, definition shown to the LLM)
CATEGORIES: Dict[str, Tuple[str, str]] = {
    "COMPLAINT": (
        "Complaints & problems",
        "a guest/user complaint, problem, negative experience or recurring issue",
    ),
    "PRAISE": (
        "What customers appreciate",
        "a facility, service or experience that guests explicitly praise",
    ),
    "CHOICE_DRIVER": (
        "Why customers choose it",
        "a stated reason guests picked this place over others "
        "(location, price, vibe, reviews, brand, recommendation)",
    ),
    "RETENTION": (
        "How it attracts & retains customers",
        "a tactic that brings people in or makes them return: offers, loyalty, "
        "events, community, social media, repeat-guest behaviour",
    ),
    "BOOKING_UX": (
        "Booking experience (convenient / confusing)",
        "something convenient, confusing or unnecessarily complicated about "
        "booking, paying, cancelling or using a booking platform",
    ),
    "PRICING": (
        "Pricing & fees",
        "a stated price, fee, hidden charge or value-for-money opinion",
    ),
    "FEATURE": (
        "Features & facilities",
        "a stated feature, facility or capability (of a venue or a software tool)",
    ),
    "TREND": (
        "Demand, trends & events",
        "a change in demand, visitor numbers, season, event, weather or "
        "local activity that could affect business",
    ),
    "GAP": (
        "Gaps - what is missing",
        "something guests or owners say is missing, hard to find or wished for",
    ),
    "FACT": ("Other facts", "a neutral, verifiable fact relevant to the question"),
    "OTHER": ("Other", "relevant but fits none of the other categories"),
}

ORDER = list(CATEGORIES.keys())


def normalise_category(value: str) -> str:
    value = (value or "").strip().upper().replace(" ", "_").replace("-", "_")

    if value in CATEGORIES:
        return value

    # Older prompts used these labels.
    aliases = {
        "NEGATIVE": "COMPLAINT",
        "POSITIVE": "PRAISE",
        "OBSERVATION": "OTHER",
        "CONTRADICTION": "OTHER",
    }

    return aliases.get(value, "OTHER")
