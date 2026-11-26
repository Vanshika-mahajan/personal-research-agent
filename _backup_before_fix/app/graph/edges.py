from app.graph.state import ResearchState


def should_continue(state: ResearchState) -> str:
    """
    Decide where the graph goes after quality_check.
    """

    sources = state.get("sources", [])
    iteration = state.get("iteration", 0)
    max_iterations = state.get("max_iterations", 3)

    if len(sources) >= 10:
        return "insights"

    if iteration >= max_iterations:
        return "insights"

    return "research"