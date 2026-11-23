from langgraph.graph import StateGraph, START, END

from app.graph.state import ResearchState
from app.graph.nodes import (
    research_planner,
    research,
    quality_check,
)
from app.graph.edges import should_continue
from app.graph.insights import generate_insights


def build_graph():
    graph = StateGraph(ResearchState)

    # Nodes
    graph.add_node("research_planner", research_planner)
    graph.add_node("research", research)
    graph.add_node("quality_check", quality_check)
    graph.add_node("insights", generate_insights)

    # Starting flow
    graph.add_edge(START, "research_planner")
    graph.add_edge("research_planner", "research")
    graph.add_edge("research", "quality_check")

    # Conditional loop
    graph.add_conditional_edges(
        "quality_check",
        should_continue,
        {
            "research": "research",
            "insights": "insights",
        },
    )

    # Finish
    graph.add_edge("insights", END)

    return graph.compile()