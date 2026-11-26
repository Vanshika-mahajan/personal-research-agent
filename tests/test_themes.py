import pytest

from app.graph.themes import rank_themes, themes_for


@pytest.mark.parametrize(
    "text,expected",
    [
        ("The room was not clean and the bathroom smelled", True),
        ("Hot water wasn't working for two days, very cold", True),
        ("Rude reception staff ignored us at check-in", True),
        ("Overpriced menu and hidden charges on the bill", True),
        # praise and neutral text must NOT count as complaints
        ("Rooms were clean and the staff were friendly", False),
        ("No smoking in rooms. Quiet hours after 10pm.", False),
        ("The cafe is not far from the mall road", False),
    ],
)
def test_theme_detection_needs_a_negative_cue(text, expected):
    assert bool(themes_for(text)) is expected


def test_rank_themes_orders_by_properties_then_sources():
    passages = [
        {"text": "The bathroom was dirty and smelled", "property": "A", "source_url": "u1"},
        {"text": "Dirty towels and unclean sheets", "property": "B", "source_url": "u2"},
        {"text": "Rude staff at reception", "property": "A", "source_url": "u3"},
        {"text": "Rude staff again, unhelpful", "property": "A", "source_url": "u4"},
    ]

    ranked = rank_themes(passages, min_sources=2)

    assert ranked[0]["theme"] == "Cleanliness & hygiene"  # 2 properties beats 1
    assert ranked[0]["property_count"] == 2
    assert ranked[0]["examples"]

    themes = {item["theme"] for item in ranked}
    assert "Staff behaviour & service" in themes  # 2 sources, 1 property


def test_min_sources_filters_one_off_complaints():
    passages = [{"text": "The bathroom was dirty", "property": "A", "source_url": "u1"}]

    assert rank_themes(passages, min_sources=2) == []
    # one passage may legitimately belong to more than one theme
    assert len(rank_themes(passages, min_sources=1)) >= 1
