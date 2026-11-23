from app.graph.state import ResearchState
from app.tools.web_search import search_web
from app.schemas.research import ResearchPlan


def research_planner(state: ResearchState) -> dict:
    """Create the initial research plan."""

    question = state["question"]

    plan = ResearchPlan(
        queries=[
            {
                "query": "hostels in Manali",
                "purpose": "Identify relevant hostels and properties",
                "priority": 5,
            },
            {
                "query": "Manali hostels reviews complaints",
                "purpose": "Find recurring customer complaints",
                "priority": 4,
            },
            {
                "query": "Manali hostels reviews positive experiences",
                "purpose": "Find what guests appreciate",
                "priority": 4,
            },
            {
                "query": "Manali hostel customer experience",
                "purpose": "Understand guest expectations and experiences",
                "priority": 3,
            },
            {
                "query": "best hostels Manali Zostel goStops Moustache",
                "purpose": "Identify major hostel competitors",
                "priority": 3,
            },
        ],
        research_goals=[
            "Identify relevant properties",
            "Identify recurring customer problems",
            "Identify positive guest experiences",
            "Identify customer expectations",
            "Identify competitor patterns",
        ],
        expected_output="Evidence-backed research report",
    )

    return {
        "research_plan": plan,
        "iteration": 0,
        "max_iterations": question.max_iterations,
    }


def research(state: ResearchState) -> dict:
    plan = state["research_plan"]

    sources = list(state.get("sources", []))

    for query in plan.queries:
        results = search_web(
            query=query.query,
            max_results=5,
        )

        sources.extend(results)

    return {
        "sources": sources,
        "iteration": state.get("iteration", 0) + 1,
    }

def quality_check(state: ResearchState) -> dict:
    """
    Decide whether enough evidence has been collected.
    """

    sources = state.get("sources", [])
    iteration = state.get("iteration", 0)
    max_iterations = state.get("max_iterations", 3)

    print(
        f"Quality check: iteration={iteration}, "
        f"sources={len(sources)}"
    )

    # We have enough evidence.
    if len(sources) >= 10:
        return {
            "evidence_score": 1.0,
            "missing_information": [],
        }

    # We have reached the safety limit.
    if iteration >= max_iterations:
        return {
            "evidence_score": len(sources) / 10,
            "missing_information": [
                "More evidence could not be collected within the iteration limit."
            ],
        }

    # Not enough evidence yet.
    return {
        "evidence_score": len(sources) / 10,
        "missing_information": [
            "Need more sources."
        ],
    }

def quality_check(state: ResearchState) -> dict:
    """
    Decide whether the collected research is sufficient.
    """

    sources = state.get("sources", [])
    iteration = state.get("iteration", 0)
    max_iterations = state.get("max_iterations", 3)

    print(
        f"Quality check: iteration={iteration}, "
        f"sources={len(sources)}"
    )

    # Enough evidence
    if len(sources) >= 10:
        return {
            "evidence_score": 1.0,
            "missing_information": [],
        }

    # We have reached the maximum allowed iterations
    if iteration >= max_iterations:
        return {
            "evidence_score": len(sources) / 10,
            "missing_information": [
                "More evidence is needed, but the maximum iteration limit was reached."
            ],
        }

    # Need another research pass
    return {
        "evidence_score": len(sources) / 10,
        "missing_information": [
            "More evidence is needed."
        ],
    }