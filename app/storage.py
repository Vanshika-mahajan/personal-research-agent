"""
Everything the agent saves lives under research/ :

    research/raw/        full page text of every source        (git-ignored)
    research/evidence/   evidence, findings, verification (JSON)
    research/reports/    finished reports (Markdown) + briefs
    research/properties/ one JSON profile per property (cached; reused by briefs)
    research/topics/     one JSON profile per platform / tool / market topic
    research/manual/     notes YOU pasted in (Google reviews, Instagram ...)
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from app.config import get_settings

SUBDIRS = ("raw", "evidence", "reports", "properties", "topics", "manual")


def research_dir() -> Path:
    base = get_settings().research_dir

    for name in SUBDIRS:
        (base / name).mkdir(parents=True, exist_ok=True)

    return base


def slugify(text: str, max_len: int = 60) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")

    return (slug or "research")[:max_len].strip("-") or "research"


def new_run_id(label: str) -> str:
    return f"{slugify(label, 40)}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"


def _dump(obj: Any) -> Any:
    """JSON default: pydantic models -> dicts, sets -> lists."""

    if hasattr(obj, "model_dump"):
        return obj.model_dump()

    if isinstance(obj, set):
        return sorted(obj)

    if isinstance(obj, Path):
        return str(obj)

    return str(obj)


def write_json(path: Path, data: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False, default=_dump),
        encoding="utf-8",
    )

    return path


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


# ------------------------------------------------------------------
# Runs
# ------------------------------------------------------------------

def save_run(run_id: str, state: Dict[str, Any]) -> Dict[str, str]:
    """Write raw sources, evidence/findings and the report for one run."""

    base = research_dir()

    raw_path = write_json(
        base / "raw" / f"{run_id}.json",
        {"sources": state.get("sources", [])},
    )

    question = state.get("question")

    evidence_path = write_json(
        base / "evidence" / f"{run_id}.json",
        {
            "run_id": run_id,
            "question": question.model_dump() if question else {},
            "queries": state.get("search_queries", []),
            "iterations": state.get("iteration", 0),
            "quality_score": state.get("evidence_score", 0.0),
            "quality_decision": state.get("quality_decision", ""),
            "missing_information": state.get("missing_information", []),
            "evidence": state.get("evidence", []),
            "findings": state.get("verified_findings", []),
            "insights": state.get("insights", []),
        },
    )

    report_path = base / "reports" / f"{run_id}.md"
    report_path.write_text(state.get("report", ""), encoding="utf-8")

    return {
        "raw": str(raw_path),
        "evidence": str(evidence_path),
        "report": str(report_path),
    }


def list_reports() -> List[Path]:
    reports = research_dir() / "reports"

    return sorted(
        reports.rglob("*.md"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )


# ------------------------------------------------------------------
# Manual notes (the part of the brief that cannot be automated)
# ------------------------------------------------------------------

def _notes_path(subject: str) -> Path:
    return research_dir() / "manual" / f"{slugify(subject)}.jsonl"


def add_manual_note(
    subject: str,
    text: str,
    platform: str = "",
    source_url: str = "",
    tag: str = "",
) -> Path:
    """
    Save one note about a venue / platform.

    Typical use: you read a Google review or an Instagram caption in your
    browser and paste it here. The agent treats it as evidence (high
    confidence, clearly marked as 'your note').
    """

    text = (text or "").strip()

    if not text:
        raise ValueError("Note text cannot be empty.")

    path = _notes_path(subject)

    entry = {
        "subject": subject,
        "text": text,
        "platform": platform.strip(),
        "source_url": source_url.strip(),
        "tag": tag.strip(),
        "added_at": datetime.now().isoformat(timespec="seconds"),
    }

    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")

    return path


def import_notes_file(
    subject: str,
    file_path: str,
    platform: str = "",
    source_url: str = "",
) -> int:
    """
    Import a text file. Notes are separated by a blank line, so you can
    paste a whole batch of Google reviews at once.
    """

    raw = Path(file_path).expanduser().read_text(encoding="utf-8")

    blocks = [block.strip() for block in re.split(r"\n\s*\n", raw) if block.strip()]

    for block in blocks:
        add_manual_note(subject, block, platform=platform, source_url=source_url)

    return len(blocks)


def load_manual_evidence(subject: str) -> List[Dict[str, Any]]:
    path = _notes_path(subject)

    if not path.exists():
        return []

    notes = []

    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()

        if not line:
            continue

        try:
            notes.append(json.loads(line))
        except json.JSONDecodeError:
            continue

    return notes


def list_manual_subjects() -> List[Dict[str, Any]]:
    """Every subject you have pasted notes for, with how many."""

    folder = research_dir() / "manual"

    subjects = []

    for path in sorted(folder.glob("*.jsonl")):
        notes = []

        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                notes.append(json.loads(line))
            except json.JSONDecodeError:
                continue

        if notes:
            subjects.append(
                {
                    "subject": notes[0].get("subject", path.stem),
                    "count": len(notes),
                    "last_added": notes[-1].get("added_at", ""),
                }
            )

    return subjects


# ------------------------------------------------------------------
# Property profiles (cache, so a brief can be resumed / re-rendered)
# ------------------------------------------------------------------

def profile_path(name: str, kind: str = "properties") -> Path:
    return research_dir() / kind / f"{slugify(name)}.json"


def save_profile(
    name: str, profile: Dict[str, Any], kind: str = "properties"
) -> Path:
    return write_json(profile_path(name, kind), profile)


def load_profile(name: str, kind: str = "properties") -> Dict[str, Any] | None:
    path = profile_path(name, kind)

    return read_json(path) if path.exists() else None


def list_profiles(kind: str = "properties") -> List[Dict[str, Any]]:
    folder = research_dir() / kind

    profiles = []

    for path in sorted(folder.glob("*.json")):
        try:
            profiles.append(read_json(path))
        except Exception:
            continue

    return profiles
