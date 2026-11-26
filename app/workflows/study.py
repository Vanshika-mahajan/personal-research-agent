"""
A reusable property study for ANY place - no hand-written list needed.

    python -m app.main study "Goa" --stays 4 --cafes 3

1. discovery  finds the properties in that place with the most review
              material (app/workflows/discovery.py)
2. profiling  researches each one (complaints, why customers choose it,
              what they appreciate, how it keeps customers, what is missing)
3. report     one Markdown file: how the properties were chosen, the most
              common problems across them, then every property's profile

The Vibers brief is this study plus the platform audit, ideas and Part 2.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List

from app.graph.report_builder import source_link
from app.storage import research_dir, slugify
from app.workflows.discovery import (
    get_selection,
    profile_selection,
    render_selection_markdown,
)
from app.workflows.profiles import (
    profile_property,
    render_property_section,
    top_problems,
)


def render_study(selection: Dict[str, Any], profiles: List[Dict[str, Any]]) -> str:
    place = selection["place"]

    lines = [
        f"# Property study - {place}",
        "",
        f"*Generated {datetime.now().strftime('%d %b %Y %H:%M')} · "
        f"{len(profiles)} properties · every statement below is RESEARCHED from the linked sources; "
        "nothing is an idea or an opinion.*",
        "",
        render_selection_markdown(selection, heading_level=2),
    ]

    problems = top_problems(profiles, limit=5, min_sources=2)

    lines += [
        "## Most common customer problems",
        "",
        "**OBSERVATION - counted by keyword matching across all passages** (negative wording + a "
        "problem keyword). A problem only counts if it appears in at least 2 different sources, so "
        "fewer than five may be listed. Read the examples; the counting can misfire.",
        "",
    ]

    if problems:
        for rank, problem in enumerate(problems, start=1):
            lines.append(f"### {rank}. {problem['theme']}")
            lines.append(
                f"Seen at **{problem['property_count']}** of {len(profiles)} properties "
                f"({', '.join(problem['properties'])}), in **{problem['source_count']}** sources."
            )
            lines.append("")

            for example in problem["examples"]:
                text = " ".join(example["text"].split())[:280]
                link = source_link(
                    {
                        "source_title": example["source_title"],
                        "source_url": example["source_url"],
                        "platform": example["platform"],
                        "source_type": "web",
                    }
                )
                lines.append(f"- “{text}” - *{example['property']}* - {link}")

            lines.append("")
    else:
        lines += ["No problem was repeated across enough sources yet.", ""]

    lines += ["## The properties", ""]

    for profile in profiles:
        lines.append(render_property_section(profile, heading_level=3))

    return "\n".join(lines).rstrip() + "\n"


def run_study(
    place: str,
    *,
    stays: int = 3,
    cafes: int = 2,
    depth: str = "standard",
    refresh: bool = False,
    rediscover: bool = False,
    allow_thin: bool = False,
    min_reviews: int = 50,
    min_sites: int = 3,
    log=print,
) -> Dict[str, str]:
    """Discover, profile and write research/reports/study_<place>.md."""

    selection = get_selection(
        place,
        stays=stays,
        cafes=cafes,
        rediscover=rediscover,
        allow_thin=allow_thin,
        min_reviews=min_reviews,
        min_sites=min_sites,
        log=log,
    )

    specs = profile_selection(selection, depth=depth, refresh=refresh, log=log)

    if not specs:
        raise ValueError(
            f"No property in {place} cleared the evidence bar. Try --allow-thin or lower "
            "--min-reviews / --min-sources."
        )

    profiles = [profile_property(spec, depth=depth, refresh=False, log=log) for spec in specs]

    path = research_dir() / "reports" / f"study_{slugify(place)}.md"
    path.write_text(render_study(selection, profiles), encoding="utf-8")

    return {"study": str(path)}
