from typing import Any, Dict, List

from app.graph.state import ResearchState

from app.schemas.research import (
    ResearchQuery,
    ResearchPlan,
)

from app.tools.web_search import search_web

def research_node(state: ResearchState) -> ResearchState:
    return research(state)
# ============================================================
# RESEARCH PLANNER
# ============================================================

def research_planner(state: ResearchState) -> Dict[str, Any]:
    """
    Convert the user's research question into a structured
    research plan.
    """

    question = state.get("question")

    if not question:
        raise ValueError("Research question cannot be empty.")

    # ResearchQuestion is a Pydantic object.
    # Get the actual text from .question
    question_text = question.question.strip()

    if question_text.lower().startswith("research "):
        question_text = question_text[9:].strip()

    if not question_text:
        raise ValueError("Research question cannot be empty.")

    # --------------------------------------------------------
    # Core research queries
    # --------------------------------------------------------

    queries = [
        ResearchQuery(
            query=question_text,
            purpose="Understand the topic and identify relevant sources",
            priority=5,
        ),

        ResearchQuery(
            query=f"{question_text} reviews complaints",
            purpose="Identify recurring complaints, negative experiences, and pain points",
            priority=5,
        ),

        ResearchQuery(
            query=f"{question_text} official website",
            purpose="Find official information about the topic",
            priority=4,
        ),

        ResearchQuery(
            query=f"{question_text} facilities experiences",
            purpose="Identify facilities, experiences, and customer-valued features",
            priority=4,
        ),

        ResearchQuery(
            query=f"{question_text} positive experiences",
            purpose="Identify positive experiences and appreciated features",
            priority=3,
        ),
    ]

    # --------------------------------------------------------
    # Research goals
    # --------------------------------------------------------

    research_goals = [
        "Identify the most important facts about the topic",
        "Identify recurring complaints and problems",
        "Identify positive experiences and appreciated features",
        "Compare information across independent sources",
        "Separate verified facts from observations and hypotheses",
    ]

    expected_output = (
        "Evidence-backed research findings with supporting sources, "
        "recurring patterns, contradictions, and actionable insights."
    )

    plan = ResearchPlan(
        queries=queries,
        research_goals=research_goals,
        expected_output=expected_output,
    )

    return {
        "research_plan": plan,
        "search_queries": [q.query for q in queries],
        "pending_queries": [q.query for q in queries],
        "iteration": state.get("iteration", 0),
        "max_iterations": question.max_iterations,
    }


# ============================================================
# WEB RESEARCH
# ============================================================

def research(state: ResearchState) -> Dict[str, Any]:

    pending_queries = state.get("pending_queries", [])

    if not pending_queries:
        return {
            "sources": state.get("sources", []),
            "evidence": state.get("evidence", []),
            "iteration": state.get("iteration", 0) + 1,
        }

    existing_sources = list(
        state.get("sources", [])
    )

    for query in pending_queries:

        try:
            results = search_web(query)

        except Exception as exc:

            existing_sources.append(
                {
                    "query": query,
                    "error": str(exc),
                    "results": [],
                }
            )

            continue

        if results is None:
            results = []

        if isinstance(results, dict):
            results = results.get(
                "results",
                [results],
            )

        for result in results:

            if isinstance(result, dict):

                source = {
                    "query": query,
                    "source_title": result.get(
                        "title",
                        result.get(
                            "source_title",
                            "",
                        ),
                    ),
                    "source_url": result.get(
                        "url",
                        result.get(
                            "source_url",
                            "",
                        ),
                    ),
                    "supporting_text": result.get(
                        "content",
                        result.get(
                            "snippet",
                            result.get(
                                "supporting_text",
                                "",
                            ),
                        ),
                    ),
                    "confidence": result.get(
                        "confidence",
                        0.5,
                    ),
                }

            else:

                source = {
                    "query": query,
                    "source_title": str(result),
                    "source_url": "",
                    "supporting_text": str(result),
                    "confidence": 0.3,
                }

            existing_sources.append(source)

    return {
        "sources": existing_sources,
        "pending_queries": [],
        "iteration": state.get("iteration", 0) + 1,
    }


# ============================================================
# EVIDENCE EXTRACTION
# ============================================================

def extract_evidence(
    state: ResearchState,
) -> Dict[str, Any]:

    sources = state.get("sources", [])

    evidence = list(
        state.get("evidence", [])
    )

    for source in sources:

        if source.get("error"):
            continue

        supporting_text = (
            source.get(
                "supporting_text",
                "",
            )
            .strip()
        )

        if not supporting_text:
            continue

        evidence_item = {
            "claim": supporting_text,
            "type": "OBSERVATION",
            "supporting_evidence": (
                [source.get("source_url", "")]
                if source.get("source_url")
                else []
            ),
            "source_title": source.get(
                "source_title",
                "",
            ),
            "source_url": source.get(
                "source_url",
                "",
            ),
            "confidence": source.get(
                "confidence",
                0.5,
            ),
            "query": source.get(
                "query",
                "",
            ),
        }

        evidence.append(evidence_item)

    return {
        "evidence": evidence,
    }


# ============================================================
# QUALITY CHECK
# ============================================================

def quality_check(
    state: ResearchState,
) -> Dict[str, Any]:

    iteration = state.get(
        "iteration",
        0,
    )

    max_iterations = state.get(
        "max_iterations",
        3,
    )

    evidence = state.get(
        "evidence",
        []
    )

    sources = state.get(
        "sources",
        []
    )

    missing_information: List[str] = []

    if not sources:
        missing_information.append(
            "No sources were successfully retrieved."
        )

    if not evidence:
        missing_information.append(
            "No usable evidence was extracted."
        )

    source_urls = {
        source.get("source_url")
        for source in sources
        if source.get("source_url")
    }

    if len(source_urls) < 2:
        missing_information.append(
            "Research needs more independent sources."
        )

    source_score = min(
        len(source_urls) / 5,
        1.0,
    )

    evidence_score = min(
        len(evidence) / 10,
        1.0,
    )

    diversity_score = (
        1.0
        if len(source_urls) >= 3
        else 0.5
    )

    score = (
        0.4 * source_score
        + 0.4 * evidence_score
        + 0.2 * diversity_score
    )

    return {
        "missing_information": missing_information,
        "evidence_score": score,
    }


# ============================================================
# LOOP DECISION
# ============================================================

def should_continue(
    state: ResearchState,
) -> str:

    iteration = state.get(
        "iteration",
        0,
    )

    max_iterations = state.get(
        "max_iterations",
        3,
    )

    evidence_score = state.get(
        "evidence_score",
        0.0,
    )

    missing_information = state.get(
        "missing_information",
        [],
    )

    # HARD STOP
    if iteration >= max_iterations:
        return "insights"

    # Good enough
    if (
        evidence_score >= 0.7
        and not missing_information
    ):
        return "insights"

    # Need another research pass
    return "research"


# ============================================================
# INSIGHTS
# ============================================================

def generate_insights(
    state: ResearchState,
) -> Dict[str, Any]:

    evidence = state.get(
        "evidence",
        []
    )

    insights: List[Dict[str, Any]] = []

    grouped: Dict[
        str,
        List[Dict[str, Any]]
    ] = {}

    for item in evidence:

        query = item.get(
            "query",
            "general",
        )

        grouped.setdefault(
            query,
            [],
        ).append(item)

    for query, items in grouped.items():

        insights.append(
            {
                "theme": query,
                "finding": (
                    f"{len(items)} evidence item(s) "
                    f"were collected for this research area."
                ),
                "evidence": [
                    item.get("source_url")
                    for item in items
                    if item.get("source_url")
                ],
            }
        )

    return {
        "insights": insights,
    }


# ============================================================
# REPORT
# ============================================================

def generate_report(
    state: ResearchState,
) -> Dict[str, Any]:

    question = state.get(
        "question"
    )

    evidence = state.get(
        "evidence",
        []
    )

    insights = state.get(
        "insights",
        []
    )

    question_text = (
        question.question
        if question
        else ""
    )

    lines = [
        "# Research Report",
        "",
        "## Research Question",
        "",
        question_text,
        "",
        "## Evidence",
        "",
    ]

    for index, item in enumerate(
        evidence,
        start=1,
    ):

        title = item.get(
            "source_title",
            "Unknown source",
        )

        url = item.get(
            "source_url",
            "",
        )

        claim = item.get(
            "claim",
            "",
        )

        lines.append(
            f"### {index}. {title}"
        )

        lines.append("")

        lines.append(claim)

        if url:

            lines.append("")

            lines.append(
                f"Source: {url}"
            )

        lines.append("")

    lines.extend(
        [
            "## Insights",
            "",
        ]
    )

    for insight in insights:

        lines.append(
            f"- **{insight.get('theme', 'General')}**: "
            f"{insight.get('finding', '')}"
        )

    return {
        "report": "\n".join(lines)
    }


# ============================================================
# COMPATIBILITY ALIAS
# ============================================================

# Your graph/tests expect this name.
build_report = generate_report