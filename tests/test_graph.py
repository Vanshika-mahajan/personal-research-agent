from app.graph.graph import build_graph
from app.graph.nodes import research_node
from app.schemas.research import ResearchQuestion


def test_research_node():

    state = {
        "pending_queries": ["best hostels in Manali"],
        "sources": [],
        "iteration": 0,
    }

    result = research_node(state)

    assert len(result["sources"]) > 0
    assert result["pending_queries"] == []
    assert result["iteration"] == 1


def test_graph_builds():

    graph = build_graph()

    assert graph is not None


def test_graph_runs():

    graph = build_graph()

    initial_state = {
        "question": ResearchQuestion(
            question=(
                "Research 5 hostels in Manali "
                "and identify common guest complaints."
            )
        ),

        "search_queries": [],
        "pending_queries": [],
        "sources": [],
        "evidence": [],
        "contradictions": [],
        "findings": [],
        "insights": [],
        "missing_information": [],
        "evidence_score": 0.0,
        "iteration": 0,
        "max_iterations": 1,
        "quality_decision": "",
        "report": "",
    }

    result = graph.invoke(initial_state)

    assert result is not None