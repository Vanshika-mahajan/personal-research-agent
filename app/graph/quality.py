from typing import Literal

from app.graph.state import ResearchState


def quality_check(state: ResearchState) -> dict:
    """
    Evaluate whether the research has enough evidence to continue
    to insight generation or whether another research iteration is needed.

    This node does not perform web searches.
    It only evaluates the current state.
    """

    sources = state.get("sources", [])
    evidence = state.get("evidence", [])
    iteration = state.get("iteration", 0)
    max_iterations = state.get("max_iterations", 3)

    print(
        f"Quality check: iteration={iteration}, "
        f"sources={len(sources)}, evidence={len(evidence)}"
    )

    # Basic evidence threshold.
    # We deliberately keep this deterministic for now.
    enough_sources = len(sources) >= 5
    enough_evidence = len(evidence) >= 3

    if enough_sources and enough_evidence:
        decision = "insights"

    elif iteration >= max_iterations:
        # Never allow the research loop to run forever.
        decision = "insights"

    else:
        decision = "research"

    return {
        "quality_decision": decision,
    }


def should_continue(
    state: ResearchState,
) -> Literal["research", "insights"]:
    """
    Convert the quality-check result into a LangGraph routing decision.
    """

    decision = state.get("quality_decision", "research")

    if decision == "insights":
        return "insights"

    return "research"