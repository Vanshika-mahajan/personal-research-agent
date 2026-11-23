from app.graph.graph import build_graph
from app.schemas.research import ResearchQuestion


def test_research_loop():

    graph = build_graph()

    initial_state = {
        "question": ResearchQuestion(
            question="Research hostels in Manali",
            depth="deep",
            max_iterations=3,
        )
    }

    result = graph.invoke(initial_state)

    assert "research_plan" in result
    assert result["iteration"] == 3
    assert result["evidence_score"] == 1.0
    assert result["missing_information"] == []


def test_research_planner():

    graph = build_graph()

    initial_state = {
        "question": ResearchQuestion(
            question="Research hostels in Manali",
            depth="deep",
            max_iterations=3,
        )
    }

    result = graph.invoke(initial_state)

    assert len(result["research_plan"].queries) == 3