from langgraph.graph import (
    StateGraph,
    START,
    END,
)

from app.graph.state import ResearchState

from app.graph.nodes import (
    research_planner,
    research,
    extract_evidence,
    analyze_evidence_with_llm,
    verify_findings,
    quality_check,
    should_continue,
    generate_followup_queries,
    generate_insights,
    generate_report,
)
from app.graph.state import ResearchState

def build_graph():
    graph = StateGraph(
        ResearchState
    )

    # --------------------------------------------------------
    # Nodes
    # --------------------------------------------------------

    graph.add_node(
        "research_planner",
        research_planner,
    )

    graph.add_node(
        "research",
        research,
    )

    graph.add_node(
        "extract_evidence",
        extract_evidence,
    )

    graph.add_node(
        "analyze_evidence",
        analyze_evidence_with_llm,
    )

    graph.add_node(
        "verify_findings",
        verify_findings,
    )

    graph.add_node(
        "quality_check",
        quality_check,
    )

    graph.add_node(
        "generate_followup_queries",
        generate_followup_queries,
    )

    graph.add_node(
        "insights",
        generate_insights,
    )

    graph.add_node(
        "report",
        generate_report,
    )

    # --------------------------------------------------------
    # Initial research flow
    # --------------------------------------------------------

    graph.add_edge(
        START,
        "research_planner",
    )

    graph.add_edge(
        "research_planner",
        "research",
    )

    graph.add_edge(
        "research",
        "extract_evidence",
    )

    graph.add_edge(
        "extract_evidence",
        "analyze_evidence",
    )

    # --------------------------------------------------------
    # Finding verification
    # --------------------------------------------------------

    graph.add_edge(
        "analyze_evidence",
        "verify_findings",
    )

    graph.add_edge(
        "verify_findings",
        "quality_check",
    )

    # --------------------------------------------------------
    # Conditional research loop
    # --------------------------------------------------------

    graph.add_conditional_edges(
        "quality_check",
        should_continue,
        {
            "followup": (
                "generate_followup_queries"
            ),
            "insights": "insights",
        },
    )

    graph.add_edge(
        "generate_followup_queries",
        "research",
    )

    # --------------------------------------------------------
    # Final pipeline
    # --------------------------------------------------------

    graph.add_edge(
        "insights",
        "report",
    )

    graph.add_edge(
        "report",
        END,
    )

    return graph.compile()