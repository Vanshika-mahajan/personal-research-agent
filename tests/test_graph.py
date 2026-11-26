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
        "max_iterations": 2,
        "quality_decision": "",
        "report": "",
    }

    result = graph.invoke(initial_state)

    assert result is not None

def test_followup_query_generation():
    from app.graph.nodes import generate_followup_queries

    state = {
        "question": ResearchQuestion(
            question="Research hostels in Manali"
        ),
        "missing_information": [
            "Research needs more independent sources."
        ],
        "search_queries": [
            "Research hostels in Manali"
        ],
    }

    result = generate_followup_queries(state)

    assert len(result["pending_queries"]) > 0

    previous_queries = {
        query.lower()
        for query in state["search_queries"]
    }

    for query in result["pending_queries"]:
        assert query.lower() not in previous_queries
        assert isinstance(query, str)
        assert query.strip()