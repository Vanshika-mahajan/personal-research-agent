"""
Property profiles and topic profiles.

A *property profile* answers, for ONE hotel / hostel / café, the five
customer questions from the Vibers brief:

    1. what do customers complain about?
    2. why do they choose it?
    3. what do they appreciate most?
    4. how does it attract and retain customers?
    5. what is missing?

(+ how the booking / pricing experience looks)

Profiles are cached as JSON in research/properties/, so a long brief can be
resumed and re-rendered without searching again. Add `--refresh` to redo one.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from app.graph.report_builder import (
    channel_coverage,
    evidence_index,
    render_coverage_markdown,
    render_findings_markdown,
    source_link,
)
from app.graph.themes import rank_themes
from app.runner import iterations_for, run_research
from app.schemas.research import ResearchQuestion
from app.storage import (
    load_manual_evidence,
    load_profile,
    save_profile,
)
from app.tools.source_types import domain_of

LODGING_TYPES = {"hostel", "hotel", "homestay", "resort", "guesthouse", "lodge"}

PROPERTY_ASPECTS = [
    "Customer complaints, problems and negative experiences",
    "What makes customers choose this place over others",
    "Facilities and experiences customers appreciate most",
    "How it attracts customers and encourages them to return "
    "(offers, events, loyalty, community, social media)",
    "What is missing or could be better (unmet needs, gaps)",
    "Booking and pricing experience (convenient or confusing)",
]


@dataclass
class PropertySpec:
    name: str
    place: str = "Manali"
    type: str = "hostel"  # hostel | hotel | cafe | restaurant ...
    website: str = ""
    instagram: str = ""
    notes: str = ""

    @property
    def is_lodging(self) -> bool:
        return self.type.lower() in LODGING_TYPES

    @property
    def official_domains(self) -> List[str]:
        return [d for d in (domain_of(self.website),) if d]


def spec_from_dict(data: Dict[str, Any]) -> PropertySpec:
    known = {field_name for field_name in PropertySpec.__dataclass_fields__}

    return PropertySpec(**{k: v for k, v in data.items() if k in known})


def load_specs(path: str | Path) -> Dict[str, Any]:
    """
    Read a properties file:

        {
          "place": "Manali",
          "properties": [ {name, type, place?, website?, instagram?}, ... ],
          "owner_properties": ["Zostel Old Manali", ...]     # optional
        }
    """

    data = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))

    default_place = data.get("place", "Manali")

    specs = []

    for item in data.get("properties", []):
        item = {"place": default_place, **item}
        specs.append(spec_from_dict(item))

    return {
        "place": default_place,
        "properties": specs,
        "owner_properties": data.get("owner_properties", []),
    }


# ------------------------------------------------------------------
# Query plan (deterministic - no LLM needed, works with tiny models)
# ------------------------------------------------------------------

def property_queries(spec: PropertySpec) -> List[str]:
    name = spec.name
    base = f"{name} {spec.place}".strip()

    queries = [
        f'"{name}" {spec.place} reviews'.strip(),
        f"{base} complaints negative reviews",
        f"{base} google reviews",
        f"{base} tripadvisor reviews",
        f"site:instagram.com {base}",
    ]

    if spec.website:
        queries.insert(2, f"site:{domain_of(spec.website)} {name}")

    if spec.is_lodging:
        queries += [
            f"{base} booking.com hostelworld reviews",
            f"{base} makemytrip agoda airbnb",
            f"{base} what guests love",
        ]
    else:
        queries += [
            f"{base} zomato reviews",
            f"{base} dineout justdial reviews",
            f"{base} what people love must try",
        ]

    queries += [
        f"{base} offers events membership",
        f"site:reddit.com {base}",
        f"{base} experience blog",
    ]

    return queries


def question_for(spec: PropertySpec, depth: str = "standard") -> ResearchQuestion:
    seed_urls = [url for url in (spec.website,) if url]

    return ResearchQuestion(
        question=(
            f"Profile {spec.name} ({spec.type}, {spec.place}). "
            + " ".join(f"{index}) {aspect}." for index, aspect in enumerate(PROPERTY_ASPECTS, 1))
        ),
        depth=depth,
        max_iterations=iterations_for(depth),
        mode="property",
        subject=spec.name,
        place=spec.place,
        aspects=PROPERTY_ASPECTS,
        official_domains=spec.official_domains,
        seed_urls=seed_urls,
        seed_queries=property_queries(spec),
    )


# ------------------------------------------------------------------
# Running
# ------------------------------------------------------------------

def _package(
    key: str,
    kind: str,
    result: Dict[str, Any],
    manual_count: int,
    extra: Dict[str, Any],
) -> Dict[str, Any]:
    state = result["state"]
    evidence = state.get("evidence", [])

    return {
        "key": key,
        "kind": kind,
        "run_id": result["run_id"],
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "manual_note_count": manual_count,
        "question": state["question"].model_dump(),
        "iterations": state.get("iteration", 0),
        "quality_score": state.get("evidence_score", 0.0),
        "missing_information": state.get("missing_information", []),
        "evidence": evidence,
        "findings": state.get("verified_findings", []),
        "insights": state.get("insights", []),
        "coverage": channel_coverage(evidence),
        "report_path": result["paths"].get("report", ""),
        **extra,
    }


def profile_property(
    spec: PropertySpec,
    *,
    depth: str = "standard",
    refresh: bool = False,
    log=print,
) -> Dict[str, Any]:
    """Research one property (or reuse the cached profile)."""

    manual = load_manual_evidence(spec.name)

    cached = load_profile(spec.name)

    if (
        cached
        and not refresh
        and cached.get("manual_note_count") == len(manual)
    ):
        log(f"\n=== {spec.name}: using saved profile (use --refresh to redo) ===")
        return cached

    log(f"\n{'=' * 60}\nPROFILING: {spec.name} ({spec.type}, {spec.place})\n{'=' * 60}")

    result = run_research(
        question_for(spec, depth),
        label=spec.name,
        manual_evidence=manual,
    )

    profile = _package(
        spec.name,
        "property",
        result,
        len(manual),
        {"spec": asdict(spec)},
    )

    save_profile(spec.name, profile)

    return profile


def profile_topic(
    key: str,
    *,
    title: str,
    question: str,
    queries: List[str],
    aspects: Optional[List[str]] = None,
    depth: str = "standard",
    refresh: bool = False,
    log=print,
) -> Dict[str, Any]:
    """
    Research a themed topic with hand-written queries (a booking platform,
    a revenue tool, local market intelligence ...). Cached like properties.
    """

    manual = load_manual_evidence(key)

    cached = load_profile(key, kind="topics")

    if (
        cached
        and not refresh
        and cached.get("manual_note_count") == len(manual)
    ):
        log(f"\n=== {title}: using saved research (use --refresh to redo) ===")
        return cached

    log(f"\n{'=' * 60}\nTOPIC: {title}\n{'=' * 60}")

    result = run_research(
        ResearchQuestion(
            question=question,
            depth=depth,
            max_iterations=iterations_for(depth),
            mode="topic",
            subject=title,
            aspects=aspects or [],
            seed_queries=queries,
        ),
        label=key,
        manual_evidence=manual,
    )

    profile = _package(key, "topic", result, len(manual), {"title": title})

    save_profile(key, profile, kind="topics")

    return profile


# ------------------------------------------------------------------
# Reading profiles
# ------------------------------------------------------------------

def verified(profile: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [
        finding
        for finding in profile.get("findings", [])
        if finding.get("verification_status") == "VERIFIED"
    ]


def findings_in(profile: Dict[str, Any], category: str) -> List[Dict[str, Any]]:
    return [
        finding
        for finding in verified(profile)
        if (finding.get("category") or finding.get("type")) == category
    ]


def complaint_passages(profiles: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Raw evidence passages from independent sources (not the venue's own
    website, which rarely contains complaints) for theme counting.
    """

    passages = []

    for profile in profiles:
        name = profile.get("key") or profile.get("spec", {}).get("name", "")

        for item in profile.get("evidence", []):
            if item.get("source_type") == "official":
                continue

            passages.append(
                {
                    "text": item.get("claim", ""),
                    "property": name,
                    "source_url": item.get("source_url", ""),
                    "source_title": item.get("source_title", ""),
                    "platform": item.get("platform", ""),
                }
            )

    return passages


def top_problems(
    profiles: Iterable[Dict[str, Any]],
    limit: int = 5,
    min_sources: int = 2,
) -> List[Dict[str, Any]]:
    """
    The most common customer problems across properties.

    A problem must show up in at least `min_sources` distinct sources to
    count as "repeated". If fewer than `limit` qualify we return fewer -
    padding the list would be inventing a pattern.
    """

    return rank_themes(complaint_passages(profiles), min_sources=min_sources)[:limit]


# ------------------------------------------------------------------
# Rendering
# ------------------------------------------------------------------

def _raw_evidence_markdown(evidence: List[Dict[str, Any]], limit: int = 6) -> str:
    items = sorted(
        evidence,
        key=lambda item: (item.get("origin") == "manual", item.get("confidence", 0)),
        reverse=True,
    )[:limit]

    if not items:
        return "*No evidence collected.*"

    lines = []

    for item in items:
        claim = " ".join(str(item.get("claim", "")).split())[:300]
        lines.append(f"- “{claim}” - {source_link(item)}")

    return "\n".join(lines)


def render_property_section(profile: Dict[str, Any], heading_level: int = 2) -> str:
    spec = profile.get("spec", {})
    hashes = "#" * heading_level
    sub = "#" * (heading_level + 1)

    lines = [
        f"{hashes} {spec.get('name', profile.get('key', 'Property'))}",
        "",
        f"*{spec.get('type', '').title()} · {spec.get('place', '')} · "
        f"RESEARCHED from web sources, run `{profile.get('run_id', '')}`*",
        "",
        f"{sub} Channels reached",
        "",
        render_coverage_markdown(profile.get("evidence", [])),
        "",
        f"{sub} What we observed (verified findings)",
        "",
    ]

    body = render_findings_markdown(
        verified(profile),
        profile.get("evidence", []),
        heading_level=heading_level + 2,
    )

    if body:
        lines.append(body)
    else:
        lines += [
            "No finding passed verification for this property.",
            "",
            f"{sub} Raw evidence (unprocessed - read it yourself)",
            "",
            _raw_evidence_markdown(profile.get("evidence", [])),
        ]

    if profile.get("missing_information"):
        lines += ["", f"{sub} Gaps in the research", ""]
        lines += [f"- {item}" for item in profile["missing_information"]]

    return "\n".join(lines).strip() + "\n"


def render_topic_section(profile: Dict[str, Any], heading_level: int = 3) -> str:
    hashes = "#" * heading_level

    lines = [f"{hashes} {profile.get('title', profile.get('key', 'Topic'))}", ""]

    body = render_findings_markdown(
        verified(profile),
        profile.get("evidence", []),
        heading_level=heading_level + 1,
    )

    if body:
        lines.append(body)
    else:
        lines += [
            "*No finding passed verification. Raw evidence:*",
            "",
            _raw_evidence_markdown(profile.get("evidence", []), limit=5),
        ]

    return "\n".join(lines).strip() + "\n"
