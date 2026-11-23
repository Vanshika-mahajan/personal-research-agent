from app.graph.state import ResearchState
from app.schemas.insight import Insight


def generate_insights(state: ResearchState) -> ResearchState:
    """
    Convert collected evidence into structured insights.

    This first version is deterministic so the graph
    architecture can be tested before connecting an LLM.
    """

    evidence = state.get("evidence", [])

    insights = []

    for item in evidence:
        title = item.get("title", "")
        source = item.get("source", "")

        if not title:
            continue

        insight = Insight(
            statement=title,
            type="FACT",
            supporting_evidence=[source] if source else [],
            confidence=0.8,
            reasoning="Derived directly from the collected evidence.",
        )

        insights.append(insight.model_dump())

    return {
        **state,
        "insights": insights,
    }