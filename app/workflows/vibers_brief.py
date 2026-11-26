"""
The Vibers Connect research brief, end to end.

Part 1  Customer & property research
        5 properties + booking-platform audit -> problems, ideas, opinion
        (the properties are DISCOVERED for a place by app/workflows/discovery.py -
        the ones with the most review material - unless you pass your own file)
Part 2  QC Intelligence Platform
        owner's morning information, PriceLabs / Lighthouse / Cloudbeds,
        three answers, dashboard design

Every section of the output carries one of three labels, because the brief
says "distinguish what you have actually researched from your own ideas":

    RESEARCHED   backed by a source link (a web page, or a note you pasted)
    IDEA         a hypothesis drafted from the research - NOT evidence
    YOUR VIEW    left blank on purpose; only you can write it
"""

from __future__ import annotations

import html
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.graph.report_builder import (
    channel_coverage,
    evidence_index,
    finding_sources,
    render_findings_markdown,
    source_link,
)
from app.llm.json_utils import parse_json
from app.llm.provider import generate_text
from app.storage import research_dir
from app.workflows.discovery import (
    get_selection,
    load_selection,
    profile_selection,
    render_selection_markdown,
    selected_specs,
)
from app.workflows.profiles import (
    PropertySpec,
    findings_in,
    load_specs,
    profile_property,
    profile_topic,
    render_property_section,
    render_topic_section,
    top_problems,
    verified,
)

# ------------------------------------------------------------------
# The ecosystem (from the brief) - used only to draft ideas
# ------------------------------------------------------------------

ECOSYSTEM = """\
1. QC2 (Quad Computing Connect) - helps hotels and cafes manage orders, bookings, billing, inventory and daily operations.
2. Vibers Connect - helps guests discover places, explore services, order through QR and earn 7% rewards in the venue's own wallet for future visits.
3. Vibers Point - physical identity and verification system for partner properties.
4. Vibers Club - community where travellers discover people, experiences and events around them."""

LABELS = """\
- **RESEARCHED** - backed by a source link (a web page, or a note you pasted in).
- **IDEA** - a hypothesis drafted from the research. Not evidence. Challenge it.
- **YOUR VIEW** - left for you to write; the agent cannot have a customer's opinion."""

# problem theme -> (Vibers part, how it could help). This is the ANALYST'S
# HYPOTHESIS, printed as IDEA - it is not research.
THEME_TO_VIBERS = {
    "Cleanliness & hygiene": ("Vibers Point + QC2", "verified cleanliness checks at check-in/out; housekeeping checklists staff must complete"),
    "Noise & disturbance": ("QC2 + Vibers Club", "quiet-hour rules visible before booking; event schedule so guests know what to expect"),
    "Staff behaviour & service": ("QC2", "response-time tracking and guest feedback loop owners actually see"),
    "Hot water, heating & bathrooms": ("Vibers Point", "amenities shown on Vibers Connect verified by both guest and property at every check-in and check-out"),
    "Food & café quality or price": ("QC2 + Vibers Connect", "QR ordering with live menu/prices and wallet rewards for repeat orders"),
    "Wi-Fi, power & connectivity": ("Vibers Point", "verified amenity claims (e.g. Wi-Fi works, power backup) instead of self-reported ones"),
    "Pricing, hidden charges & value": ("Vibers Connect + QC2", "one transparent total price and itemised bill from booking to checkout"),
    "Booking, cancellation & refunds": ("Vibers Connect + QC2", "single booking-status view and clear cancellation/refund state for guest and owner"),
    "Location, access & parking": ("Vibers Connect", "arrival guidance: how to reach, parking, last-mile directions inside the listing"),
    "Safety & security": ("Vibers Point", "verified identity of the property and its safety basics"),
    "Overcrowding, space & comfort": ("QC2", "capacity-aware bookings so a venue is not oversold"),
    "Photos & expectations mismatch": ("Vibers Point", "verified listings: what you see is what the property confirmed at inspection"),
}

PLATFORM_AUDIT = [
    {
        "key": "platform-zostel",
        "title": "Zostel (booking experience)",
        "question": "What do travellers find convenient, confusing or unnecessarily complicated when booking and staying through Zostel in India?",
        "queries": [
            "Zostel booking experience complaints",
            "Zostel app review booking cancellation refund",
            "Zostel booking hidden charges confusing",
            "site:reddit.com Zostel booking experience",
            "Zostel vs Hostelworld booking which is better",
        ],
    },
    {
        "key": "platform-makemytrip",
        "title": "MakeMyTrip (hotel booking)",
        "question": "What do travellers and hotel owners find convenient, confusing or unnecessarily complicated about MakeMyTrip hotel bookings in India?",
        "queries": [
            "MakeMyTrip hotel booking complaints hidden charges refund",
            "MakeMyTrip app hotel booking confusing review",
            "MakeMyTrip hotel partner commission complaints hoteliers",
            "site:reddit.com MakeMyTrip hotel booking experience",
            "MakeMyTrip vs Booking.com vs Airbnb India comparison",
        ],
    },
    {
        "key": "platform-airbnb",
        "title": "Airbnb (stays in India)",
        "question": "What do travellers and hosts find convenient, confusing or unnecessarily complicated about Airbnb in India?",
        "queries": [
            "Airbnb India booking cleaning fee service fee confusing complaints",
            "Airbnb India host problems commission cancellation",
            "Airbnb vs Booking.com convenience India travellers",
            "site:reddit.com Airbnb India booking experience",
            "Airbnb listing not as described India complaints",
        ],
    },
]

PLATFORM_ASPECTS = [
    "Something convenient about booking or using the platform",
    "Something confusing or unnecessarily complicated about booking, paying or cancelling",
    "Fees, hidden charges or pricing surprises",
    "What owners / hosts complain about",
]

TOOLS = [
    {
        "key": "tool-pricelabs",
        "title": "PriceLabs",
        "question": "What intelligence does PriceLabs give hotel and hostel owners, and what do small independent owners find missing or too complex?",
        "queries": [
            "PriceLabs features dynamic pricing hotels demand",
            "PriceLabs market dashboard competitor rates neighbourhood data",
            "PriceLabs review small hotel owners pros cons",
            "site:reddit.com PriceLabs hotel owners experience",
        ],
    },
    {
        "key": "tool-lighthouse",
        "title": "Lighthouse (formerly OTA Insight)",
        "question": "What intelligence does Lighthouse give hotels, and what do small independent owners find missing, too expensive or too complex?",
        "queries": [
            "Lighthouse hospitality market insight rate shopper features",
            "Lighthouse OTA Insight demand forecasting competitor rates hotels",
            "Lighthouse hotel intelligence pricing small independent hotels",
            "Lighthouse OTA Insight review hotel revenue managers pros cons",
        ],
    },
    {
        "key": "tool-cloudbeds",
        "title": "Cloudbeds",
        "question": "What intelligence and reports does Cloudbeds give hostels and small hotels, and what do owners find missing or complicated?",
        "queries": [
            "Cloudbeds features PMS channel manager revenue management reports",
            "Cloudbeds benchmarking competitor rates insights hostels",
            "Cloudbeds review small hostel owners pros cons",
            "site:reddit.com Cloudbeds hostel experience",
        ],
    },
]

TOOL_ASPECTS = [
    "A feature or kind of intelligence the tool provides",
    "Pricing or cost of the tool",
    "What owners say is missing, too complex or not suited to small properties",
]


def _areas(place: str) -> List[Dict[str, Any]]:
    """The seven intelligence questions from the brief. Areas 3, 6, 7 need no
    web research (customer intelligence = Part 1 profiles; performance =
    the owner's own data; decision = product design)."""

    return [
        {
            "n": 1,
            "key": "market-demand",
            "title": "Market demand",
            "question": f"Are more travellers visiting {place} this week? Is demand rising or falling?",
            "needs_web": True,
            "query_question": f"What public data exists on traveller demand and tourist footfall in {place}, and how often is it published?",
            "queries": [
                f"{place} tourist footfall statistics",
                f"{place} tourist arrivals trend this season",
                f"{place} hotel occupancy tourist rush weekend",
                f"Himachal Pradesh tourist arrivals data Kullu {place}",
            ],
            "shows": "Demand trend vs last week (up / down / flat), a 14-day outlook, and the next long weekends.",
            "why": "Tells the owner whether to hold or drop prices and how much staff / stock to line up.",
        },
        {
            "n": 2,
            "key": "competitor-intelligence",
            "title": "Competitor intelligence",
            "question": f"What are nearby properties charging, and what are they doing differently?",
            "needs_web": True,
            "query_question": f"How can a small property in {place} see what nearby hotels and hostels charge, and what offers do competitors run?",
            "queries": [
                f"{place} hostel price per night weekend vs weekday",
                f"{place} hotel rates compare nearby properties",
                f"{place} hostel offers discounts packages",
                "how hotels track competitor rates small property rate shopper",
            ],
            "shows": "Nearby rates for my room type (today / this weekend), who is sold out, and new offers rivals launched.",
            "why": "Pricing is the owner's biggest daily decision; today it means checking apps one by one.",
        },
        {
            "n": 3,
            "key": "customer-intelligence",
            "title": "Customer intelligence",
            "question": "What are guests complaining about at nearby hotels, and what experiences do they want?",
            "needs_web": False,
            "queries": [],
            "shows": "New reviews at nearby properties, this month's top complaint themes, and what guests keep asking for.",
            "why": "Lets the owner fix the same problems before they hit his own reviews and copy what guests love.",
        },
        {
            "n": 4,
            "key": "revenue-opportunities",
            "title": "Revenue opportunities",
            "question": "What additional services could the property offer to increase earnings?",
            "needs_web": True,
            "query_question": f"What extra services and add-on revenue do hostels and small hotels in {place} or similar mountain destinations offer?",
            "queries": [
                "hostel ancillary revenue ideas add-on services",
                f"{place} hostel activities rentals treks cafe workshops revenue",
                "small hotel upsell ideas guests pay for",
                "hostel events bonfire workshops revenue community",
            ],
            "shows": "Add-on services ranked by fit for this property (rentals, treks, café, workshops, events).",
            "why": "Turns empty beds and idle space into extra income without discounting.",
        },
        {
            "n": 5,
            "key": "local-intelligence",
            "title": "Local intelligence",
            "question": "Are there upcoming events, weather changes or tourist activities that may influence bookings?",
            "needs_web": True,
            "query_question": f"What events, festivals, weather conditions and road or pass status affect tourism and bookings in {place}?",
            "queries": [
                f"{place} upcoming events festivals",
                f"{place} weather forecast tourist season snowfall",
                f"{place} Rohtang Atal tunnel road status tourists",
                f"{place} tourism events calendar",
            ],
            "shows": "Events, weather and road/pass status for the next 14 days, each flagged as likely to raise or hurt bookings.",
            "why": "Lets the owner prepare for rushes and cancellations a week ahead instead of reacting.",
        },
        {
            "n": 6,
            "key": "business-performance",
            "title": "Business performance",
            "question": "What is working well, what isn't, and what should the owner improve?",
            "needs_web": False,
            "queries": [],
            "shows": "Occupancy, average rate, revenue and review score vs last week, plus the top complaint inside the property.",
            "why": "One honest scoreboard; the owner sees movement, not a spreadsheet.",
        },
        {
            "n": 7,
            "key": "decision-intelligence",
            "title": "Decision intelligence",
            "question": "Can the platform give simple recommendations instead of complicated reports?",
            "needs_web": False,
            "queries": [],
            "shows": "Three recommended actions for today, each with the reason behind it.",
            "why": "The reason an owner opens it every morning: it tells him what to do, not just what happened.",
        },
    ]


# ------------------------------------------------------------------
# LLM drafts (always labelled IDEA, with honest placeholders on failure)
# ------------------------------------------------------------------

def _bullets(items: List[str], limit: int = 12) -> str:
    return "\n".join(f"- {item}" for item in items[:limit]) or "- (none found)"


def draft_ideas(
    problems: List[Dict[str, Any]],
    platform_notes: List[str],
) -> List[Dict[str, str]]:
    """Three Vibers Connect ideas tied to researched problems."""

    problem_lines = [
        f"{p['theme']} (seen at {p['property_count']} properties, {p['source_count']} sources)"
        for p in problems
    ]

    prompt = f"""
You are a hospitality product strategist.

THE VIBERS ECOSYSTEM:
{ECOSYSTEM}

RESEARCHED CUSTOMER PROBLEMS:
{_bullets(problem_lines)}

RESEARCHED BOOKING-PLATFORM PAIN POINTS:
{_bullets(platform_notes)}

Propose exactly 3 ideas that would make Vibers Connect genuinely
different from Zostel, MakeMyTrip and Airbnb.

Rules:
- Each idea must solve one of the researched problems above.
- Each idea must use at least one part of the ecosystem.
- Do NOT invent statistics and do NOT claim anything is proven.
- Be concrete about what the guest or owner would actually see.

Return ONLY valid JSON:

{{"ideas": [{{"title": "", "problem_addressed": "", "how_it_works": "", "why_different": ""}}]}}
"""

    try:
        ideas = parse_json(generate_text(prompt)).get("ideas", [])

        clean = [
            {key: str(item.get(key, "")).strip() for key in
             ("title", "problem_addressed", "how_it_works", "why_different")}
            for item in ideas
            if isinstance(item, dict) and str(item.get("title", "")).strip()
        ][:3]
    except Exception as exc:
        print(f"IDEA DRAFT ERROR: {exc}")
        clean = []

    theme_keys = [p["theme"].split()[0].lower().rstrip(",") for p in problems]

    for idea in clean:
        addressed = idea["problem_addressed"].lower()

        idea["matched"] = (
            "yes" if any(key in addressed for key in theme_keys) else "no"
        )

    while len(clean) < 3:
        clean.append(_placeholder_ideas()[len(clean)])

    return clean


def draft_owner_answers(
    hard_to_find: List[str],
    tool_gaps: List[str],
) -> Dict[str, List[str]]:
    """Drafts for the three questions of Part 2."""

    prompt = f"""
You are a hospitality product strategist helping design an intelligence
dashboard for small hotel and hostel owners in India.

RESEARCHED: information that is hard for owners to get:
{_bullets(hard_to_find)}

RESEARCHED: gaps in existing tools (PriceLabs, Lighthouse, Cloudbeds):
{_bullets(tool_gaps)}

Answer, using only the research above plus plain reasoning
(no invented statistics):

1. hard_to_find: 3-5 pieces of information owners find difficult to get.
2. one_dashboard: 4-6 things one simple dashboard could show.
3. morning_hooks: 3 reasons an owner would open the platform every
   morning even if he does not use QC2 for billing.

Return ONLY valid JSON:
{{"hard_to_find": ["..."], "one_dashboard": ["..."], "morning_hooks": ["..."]}}
"""

    placeholder = {
        "hard_to_find": ["[Write what you think is hardest for owners to find]"],
        "one_dashboard": ["[Write what you would put on one screen]"],
        "morning_hooks": ["[Write what would make an owner open it daily]"],
    }

    try:
        parsed = parse_json(generate_text(prompt))

        result = {}

        for key in placeholder:
            items = [str(item).strip() for item in parsed.get(key, []) if str(item).strip()]
            result[key] = items[:6] or placeholder[key]

        return result
    except Exception as exc:
        print(f"ANSWER DRAFT ERROR: {exc}")
        return placeholder


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _stub_profile(spec: PropertySpec) -> Dict[str, Any]:
    return {
        "key": spec.name,
        "spec": spec.__dict__.copy(),
        "run_id": "not-run",
        "evidence": [],
        "findings": [],
        "insights": [],
        "missing_information": ["Not researched yet - run without --render-only."],
        "coverage": [],
    }


def _stub_topic(key: str, title: str) -> Dict[str, Any]:
    return {
        "key": key,
        "title": title,
        "run_id": "not-run",
        "evidence": [],
        "findings": [],
        "insights": [],
        "missing_information": ["Not researched yet."],
    }


def _cross_property(
    profiles: List[Dict[str, Any]], category: str
) -> str:
    """Findings of one category across all properties, grouped by property."""

    lines: List[str] = []

    for profile in profiles:
        items = findings_in(profile, category)

        if not items:
            continue

        name = profile.get("spec", {}).get("name", profile.get("key", ""))
        by_id = evidence_index(profile.get("evidence", []))

        lines.append(f"**{name}**")

        for finding in items:
            sources = " · ".join(finding_sources(finding, by_id)) or "*no source*"
            lines.append(f"- {finding['statement'].strip()} - {sources}")

        lines.append("")

    return "\n".join(lines).strip() or "*No verified finding in this category yet.*"


def _topic_findings(profile: Dict[str, Any], categories: Optional[List[str]] = None) -> List[str]:
    items = verified(profile)

    if categories:
        items = [f for f in items if f.get("category") in categories]

    return [f["statement"].strip() for f in items]


def _icons(profile: Dict[str, Any]) -> str:
    icons = {"full": "✅", "snippet": "⚠️", "none": "❌"}

    wanted = ("maps", "social", "official", "booking", "review")

    rows = {r["source_type"]: r for r in channel_coverage(profile.get("evidence", []))}

    return " ".join(icons[rows[key]["status"]] for key in wanted)


def _header(title: str, subtitle: str) -> List[str]:
    return [
        f"# {title}",
        "",
        f"*{subtitle}*  ",
        f"*Draft produced by the research agent on {datetime.now().strftime('%d %b %Y')}. "
        f"Read it critically before you share it.*",
        "",
        "## How this document is labelled",
        "",
        LABELS,
        "",
    ]


# ------------------------------------------------------------------
# PART 1
# ------------------------------------------------------------------

def run_part1(
    specs: List[PropertySpec],
    *,
    depth: str,
    refresh: bool,
    render_only: bool,
    log=print,
    refresh_properties: Optional[bool] = None,
) -> Dict[str, Any]:
    # Topics (platforms, tools, areas) follow `refresh`. Property profiles
    # follow `refresh_properties` when given: auto-discovery has already
    # refreshed them once and must not do it twice.
    property_refresh = refresh if refresh_properties is None else refresh_properties

    profiles = []

    for spec in specs:
        if render_only:
            from app.storage import load_profile

            profiles.append(load_profile(spec.name) or _stub_profile(spec))
        else:
            profiles.append(profile_property(spec, depth=depth, refresh=property_refresh, log=log))

    platforms = []

    for item in PLATFORM_AUDIT:
        if render_only:
            from app.storage import load_profile

            platforms.append(load_profile(item["key"], kind="topics") or _stub_topic(item["key"], item["title"]))
        else:
            platforms.append(
                profile_topic(
                    item["key"],
                    title=item["title"],
                    question=item["question"],
                    queries=item["queries"],
                    aspects=PLATFORM_ASPECTS,
                    depth=depth,
                    refresh=refresh,
                    log=log,
                )
            )

    return {"profiles": profiles, "platforms": platforms}


def render_part1(data: Dict[str, Any], *, use_llm: bool = True) -> str:
    profiles = data["profiles"]
    platforms = data["platforms"]

    problems = top_problems(profiles, limit=5, min_sources=2)

    platform_notes: List[str] = []

    for profile in platforms:
        platform_notes += _topic_findings(profile, ["BOOKING_UX", "PRICING", "COMPLAINT", "GAP"])

    lines = _header(
        "Vibers Connect - Customer & Property Research",
        "Part 1 of the research brief",
    )

    # ---- 1. properties ------------------------------------------------
    lines += [
        "## 1. The properties and what we observed",
        "",
    ]

    if data.get("selection"):
        lines += [render_selection_markdown(data["selection"], heading_level=3), ""]

    lines += [
        "Channel key (left to right): Google Maps · Instagram/Facebook · official website · "
        "booking platforms · review sites. ✅ full text read, ⚠️ search snippets only, ❌ nothing.",
        "",
        "| Property | Type | Channels | Verified findings |",
        "|---|---|---|---|",
    ]

    for profile in profiles:
        spec = profile.get("spec", {})
        lines.append(
            f"| {spec.get('name', profile.get('key'))} | {spec.get('type', '')} | "
            f"{_icons(profile)} | {len(verified(profile))} |"
        )

    lines.append("")

    for profile in profiles:
        lines.append(render_property_section(profile, heading_level=3))

    # ---- 2. problems --------------------------------------------------
    lines += [
        "## 2. The most common customer problems",
        "",
        "**OBSERVATION - counted by keyword matching across all passages** (negative wording + a "
        "problem keyword). A problem only counts as common if it appears in at least 2 different "
        "sources. Read the examples; the counting can misfire.",
        "",
    ]

    if problems:
        for rank, problem in enumerate(problems, start=1):
            lines.append(
                f"### {rank}. {problem['theme']}"
            )
            lines.append(
                f"Seen at **{problem['property_count']}** of {len(profiles)} properties "
                f"({', '.join(problem['properties'])}), in **{problem['source_count']}** sources, "
                f"**{problem['passages']}** passages."
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

        if len(problems) < 5:
            lines.append(
                f"*Only {len(problems)} recurring problem(s) were found with real support. "
                "The list is not padded to five - add Google review notes with the `note` "
                "command and re-run to strengthen it.*"
            )
            lines.append("")
    else:
        lines += [
            "*No problem was repeated across at least two sources yet.* Google reviews and "
            "Instagram comments are the best source for this and cannot be read automatically - "
            "paste them with `python -m app.main note \"<property>\" \"<review text>\" --platform \"Google Maps\"` "
            "and re-run.",
            "",
        ]

    # ---- 3. five questions -------------------------------------------
    lines += [
        "## 3. The five customer questions, across all properties",
        "",
        "### Q1. What do customers repeatedly complain about?",
        "",
        "See section 2 for the ranked problems. Verified complaint findings per property:",
        "",
        _cross_property(profiles, "COMPLAINT"),
        "",
        "### Q2. What makes customers choose these places over others?",
        "",
        _cross_property(profiles, "CHOICE_DRIVER"),
        "",
        "### Q3. What facilities or experiences do customers appreciate most?",
        "",
        _cross_property(profiles, "PRAISE"),
        "",
        "### Q4. How do these properties attract customers and encourage them to return?",
        "",
        _cross_property(profiles, "RETENTION"),
        "",
        "### Q5. What is missing?",
        "",
        _cross_property(profiles, "GAP"),
        "",
    ]

    # ---- 4. platforms -------------------------------------------------
    lines += [
        "## 4. Booking platforms - what feels convenient, confusing or unnecessarily complicated",
        "",
        "*RESEARCHED from the sources linked under each platform.*",
        "",
    ]

    for profile in platforms:
        lines.append(render_topic_section(profile, heading_level=3))

    # ---- 5. what Vibers could improve --------------------------------
    lines += [
        "## 5. What Vibers Connect could improve",
        "",
        "**IDEA** - the mapping below is the analyst's hypothesis, built from the four parts of the "
        "Vibers ecosystem in the brief. The problems on the left are researched; the right-hand "
        "column is not.",
        "",
        "| Researched problem | Vibers part | IDEA: how it could help |",
        "|---|---|---|",
    ]

    for problem in problems:
        part, how = THEME_TO_VIBERS.get(problem["theme"], ("-", "-"))
        lines.append(f"| {problem['theme']} | {part} | {how} |")

    if not problems:
        lines.append("| *(no recurring problem found yet)* | | |")

    lines.append("")

    # ---- 6. three ideas ----------------------------------------------
    ideas = draft_ideas(problems, platform_notes) if use_llm else _placeholder_ideas()

    lines += [
        "## 6. Three ideas that could make Vibers Connect genuinely different",
        "",
        "**IDEA - drafted from the researched problems above. Not evidence; rewrite them in your own words.**",
        "",
    ]

    for number, idea in enumerate(ideas, start=1):
        matched = idea.get("matched", "placeholder")

        problem_note = {
            "yes": "  *(matches a problem found in the research above)*",
            "no": "  *(⚠️ not tied to a problem found in the research - treat it as a pure idea)*",
            "placeholder": "",
        }[matched]

        lines += [
            f"### Idea {number}: {idea['title']}",
            "",
            f"- **Problem it targets:** {idea['problem_addressed']}{problem_note}",
            f"- **How it works (IDEA):** {idea['how_it_works']}",
            f"- **Why it is different (IDEA):** {idea['why_different']}",
            "",
        ]

    # ---- 7. opinion --------------------------------------------------
    lines += [
        "## 7. Your personal opinion as a customer",
        "",
        "**YOUR VIEW - write this yourself.** The agent has never stayed at a hostel, so it will not "
        "invent an opinion. Use the research above as your starting point:",
        "",
        "- Would you use Vibers Connect? Why, or why not?",
        "- Which one problem from section 2 annoys *you* most when you travel?",
        "- Would 7% back in the venue's own wallet change where you stay or eat? Be honest about "
        "whether you would actually return to the same place.",
        "- What would make you trust a venue's \"verified\" label (Vibers Point)?",
        "",
        "> *(your answer here)*",
        "",
    ]

    # ---- limits ------------------------------------------------------
    lines += [
        "## Method and limits",
        "",
        "- Web search is DuckDuckGo; pages are read when they allow it. **Google reviews and Instagram "
        "cannot be read automatically** (they need a login / JavaScript), so for those channels the "
        "agent only sees search-engine snippets. Pasting real reviews with the `note` command is the "
        "honest way to cover them.",
        "- Findings are produced by a small local model and then checked by a second model pass and a "
        "wording check against the cited evidence. They can still be wrong - open the links.",
        "- Evidence, findings and raw pages for every run are saved under `research/` so any claim can "
        "be traced back to its source.",
        "",
    ]

    return "\n".join(lines).strip() + "\n"


def _placeholder_ideas() -> List[Dict[str, str]]:
    return [
        {
            "title": f"[Idea {n} - write yours]",
            "problem_addressed": "[Which researched problem does it solve?]",
            "how_it_works": "[What does the guest / owner see?]",
            "why_different": "[Why is this not already on Zostel / MakeMyTrip / Airbnb?]",
            "matched": "placeholder",
        }
        for n in (1, 2, 3)
    ]


# ------------------------------------------------------------------
# PART 2
# ------------------------------------------------------------------

def run_part2(
    specs: List[PropertySpec],
    owner_names: List[str],
    place: str,
    *,
    depth: str,
    refresh: bool,
    render_only: bool,
    log=print,
    refresh_properties: Optional[bool] = None,
) -> Dict[str, Any]:
    from app.storage import load_profile

    property_refresh = refresh if refresh_properties is None else refresh_properties

    lookup = {spec.name.lower(): spec for spec in specs}

    chosen = [lookup[name.lower()] for name in owner_names if name.lower() in lookup]

    if len(chosen) < 3:
        extra = [
            spec for spec in specs
            if spec.is_lodging and spec not in chosen
        ]
        chosen += extra[: 3 - len(chosen)]

    chosen = chosen[:3]

    owner_profiles = []

    for spec in chosen:
        if render_only:
            owner_profiles.append(load_profile(spec.name) or _stub_profile(spec))
        else:
            owner_profiles.append(profile_property(spec, depth=depth, refresh=property_refresh, log=log))

    tools = []

    for item in TOOLS:
        if render_only:
            tools.append(load_profile(item["key"], kind="topics") or _stub_topic(item["key"], item["title"]))
        else:
            tools.append(
                profile_topic(
                    item["key"],
                    title=item["title"],
                    question=item["question"],
                    queries=item["queries"],
                    aspects=TOOL_ASPECTS,
                    depth=depth,
                    refresh=refresh,
                    log=log,
                )
            )

    areas = []

    for area in _areas(place):
        if area["needs_web"]:
            key = f"area-{area['key']}"

            if render_only:
                topic = load_profile(key, kind="topics") or _stub_topic(key, area["title"])
            else:
                topic = profile_topic(
                    key,
                    title=f"{area['title']} - {place}",
                    question=area["query_question"],
                    queries=area["queries"],
                    aspects=[
                        "What data or signals exist and how an owner can get them",
                        "A trend, event, price or fact relevant to the owner's decision",
                        "What is hard to find or missing",
                    ],
                    depth=depth,
                    refresh=refresh,
                    log=log,
                )
        else:
            topic = None

        areas.append({**area, "topic": topic})

    return {
        "place": place,
        "owner_profiles": owner_profiles,
        "tools": tools,
        "areas": areas,
    }


def _owner_morning_questions(profile: Dict[str, Any]) -> List[str]:
    """Questions this owner would need answered each morning, derived from
    the property's own verified findings."""

    lines = []

    for finding in verified(profile):
        category = finding.get("category")
        statement = finding["statement"].strip()

        if category == "COMPLAINT":
            lines.append(f"Is this still happening, and are nearby properties hit by it too? → “{statement}”")
        elif category == "PRICING":
            lines.append(f"Is my price still right versus nearby properties? → “{statement}”")
        elif category == "GAP":
            lines.append(f"Could I fill this gap before a rival does? → “{statement}”")
        elif category == "RETENTION":
            lines.append(f"Is this tactic still bringing guests back? → “{statement}”")

    return lines[:6]


def render_part2(data: Dict[str, Any], part1: Optional[Dict[str, Any]], *, use_llm: bool = True) -> str:
    place = data["place"]

    lines = _header(
        "QC Intelligence Platform - What an Owner Needs Every Morning",
        f"Part 2 of the research brief · market: {place}",
    )

    # ---- 1. three owners ---------------------------------------------
    lines += [
        "## 1. Three properties, seen as their owner",
        "",
        "*Imagine you own each of these. The facts come from the property's own research profile "
        "(RESEARCHED); the morning questions are derived from those findings (IDEA).*",
        "",
    ]

    for profile in data["owner_profiles"]:
        spec = profile.get("spec", {})
        lines += [
            f"### If I owned {spec.get('name', profile.get('key'))}",
            "",
            f"*{spec.get('type', '').title()} · {spec.get('place', place)}*",
            "",
        ]

        body = render_findings_markdown(
            verified(profile), profile.get("evidence", []), heading_level=4
        )

        lines.append(body or "*No verified findings for this property yet (see Part 1 for raw evidence).*")
        lines.append("")

        questions = _owner_morning_questions(profile)

        lines.append("**IDEA - what I would want to know every morning because of this:**")
        lines.append("")
        lines += [f"- {q}" for q in questions] or ["- *(no findings to derive questions from yet)*"]
        lines.append("")

    # ---- 2. tools ----------------------------------------------------
    lines += [
        "## 2. What hospitality businesses already have",
        "",
        "*RESEARCHED from vendor pages, reviews and forums - links under each finding.*",
        "",
    ]

    for profile in data["tools"]:
        lines.append(render_topic_section(profile, heading_level=3))

    # ---- 3. seven areas ----------------------------------------------
    lines += [
        "## 3. The seven intelligence areas - what is actually knowable",
        "",
        "Each area is one of the brief's seven questions. Areas 3, 6 and 7 need no web research: "
        "customer intelligence is Part 1, performance is the owner's own data, and decision "
        "intelligence is product design.",
        "",
    ]

    for area in data["areas"]:
        lines.append(f"### {area['n']}. {area['title']}")
        lines.append("")
        lines.append(f"**Brief question:** {area['question']}")
        lines.append("")

        if area["topic"] is not None:
            lines.append("**RESEARCHED:**")
            lines.append("")
            lines.append(
                render_findings_markdown(
                    verified(area["topic"]), area["topic"].get("evidence", []), heading_level=4
                )
                or "*No verified findings yet - see raw evidence in research/evidence/.*"
            )
        elif area["key"] == "customer-intelligence":
            lines.append("**RESEARCHED in Part 1** - complaint and praise findings per property.")
        else:
            lines.append("*No outside research needed - this is the owner's own data / product design.*")

        lines.append("")

    # ---- 4. three answers --------------------------------------------
    hard_to_find: List[str] = []

    for area in data["areas"]:
        if area["topic"] is not None:
            hard_to_find += _topic_findings(area["topic"], ["GAP", "TREND", "FACT", "FEATURE"])

    tool_gaps: List[str] = []

    for profile in data["tools"]:
        tool_gaps += _topic_findings(profile, ["GAP", "PRICING", "COMPLAINT"])

    answers = (
        draft_owner_answers(hard_to_find, tool_gaps)
        if use_llm
        else _placeholder_answers()
    )

    lines += [
        "## 4. The three questions",
        "",
        "**IDEA - drafted from the research above; rewrite in your own words.**",
        "",
        "### What information is difficult for hotel owners to find?",
        "",
        *[f"- {item}" for item in answers["hard_to_find"]],
        "",
        "### What could our intelligence platform show them in one simple dashboard?",
        "",
        *[f"- {item}" for item in answers["one_dashboard"]],
        "",
        "See section 5 and the wireframe for the full layout.",
        "",
        "### What would make an owner open it every morning, even without using QC2 for billing?",
        "",
        *[f"- {item}" for item in answers["morning_hooks"]],
        "",
    ]

    # ---- 5. dashboard -------------------------------------------------
    lines += [
        "## 5. The owner's morning dashboard (design)",
        "",
        "A wireframe is saved next to this document (`part2_dashboard_wireframe.html`). It has no "
        "real numbers - it shows *what information sits where, and why*. Screenshot it into Canva "
        "if you want to restyle it.",
        "",
        "| # | Panel | Answers the brief question | What it shows (IDEA) | Why the owner cares (IDEA) | Research behind it |",
        "|---|---|---|---|---|---|",
    ]

    for area in data["areas"]:
        research = _research_label(area)
        lines.append(
            f"| {area['n']} | {area['title']} | {area['question']} | {area['shows']} | {area['why']} | {research} |"
        )

    lines += [
        "",
        "**Top of the screen - \"Today's 3 actions\":** the first thing an owner reads, built from the "
        "panels below. (IDEA)",
        "",
        "## Method and limits",
        "",
        "- Vendor and review pages are read when they allow it; some are blocked or JavaScript-only, "
        "in which case only search snippets were available.",
        "- Findings come from a small local model plus a verification pass; open the links before relying on one.",
        "- The dashboard layout, the three answers and every \"IDEA\" line are hypotheses to test with real owners.",
        "",
    ]

    return "\n".join(lines).strip() + "\n"


def _placeholder_answers() -> Dict[str, List[str]]:
    return {
        "hard_to_find": ["[Write what you think is hardest for owners to find]"],
        "one_dashboard": ["[Write what you would put on one screen]"],
        "morning_hooks": ["[Write what would make an owner open it daily]"],
    }


def _research_label(area: Dict[str, Any]) -> str:
    topic = area.get("topic")

    if topic is None:
        if area["key"] == "customer-intelligence":
            return "Part 1 findings"

        return "none (owner's own data / product design)"

    count = len(verified(topic))

    return f"{count} verified finding(s)" if count else "no verified finding yet"


# ------------------------------------------------------------------
# Dashboard wireframe (static HTML, no numbers)
# ------------------------------------------------------------------

def render_dashboard_html(data: Dict[str, Any]) -> str:
    place = html.escape(data["place"])

    cards = []

    ordered = sorted(data["areas"], key=lambda a: {7: 0}.get(a["n"], a["n"]))

    for area in ordered:
        label = _research_label(area)
        research = html.escape(label)
        research_class = "none" if label.startswith(("none", "no verified")) else "research"

        title = (
            "Today's 3 actions - decision intelligence"
            if area["n"] == 7
            else area["title"]
        )

        cards.append(
            f"""
      <section class="card{' wide' if area['n'] == 7 else ''}">
        <header>
          <span class="num">{area['n']}</span>
          <h2>{html.escape(title)}</h2>
        </header>
        <p class="q">{html.escape(area['question'])}</p>
        <div class="viz"><span>▲ ▼ ▬</span><i></i><i></i><i></i></div>
        <p><b>Shows:</b> {html.escape(area['shows'])}</p>
        <p><b>Why:</b> {html.escape(area['why'])}</p>
        <footer><span class="tag idea">IDEA</span><span class="tag {research_class}">{research}</span></footer>
      </section>"""
        )

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Owner's morning dashboard - wireframe</title>
<style>
  :root {{ --ink:#1f2933; --muted:#667085; --line:#d9dee5; --bg:#f6f7f9; --card:#fff; --accent:#2b6cb0; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; font:15px/1.5 system-ui,-apple-system,Segoe UI,sans-serif; color:var(--ink); background:var(--bg); }}
  main {{ max-width:1100px; margin:0 auto; padding:28px 20px 48px; }}
  h1 {{ font-size:22px; margin:0 0 4px; }}
  .sub {{ color:var(--muted); margin:0 0 22px; }}
  .note {{ background:#fff8e6; border:1px solid #f0d58c; padding:10px 14px; border-radius:8px; margin-bottom:20px; font-size:14px; }}
  .grid {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(310px,1fr)); gap:16px; }}
  .card {{ background:var(--card); border:1px solid var(--line); border-radius:12px; padding:16px; }}
  .card.wide {{ grid-column:1 / -1; border-color:var(--accent); }}
  .card header {{ display:flex; align-items:center; gap:10px; }}
  .card h2 {{ font-size:16px; margin:0; }}
  .num {{ background:var(--ink); color:#fff; width:24px; height:24px; border-radius:50%; display:grid; place-items:center; font-size:12px; }}
  .q {{ color:var(--muted); font-style:italic; margin:8px 0; }}
  .viz {{ height:64px; background:repeating-linear-gradient(90deg,#eef1f5 0 40px,#f8f9fb 40px 80px); border-radius:8px; margin:10px 0; display:flex; align-items:center; gap:10px; padding:0 12px; color:var(--muted); }}
  .viz i {{ flex:1; height:10px; background:#cfd6df; border-radius:5px; }}
  p {{ margin:6px 0; }}
  footer {{ display:flex; gap:8px; flex-wrap:wrap; margin-top:10px; }}
  .tag {{ font-size:11px; padding:2px 8px; border-radius:99px; border:1px solid var(--line); }}
  .tag.idea {{ background:#eef4ff; border-color:#c3d5f5; }}
  .tag.research {{ background:#eefbf2; border-color:#b8e3c5; }}
  .tag.none {{ background:#f3f4f6; color:var(--muted); }}
</style>
</head>
<body>
<main>
  <h1>Owner's morning dashboard - {place}</h1>
  <p class="sub">Wireframe: what information sits where, and why. Illustrative only - no real data or numbers.</p>
  <div class="note"><b>IDEA</b> = design hypothesis, not evidence. The research tag shows how many verified
  findings back that panel's data (see the research document).</div>
  <div class="grid">{''.join(cards)}
  </div>
</main>
</body>
</html>
"""


# ------------------------------------------------------------------
# Orchestration
# ------------------------------------------------------------------

def run_brief(
    properties_file: str | Path | None = None,
    *,
    place: str = "Manali",
    stays: int = 3,
    cafes: int = 2,
    rediscover: bool = False,
    allow_thin: bool = False,
    min_reviews: int = 50,
    min_sites: int = 3,
    part: str = "both",
    depth: str = "standard",
    refresh: bool = False,
    render_only: bool = False,
    use_llm: bool = True,
    log=print,
) -> Dict[str, str]:
    """
    Run the Vibers brief and write the documents to research/reports/vibers/.

    Properties:
      * normally DISCOVERED for `place` (the ones with the most review material);
        the choice is saved, so re-runs study the same properties
      * or read from `properties_file` if you give one (manual override)

    Returns the paths written.
    """

    selection = None

    if properties_file:
        config = load_specs(properties_file)

        specs: List[PropertySpec] = config["properties"]
        owner_names: List[str] = config["owner_properties"]
        place = config["place"]

    else:
        if render_only:
            selection = load_selection(place)

            if selection is None:
                raise ValueError(
                    f"No saved property selection for {place}. Run without --render-only first."
                )

            specs = selected_specs(selection)

        else:
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

        owner_names = [spec.name for spec in specs if spec.is_lodging][:3]

        if not specs:
            raise ValueError(
                f"No property in {place} cleared the evidence bar. Try --allow-thin, lower "
                "--min-reviews / --min-sources, or pass your own list with --properties."
            )

    out_dir = research_dir() / "reports" / "vibers"
    out_dir.mkdir(parents=True, exist_ok=True)

    written: Dict[str, str] = {}

    if selection is not None:
        selection_path = out_dir / "property_selection.md"
        selection_path.write_text(
            "# Which properties were studied, and why\n\n"
            + render_selection_markdown(selection, heading_level=2),
            encoding="utf-8",
        )
        written["selection"] = str(selection_path)

    part1 = None

    if part in ("1", "both"):
        part1 = run_part1(
            specs,
            depth=depth,
            refresh=refresh,
            render_only=render_only,
            log=log,
            refresh_properties=refresh if properties_file else False,
        )
        part1["selection"] = selection

        path = out_dir / "part1_property_research.md"
        path.write_text(render_part1(part1, use_llm=use_llm), encoding="utf-8")
        written["part1"] = str(path)

    if part in ("2", "both"):
        part2 = run_part2(
            specs,
            owner_names,
            place,
            depth=depth,
            refresh=refresh,
            render_only=render_only,
            log=log,
            refresh_properties=refresh if properties_file else False,
        )

        path = out_dir / "part2_qc_intelligence.md"
        path.write_text(render_part2(part2, part1, use_llm=use_llm), encoding="utf-8")
        written["part2"] = str(path)

        html_path = out_dir / "part2_dashboard_wireframe.html"
        html_path.write_text(render_dashboard_html(part2), encoding="utf-8")
        written["dashboard"] = str(html_path)

    return written
