"""
Deterministic report assembly.

The LLM is NOT asked to write the sources list or restate findings (small
models invent both). Findings, links and coverage come straight from the
verified data; the LLM may only add a short optional summary on top.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Iterable, List

from app.graph.taxonomy import CATEGORIES, ORDER, normalise_category


def evidence_index(evidence: Iterable[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    return {item.get("evidence_id"): item for item in evidence}


def source_link(item: Dict[str, Any]) -> str:
    """Markdown link (or plain label for manual notes) for one evidence item."""

    url = str(item.get("source_url", "") or "")
    title = str(item.get("source_title", "") or "source").strip()
    platform = str(item.get("platform", "") or "").strip()

    label = title if not platform or platform.lower() in title.lower() else (
        f"{title} ({platform})"
    )

    label = label.replace("[", "(").replace("]", ")")[:90]

    if item.get("source_type") == "manual" or not url.startswith("http"):
        return f"{label} - *your note*"

    return f"[{label}]({url})"


def finding_sources(
    finding: Dict[str, Any],
    by_id: Dict[str, Dict[str, Any]],
    limit: int = 3,
) -> List[str]:
    links: List[str] = []
    seen = set()

    for evidence_id in finding.get("evidence_ids", []):
        item = by_id.get(evidence_id)

        if not item:
            continue

        key = item.get("source_url") or evidence_id

        if key in seen:
            continue

        seen.add(key)
        links.append(source_link(item))

        if len(links) >= limit:
            break

    return links


def group_by_category(
    findings: Iterable[Dict[str, Any]],
) -> Dict[str, List[Dict[str, Any]]]:
    grouped: Dict[str, List[Dict[str, Any]]] = {}

    for finding in findings:
        category = normalise_category(
            finding.get("category") or finding.get("type", "")
        )
        grouped.setdefault(category, []).append(finding)

    for items in grouped.values():
        items.sort(key=lambda item: item.get("confidence", 0), reverse=True)

    return grouped


def render_findings_markdown(
    findings: Iterable[Dict[str, Any]],
    evidence: Iterable[Dict[str, Any]],
    heading_level: int = 3,
    only: Iterable[str] | None = None,
) -> str:
    """Findings grouped by category, each with source links."""

    by_id = evidence_index(evidence)
    grouped = group_by_category(findings)
    hashes = "#" * heading_level
    wanted = set(only) if only else None

    lines: List[str] = []

    for category in ORDER:
        if wanted is not None and category not in wanted:
            continue

        items = grouped.get(category)

        if not items:
            continue

        lines.append(f"{hashes} {CATEGORIES[category][0]}")
        lines.append("")

        for finding in items:
            sources = finding_sources(finding, by_id)
            source_text = " · ".join(sources) if sources else "*no source*"

            lines.append(
                f"- **FINDING** - {finding.get('statement', '').strip()} "
                f"*(confidence {finding.get('confidence', 0):.2f})*  "
            )
            lines.append(f"  Sources: {source_text}")

        lines.append("")

    return "\n".join(lines).strip()


def channel_coverage(evidence: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Which channels did we actually get text from?

    The brief says: look at Google reviews, Instagram, websites and booking
    platforms. Google Maps and Instagram cannot be read without logging in,
    so this table tells the truth about what was and was not reached.
    """

    channels = [
        ("maps", "Google Maps / Google reviews"),
        ("social", "Instagram / Facebook"),
        ("official", "Official website"),
        ("booking", "Booking platforms (Booking.com, Hostelworld, Zostel, MakeMyTrip, Airbnb ...)"),
        ("review", "Review sites (Tripadvisor, Zomato ...)"),
        ("forum", "Forums (Reddit, Quora)"),
        ("web", "Blogs & articles"),
        ("manual", "Notes you added by hand"),
    ]

    rows = []

    evidence = list(evidence)

    for source_type, label in channels:
        items = [item for item in evidence if item.get("source_type") == source_type]
        origins = {item.get("origin", "snippet") for item in items}
        urls = {item.get("source_url") for item in items}

        if not items:
            status = "none"
            note = "Nothing found"

            if source_type in {"maps", "social"}:
                note = (
                    "Not readable automatically (login / JavaScript). "
                    "Paste real reviews or captions with the `note` command."
                )

        elif origins == {"snippet"}:
            status = "snippet"
            note = "Search-engine snippets only (no full page text)"

        else:
            status = "full"
            note = "Full text read"

        rows.append(
            {
                "channel": label,
                "source_type": source_type,
                "passages": len(items),
                "sources": len(urls),
                "status": status,
                "note": note,
            }
        )

    return rows


def render_coverage_markdown(evidence: Iterable[Dict[str, Any]]) -> str:
    icons = {"full": "✅", "snippet": "⚠️", "none": "❌"}

    lines = [
        "| Channel | Status | Passages | Sources | Note |",
        "|---|---|---|---|---|",
    ]

    for row in channel_coverage(evidence):
        # Empty "blogs / forums / manual notes" rows are noise; the five
        # channels the brief asks about are always shown.
        if row["status"] == "none" and row["source_type"] in {"forum", "web", "manual"}:
            continue

        lines.append(
            f"| {row['channel']} | {icons[row['status']]} | "
            f"{row['passages']} | {row['sources']} | {row['note']} |"
        )

    return "\n".join(lines)


def unique_sources(evidence: Iterable[Dict[str, Any]]) -> List[str]:
    seen = set()
    lines = []

    for item in evidence:
        url = str(item.get("source_url", "") or "")

        if not url.startswith("http") or url in seen:
            continue

        seen.add(url)
        lines.append(f"- {source_link(item)}")

    return lines


def build_report_markdown(
    *,
    title: str,
    question: str,
    run_id: str = "",
    verified: List[Dict[str, Any]],
    all_findings: List[Dict[str, Any]],
    evidence: List[Dict[str, Any]],
    insights: List[str],
    missing_information: List[str],
    summary: str = "",
) -> str:
    stamp = datetime.now().strftime("%d %b %Y %H:%M")

    lines: List[str] = [
        f"# {title}",
        "",
        f"*Generated {stamp}" + (f" · run `{run_id}`" if run_id else "") + "*",
        "",
        "## Research question",
        "",
        question,
        "",
        "## How to read this report",
        "",
        "- **FINDING** - checked against the evidence; every one lists its sources.",
        "- **INSIGHT** - an AI synthesis built only from the findings above. "
        "It is an interpretation, not new evidence.",
        "- Anything without a source link is not research.",
        "",
    ]

    if summary.strip():
        lines += [
            "## Summary",
            "",
            f"*AI-written summary of the verified findings:* {summary.strip()}",
            "",
        ]

    lines += ["## Key findings", ""]

    if verified:
        lines.append(render_findings_markdown(verified, evidence, heading_level=3))
    else:
        lines.append(
            "No finding passed verification. The evidence collected was not "
            "strong enough to answer the question reliably - see limitations."
        )

    lines += ["", "## Insights (synthesis)", ""]

    real_insights = [item for item in insights if item]

    if real_insights and verified:
        lines += [f"- **INSIGHT** - {item}" for item in real_insights]
    else:
        lines.append("None - not enough verified findings to synthesise.")

    unverified = [
        finding
        for finding in all_findings
        if finding.get("verification_status") != "VERIFIED"
    ]

    if unverified:
        lines += ["", "## Leads that did not pass verification", ""]
        lines.append(
            "Kept for transparency. Treat as ideas to check, not as results."
        )
        lines.append("")

        for finding in unverified[:10]:
            lines.append(
                f"- ({finding.get('verification_status', 'UNSUPPORTED')}) "
                f"{finding.get('statement', '').strip()} - "
                f"{finding.get('verification_reason', '')}"
            )

    lines += ["", "## Coverage & limitations", ""]
    lines.append(render_coverage_markdown(evidence))
    lines.append("")

    if missing_information:
        lines += [f"- {item}" for item in missing_information]
    else:
        lines.append("- The built-in quality checks found no obvious gaps.")

    lines += ["", "## Sources", ""]

    sources = unique_sources(evidence)

    lines += sources or ["No web sources."]

    return "\n".join(lines).strip() + "\n"
