"""
What the interface can start. Each action validates the form values first
(so mistakes are reported instantly), then runs the same workflow functions
the command line uses.

    prepare(kind, form_values) -> (job title, cleaned values, runner)
"""

from __future__ import annotations

import contextlib
import os
from pathlib import Path
from typing import Any, Callable, Dict, Tuple

from app.storage import research_dir, slugify

DEPTHS = ("quick", "standard", "deep")
PROPERTY_TYPES = ("hostel", "hotel", "homestay", "resort", "guesthouse", "lodge", "cafe", "restaurant")

BRIEF_LABELS = {
    "part1": "Part 1 - property research",
    "part2": "Part 2 - QC intelligence",
    "dashboard": "Dashboard wireframe",
    "selection": "How the properties were chosen",
}


# ------------------------------------------------------------------
# Form values
# ------------------------------------------------------------------

def _text(raw: Dict[str, Any], key: str, label: str, *, required: bool = True, limit: int = 120) -> str:
    value = " ".join(str(raw.get(key, "") or "").split())

    if required and not value:
        raise ValueError(f"Please enter {label}.")

    if len(value) > limit:
        raise ValueError(f"{label[0].upper() + label[1:]} is too long (max {limit} characters).")

    return value


def _number(raw: Dict[str, Any], key: str, default: int, lo: int, hi: int, label: str) -> int:
    value = raw.get(key, default)

    if value in ("", None):
        value = default

    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{label} must be a whole number.")

    if not lo <= number <= hi:
        raise ValueError(f"{label} must be between {lo} and {hi}.")

    return number


def _flag(raw: Dict[str, Any], key: str) -> bool:
    value = raw.get(key, False)

    return value is True or str(value).lower() in {"1", "true", "yes", "on"}


def _depth(raw: Dict[str, Any]) -> str:
    depth = str(raw.get("depth") or "standard")

    if depth not in DEPTHS:
        raise ValueError("Depth must be quick, standard or deep.")

    return depth


def _discovery_values(raw: Dict[str, Any]) -> Dict[str, Any]:
    stays = _number(raw, "stays", 3, 0, 10, "Hotels / hostels")
    cafes = _number(raw, "cafes", 2, 0, 10, "Cafes")

    if stays + cafes == 0:
        raise ValueError("Ask for at least one hotel, hostel or cafe.")

    return {
        "place": _text(raw, "place", "a place (for example Manali or Goa)", limit=80),
        "stays": stays,
        "cafes": cafes,
        "min_reviews": _number(raw, "min_reviews", 50, 0, 100000, "Minimum reviews"),
        "min_sites": _number(raw, "min_sources", 3, 1, 20, "Minimum sources"),
        "allow_thin": _flag(raw, "allow_thin"),
        "rediscover": _flag(raw, "rediscover"),
        "skip_fetch": _flag(raw, "skip_fetch"),
    }


# ------------------------------------------------------------------
# Helpers used by the runners
# ------------------------------------------------------------------

@contextlib.contextmanager
def _page_fetching(values: Dict[str, Any]):
    """'Skip page downloads' for the length of one job."""

    if not values.get("skip_fetch"):
        yield
        return

    previous = os.environ.get("FETCH_PAGES")
    os.environ["FETCH_PAGES"] = "false"

    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("FETCH_PAGES", None)
        else:
            os.environ["FETCH_PAGES"] = previous


def _need_llm() -> None:
    from app.llm import provider

    ok, message = provider.llm_health()

    print(("OK  " if ok else "!!  ") + message)

    if not ok:
        raise RuntimeError(
            message + " Start it with `ollama serve`, then try again. "
            "(Finding properties does not need it.)"
        )


def _document(label: str, path: str | Path) -> Dict[str, str]:
    base = research_dir().resolve()
    relative = Path(path).resolve().relative_to(base)

    return {"label": label, "path": relative.as_posix()}


def _discovery_args(values: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "stays": values["stays"],
        "cafes": values["cafes"],
        "min_sites": values["min_sites"],
        "min_reviews": values["min_reviews"],
        "allow_thin": values["allow_thin"],
    }


# ------------------------------------------------------------------
# Actions
# ------------------------------------------------------------------

def _discover(raw):
    values = _discovery_values(raw)

    def run(p):
        from app.workflows import discovery

        with _page_fetching(p):
            selection = discovery.discover(p["place"], **_discovery_args(p))

        discovery.save_selection(selection)
        report = discovery.write_discovery_report(selection)

        picked = sum(len(selection[k]["selected"]) for k in ("stays", "cafes"))

        print(f"\nDone: {picked} properties selected for {p['place']}.")

        return {
            "summary": f"{picked} properties selected in {p['place']}.",
            "place": p["place"],
            "documents": [_document("Which properties and why", report)],
        }

    return f"Find properties in {values['place']}", values, run


def _study(raw):
    values = _discovery_values(raw)
    values["depth"] = _depth(raw)
    values["refresh"] = _flag(raw, "refresh")

    def run(p):
        from app.workflows.study import run_study

        _need_llm()

        with _page_fetching(p):
            written = run_study(
                p["place"],
                depth=p["depth"],
                refresh=p["refresh"],
                rediscover=p["rediscover"],
                **_discovery_args(p),
            )

        print("\nDone.")

        return {
            "summary": f"Study of {p['place']} written.",
            "place": p["place"],
            "documents": [_document("Property study", written["study"])],
        }

    return f"Study properties in {values['place']}", values, run


def _brief(raw):
    values = _discovery_values(raw)
    values["depth"] = _depth(raw)
    values["refresh"] = _flag(raw, "refresh")
    values["no_llm"] = _flag(raw, "no_llm")

    part = str(raw.get("part") or "both")

    if part not in ("1", "2", "both"):
        raise ValueError("Part must be 1, 2 or both.")

    values["part"] = part

    def run(p):
        from app.workflows.vibers_brief import run_brief

        _need_llm()

        with _page_fetching(p):
            written = run_brief(
                None,
                place=p["place"],
                part=p["part"],
                depth=p["depth"],
                refresh=p["refresh"],
                rediscover=p["rediscover"],
                use_llm=not p["no_llm"],
                **_discovery_args(p),
            )

        print("\nDone.")

        return {
            "summary": f"Vibers brief for {p['place']} written.",
            "place": p["place"],
            "documents": [
                _document(BRIEF_LABELS.get(key, key), path)
                for key, path in written.items()
            ],
        }

    return f"Vibers brief - {values['place']}", values, run


def _property(raw):
    values = {
        "name": _text(raw, "name", "the property's name", limit=100),
        "place": _text(raw, "place", "a place (for example Manali or Goa)", limit=80),
        "type": str(raw.get("type") or "hostel"),
        "website": _text(raw, "website", "a website", required=False, limit=300),
        "depth": _depth(raw),
        "refresh": _flag(raw, "refresh"),
        "skip_fetch": _flag(raw, "skip_fetch"),
    }

    if values["type"] not in PROPERTY_TYPES:
        raise ValueError("Pick a property type from the list.")

    if values["website"] and not values["website"].lower().startswith(("http://", "https://")):
        raise ValueError("The website must start with http:// or https://")

    def run(p):
        from app.workflows.profiles import PropertySpec, profile_property, render_property_section

        _need_llm()

        spec = PropertySpec(name=p["name"], place=p["place"], type=p["type"], website=p["website"])

        with _page_fetching(p):
            profile = profile_property(spec, depth=p["depth"], refresh=p["refresh"])

        path = research_dir() / "reports" / f"property_{slugify(p['name'])}.md"
        path.write_text(
            f"# {p['name']}\n\n" + render_property_section(profile, heading_level=2),
            encoding="utf-8",
        )

        print("\nDone.")

        return {
            "summary": f"{p['name']} researched.",
            "documents": [_document("Property profile", path)],
        }

    return f"Research {values['name']} ({values['place']})", values, run


def _ask(raw):
    values = {
        "question": _text(raw, "question", "a question", limit=600),
        "depth": _depth(raw),
        "skip_fetch": _flag(raw, "skip_fetch"),
    }

    def run(p):
        from app.runner import iterations_for, run_research
        from app.schemas.research import ResearchQuestion

        _need_llm()

        question = ResearchQuestion(
            question=p["question"],
            depth=p["depth"],
            max_iterations=iterations_for(p["depth"]),
        )

        with _page_fetching(p):
            result = run_research(question)

        print("\nDone.")

        return {
            "summary": "Research finished.",
            "documents": [_document("Research report", result["paths"]["report"])],
        }

    return "Research: " + values["question"][:60], values, run


_KINDS: Dict[str, Callable[[Dict[str, Any]], Tuple[str, Dict[str, Any], Callable]]] = {
    "discover": _discover,
    "study": _study,
    "brief": _brief,
    "property": _property,
    "ask": _ask,
}


def prepare(kind: str, raw: Dict[str, Any]) -> Tuple[str, Dict[str, Any], Callable]:
    if kind not in _KINDS:
        raise ValueError(f"Unknown action: {kind}")

    return _KINDS[kind](raw if isinstance(raw, dict) else {})
