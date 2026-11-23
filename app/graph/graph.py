from langgraph.graph import END, START, StateGraph

from app.graph.edges import should_continue
from app.graph.nodes import (
    mock_research,
    quality_check,
    research_planner,
)
from app.graph.state import ResearchState


def build_graph():

    graph = StateGraph(ResearchState)

    # Nodes
    graph.add_node("research_planner", research_planner)
    graph.add_node("research", mock_research)
    graph.add_node("quality_check", quality_check)

    # Initial flow
    graph.add_edge(START, "research_planner")
    graph.add_edge("research_planner", "research")
    graph.add_edge("research", "quality_check")

    # Conditional loop
    graph.add_conditional_edges(
        "quality_check",
        should_continue,
        {
            "research": "research",
            "complete": END,
        },
    )

    return graph.compile()