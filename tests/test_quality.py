from app.graph.quality import quality_check, should_continue


def test_quality_check_requests_more_research():
    state = {
        "sources": [],
        "evidence": [],
        "iteration": 1,
        "max_iterations": 3,
    }

    result = quality_check(state)

    assert result["quality_decision"] == "research"
    assert should_continue(
        {**state, **result}
    ) == "research"


def test_quality_check_accepts_sufficient_evidence():
    state = {
        "sources": [1, 2, 3, 4, 5],
        "evidence": [1, 2, 3],
        "iteration": 1,
        "max_iterations": 3,
    }

    result = quality_check(state)

    assert result["quality_decision"] == "insights"
    assert should_continue(
        {**state, **result}
    ) == "insights"


def test_quality_check_stops_at_max_iterations():
    state = {
        "sources": [],
        "evidence": [],
        "iteration": 3,
        "max_iterations": 3,
    }

    result = quality_check(state)

    assert result["quality_decision"] == "insights"
    assert should_continue(
        {**state, **result}
    ) == "insights"