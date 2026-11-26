"""
Command line entry point.

    python -m app.main check
    python -m app.main ask "What do guests complain about at hostels in Goa?"
    python -m app.main property "Zostel Old Manali" --place Manali --type hostel
    python -m app.main note "Zostel Old Manali" "pasted Google review..." --platform "Google Maps"
    python -m app.main ui                                 # the point-and-click interface
    python -m app.main discover "Manali"                  # find properties worth studying
    python -m app.main study "Goa" --stays 4 --cafes 3    # discover + research + one report
    python -m app.main brief vibers --place Manali        # the full Vibers brief
    python -m app.main compare
    python -m app.main list

Run `python -m app.main <command> -h` for the options of each command.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import List, Optional

from app.config import PROJECT_ROOT, get_settings


def _require_llm() -> bool:
    from app.llm.provider import llm_health

    ok, message = llm_health()

    print(("✅ " if ok else "❌ ") + message)

    return ok


def _show_saved(paths: dict) -> None:
    print("\nSaved:")

    for label, path in paths.items():
        print(f"  {label:9s} {path}")


# ------------------------------------------------------------------
# Commands
# ------------------------------------------------------------------

def cmd_check(args) -> int:
    from app.storage import research_dir

    settings = get_settings()

    ok = _require_llm()

    print(f"   Output folder : {research_dir()}")
    print(f"   Read web pages: {'yes' if settings.fetch_pages else 'no (FETCH_PAGES=false)'}")

    try:
        from app.tools.web_search import search_web

        results = search_web("Manali hostel reviews", max_results=2)
        print(f"✅ Web search works ({len(results)} results)")
    except Exception as exc:
        print(f"❌ Web search failed: {exc}")
        ok = False

    return 0 if ok else 2


def cmd_ask(args) -> int:
    if not _require_llm():
        return 2

    from app.runner import iterations_for, run_research
    from app.schemas.research import ResearchQuestion
    from app.storage import load_manual_evidence

    depth = args.depth
    iterations = args.iterations or iterations_for(depth)

    question = ResearchQuestion(
        question=args.question,
        depth=depth,
        max_iterations=iterations,
    )

    result = run_research(
        question,
        manual_evidence=load_manual_evidence(args.notes) if args.notes else [],
    )

    print("\n" + result["state"].get("report", ""))
    _show_saved(result["paths"])

    return 0


def cmd_property(args) -> int:
    if not _require_llm():
        return 2

    from app.workflows.profiles import PropertySpec, profile_property, render_property_section

    spec = PropertySpec(
        name=args.name,
        place=args.place,
        type=args.type,
        website=args.website or "",
        instagram=args.instagram or "",
    )

    profile = profile_property(spec, depth=args.depth, refresh=args.refresh)

    print("\n" + render_property_section(profile))

    if profile.get("report_path"):
        print(f"Full report: {profile['report_path']}")

    return 0


def cmd_note(args) -> int:
    from app.storage import add_manual_note, import_notes_file

    if args.file:
        count = import_notes_file(
            args.subject, args.file, platform=args.platform, source_url=args.url
        )
        print(f"Imported {count} note(s) for '{args.subject}'.")

    elif args.text:
        add_manual_note(
            args.subject,
            args.text,
            platform=args.platform,
            source_url=args.url,
            tag=args.tag,
        )
        print(f"Saved note for '{args.subject}'.")

    else:
        print("Give the note text, or --file notes.txt (notes separated by a blank line).")
        return 1

    print("Re-run the property / brief to include it (it is picked up automatically).")

    return 0


def cmd_ui(args) -> int:
    from app.ui.server import serve

    return serve(port=args.port, open_browser=not args.no_browser)


def _discovery_options(args) -> dict:
    return dict(
        stays=args.stays,
        cafes=args.cafes,
        rediscover=args.rediscover,
        allow_thin=args.allow_thin,
        min_reviews=args.min_reviews,
        min_sites=args.min_sources,
    )


def cmd_discover(args) -> int:
    from app.workflows.discovery import (
        discover,
        render_selection_markdown,
        save_selection,
        write_discovery_report,
    )

    selection = discover(
        args.place,
        stays=args.stays,
        cafes=args.cafes,
        min_sites=args.min_sources,
        min_reviews=args.min_reviews,
        allow_thin=args.allow_thin,
    )

    path = save_selection(selection)

    text = render_selection_markdown(selection)

    print("\n" + text)

    report = write_discovery_report(selection)

    _show_saved({"selection": str(path), "report": str(report)})

    chosen = sum(len(selection[k]["selected"]) for k in ("stays", "cafes"))

    if not chosen:
        print("\nNothing cleared the evidence bar. See the notes above.")
        return 1

    print("\nNext: `python -m app.main study \"%s\"` researches these properties." % args.place)

    return 0


def cmd_study(args) -> int:
    if not _require_llm():
        return 2

    from app.workflows.study import run_study

    try:
        written = run_study(args.place, depth=args.depth, refresh=args.refresh, **_discovery_options(args))
    except ValueError as exc:
        print(str(exc))
        return 1

    _show_saved(written)

    return 0


def cmd_brief(args) -> int:
    from app.workflows.vibers_brief import run_brief

    if args.name != "vibers":
        print("Only the 'vibers' brief exists so far.")
        return 1

    properties = None

    if args.properties:
        properties = Path(args.properties).expanduser()

        if not properties.exists():
            print(f"Properties file not found: {properties}")
            return 1

    if not args.render_only and not _require_llm():
        return 2

    try:
        written = run_brief(
            properties,
            place=args.place,
            part=args.part,
            depth=args.depth,
            refresh=args.refresh,
            render_only=args.render_only,
            use_llm=not args.no_llm,
            **_discovery_options(args),
        )
    except ValueError as exc:
        print(str(exc))
        return 1

    _show_saved(written)

    return 0


def cmd_compare(args) -> int:
    from app.storage import list_profiles, research_dir
    from app.workflows.profiles import top_problems

    profiles = list_profiles()

    if not profiles:
        print("No property profiles saved yet. Run `property` or `brief` first.")
        return 1

    problems = top_problems(profiles, limit=args.top, min_sources=args.min_sources)

    lines = [f"# Most common problems across {len(profiles)} properties", ""]

    for rank, problem in enumerate(problems, start=1):
        lines.append(
            f"{rank}. **{problem['theme']}** - {problem['property_count']} properties, "
            f"{problem['source_count']} sources: {', '.join(problem['properties'])}"
        )

    if not problems:
        lines.append("No problem repeated across enough sources yet.")

    text = "\n".join(lines) + "\n"

    out = research_dir() / "reports" / "problems_across_properties.md"
    out.write_text(text, encoding="utf-8")

    print(text)
    print(f"Saved: {out}")

    return 0


def cmd_list(args) -> int:
    from app.storage import list_reports

    reports = list_reports()

    if not reports:
        print("No reports yet.")
        return 0

    base = get_settings().research_dir

    for path in reports[: args.limit]:
        try:
            print(path.relative_to(base))
        except ValueError:
            print(path)

    return 0


# ------------------------------------------------------------------
# Parser
# ------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.main",
        description="Personal research agent for hotels, hostels and cafés.",
    )

    parser.add_argument(
        "--no-fetch",
        action="store_true",
        help="Do not download web pages; use search snippets only (faster).",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    depth_kwargs = dict(
        choices=["quick", "standard", "deep"],
        default="standard",
        help="quick = 1 search round, standard = 2, deep = 3 (default: standard)",
    )

    def discovery_flags(p, place_default=None):
        if place_default is None:
            p.add_argument("place", help='Town or area, e.g. "Manali" or "Goa".')
        else:
            p.add_argument("--place", default=place_default, help="Town or area to find properties in.")

        p.add_argument("--stays", type=int, default=3, help="How many hotels/hostels (default 3).")
        p.add_argument("--cafes", type=int, default=2, help="How many cafes (default 2).")
        p.add_argument("--min-reviews", type=int, default=50, help="Reviews that must be visible (default 50).")
        p.add_argument("--min-sources", type=int, default=3, help="Independent sites that must mention it (default 3).")
        p.add_argument("--allow-thin", action="store_true", help="Fill empty slots with weaker candidates (flagged).")
        p.add_argument("--rediscover", action="store_true", help="Search again instead of reusing the saved selection.")

    sub.add_parser("check", help="Check Ollama, web search and output folder.").set_defaults(func=cmd_check)

    p = sub.add_parser("ui", help="Open the point-and-click interface in your browser.")
    p.add_argument("--port", type=int, default=8765, help="Port to listen on (default 8765).")
    p.add_argument("--no-browser", action="store_true", help="Don't open the browser automatically.")
    p.set_defaults(func=cmd_ui)

    p = sub.add_parser("discover", help="Find the properties in a place that have enough reviews/history to study.")
    discovery_flags(p)
    p.set_defaults(func=cmd_discover)

    p = sub.add_parser("study", help="Discover properties in a place, research them, write one report.")
    discovery_flags(p)
    p.add_argument("--depth", **depth_kwargs)
    p.add_argument("--refresh", action="store_true", help="Redo property research even if saved.")
    p.set_defaults(func=cmd_study)

    p = sub.add_parser("ask", help="Research any question.")
    p.add_argument("question")
    p.add_argument("--depth", **depth_kwargs)
    p.add_argument("--iterations", type=int, help="Override the number of search rounds.")
    p.add_argument("--notes", help="Name of a notes file to include (see `note`).")
    p.set_defaults(func=cmd_ask)

    p = sub.add_parser("property", help="Profile one hotel / hostel / café.")
    p.add_argument("name")
    p.add_argument("--place", default="Manali")
    p.add_argument("--type", default="hostel", help="hostel | hotel | cafe | restaurant ...")
    p.add_argument("--website", help="Official website URL (read first, tagged 'official').")
    p.add_argument("--instagram", help="Instagram URL (kept for reference).")
    p.add_argument("--depth", **depth_kwargs)
    p.add_argument("--refresh", action="store_true", help="Ignore the saved profile.")
    p.set_defaults(func=cmd_property)

    p = sub.add_parser(
        "note",
        help="Add text you read yourself (Google review, Instagram caption ...).",
    )
    p.add_argument("subject", help="Property or platform name the note is about.")
    p.add_argument("text", nargs="?", help="The note text.")
    p.add_argument("--file", help="Text file; notes separated by a blank line.")
    p.add_argument("--platform", default="", help='e.g. "Google Maps", "Instagram"')
    p.add_argument("--url", default="", help="Where you read it.")
    p.add_argument("--tag", default="", help="Optional: complaint / praise / offer ...")
    p.set_defaults(func=cmd_note)

    p = sub.add_parser("brief", help="Run a full research brief and write the documents.")
    p.add_argument("name", choices=["vibers"])
    p.add_argument(
        "--properties",
        help="Optional: your own properties file. Normally NOT needed - properties are discovered.",
    )
    discovery_flags(p, place_default="Manali")
    p.add_argument("--part", choices=["1", "2", "both"], default="both")
    p.add_argument("--depth", **depth_kwargs)
    p.add_argument("--refresh", action="store_true", help="Redo research even if saved.")
    p.add_argument("--render-only", action="store_true", help="Rebuild the documents from saved research; no searching.")
    p.add_argument("--no-llm", action="store_true", help="Leave the idea drafts as blanks for you to write.")
    p.set_defaults(func=cmd_brief)

    p = sub.add_parser("compare", help="Rank the most common problems across saved property profiles.")
    p.add_argument("--top", type=int, default=5)
    p.add_argument("--min-sources", type=int, default=2)
    p.set_defaults(func=cmd_compare)

    p = sub.add_parser("list", help="List saved reports.")
    p.add_argument("--limit", type=int, default=20)
    p.set_defaults(func=cmd_list)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)

    if args.no_fetch:
        os.environ["FETCH_PAGES"] = "false"

    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("\nStopped. Anything already researched is saved under research/ and will be reused.")
        return 130


if __name__ == "__main__":
    sys.exit(main())
