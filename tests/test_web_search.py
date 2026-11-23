from app.tools.web_search import search_web
from app.schemas.source import Source


def test_web_search_returns_sources():

    results = search_web("hostels in Manali", max_results=3)

    assert len(results) > 0
    assert len(results) <= 3

    for result in results:
        assert isinstance(result, Source)
        assert result.title
        assert result.url
        assert result.source_type == "web"
        assert 0.0 <= result.credibility <= 1.0