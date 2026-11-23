from app.tools.web_search import search_web


def test_web_search_returns_sources(monkeypatch):
    """
    Test search result conversion without making a real network request.
    """

    class FakeDDGS:
        def __init__(self, *args, **kwargs):
            # Accept the same constructor arguments as the real DDGS client.
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            pass

        def text(self, query, max_results=5):
            return [
                {
                    "title": "Manali Hotel Example",
                    "href": "https://example.com/manali-hotel",
                    "body": "Example information about a hotel in Manali.",
                },
                {
                    "title": "Manali Travel Guide",
                    "href": "https://example.com/manali-guide",
                    "body": "Example travel information about Manali.",
                },
            ]

    monkeypatch.setattr(
        "app.tools.web_search.DDGS",
        FakeDDGS,
    )

    results = search_web(
        "hostels in Manali",
        max_results=3,
    )

    assert len(results) > 0
    assert results[0].title == "Manali Hotel Example"
    assert results[0].url == "https://example.com/manali-hotel"
    assert results[0].source_type == "web"