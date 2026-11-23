import pytest

import app.graph.nodes as nodes

from app.graph.graph import build_graph
from app.schemas.research import ResearchQuestion
from app.schemas.source import Source


def fake_search_web(query: str, max_results: int = 5):
    """
    Fake web search used by graph tests.

    This prevents tests from depending on:
    - internet connectivity
    - DuckDuckGo
    - search API timeouts
    - rate limits
    """

    return [
        Source(
            title=f"Test result for {query}",
            url="https://example.com",
            source_type="web",
            credibility=0.8,
        )
    ]


@pytest.fixture(autouse=True)
def mock_web_search(monkeypatch):
    monkeypatch.setattr(
        nodes,
        "search_web",
        fake_search_web,
    )


def make_question():
    return ResearchQuestion(
        question="Research hostels in Manali",
        depth="deep",
        max_iterations=3,
    )


def test_research_planner():

    graph = build_graph()

    initial_state = {
        "question": make_question()
    }

    result = graph.invoke(initial_state)

    assert "research_plan" in result

    plan = result["research_plan"]

    assert plan is not None
    assert len(plan.queries) >= 3


def test_research_loop():

    graph = build_graph()

    initial_state = {
        "question": make_question()
    }

    result = graph.invoke(initial_state)

    assert "research_plan" in result
    assert "sources" in result
    assert "iteration" in result

    assert isinstance(result["sources"], list)

    assert len(result["sources"]) > 0

    assert result["iteration"] >= 1


def test_research_respects_max_iterations():

    graph = build_graph()

    initial_state = {
        "question": make_question()
    }

    result = graph.invoke(initial_state)

    assert result["iteration"] <= 3


def test_research_plan_contains_queries():

    graph = build_graph()

    initial_state = {
        "question": make_question()
    }

    result = graph.invoke(initial_state)

    plan = result["research_plan"]

    assert len(plan.queries) >= 3

    queries = [
        query.query
        for query in plan.queries
    ]

    assert "hostels in Manali" in queries

    assert any(
        "complaints" in query.lower()
        for query in queries
    )

    assert any(
        "positive" in query.lower()
        for query in queries
    )


def test_research_state_preserves_question():

    graph = build_graph()

    question = make_question()

    initial_state = {
        "question": question
    }

    result = graph.invoke(initial_state)

    assert result["question"] == question