from app.graph.insights import generate_insights


def test_generate_insights_from_evidence():
    state = {
        "question": "Research hotels in Manali",
        "evidence": [
            {
                "title": "Hotel Example has mountain views",
                "source": "https://example.com/hotel",
            }
        ],
    }

    result = generate_insights(state)

    assert len(result["insights"]) == 1

    insight = result["insights"][0]

    assert insight["type"] == "FACT"
    assert insight["statement"] == "Hotel Example has mountain views"
    assert insight["supporting_evidence"] == [
        "https://example.com/hotel"
    ]