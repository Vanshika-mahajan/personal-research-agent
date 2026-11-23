from app.graph.state import ResearchState


def should_continue(state: ResearchState) -> str:
    """
    Decide whether the research loop should continue
    or move forward.
    """

    evidence_score = state.get("evidence_score", 0.0)
    iteration = state.get("iteration", 0)
    max_iterations = state.get("max_iterations", 3)

    if evidence_score >= 0.8:
        return "complete"

    if iteration >= max_iterations:
        return "complete"

    return "research"