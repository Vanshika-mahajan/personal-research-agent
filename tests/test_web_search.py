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

        def text(self, query, max_results=5, **options):
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

class DDGSException(Exception):
    """Same name as ddgs' own exception, which is what the code looks at."""


def _fake_ddgs(monkeypatch, outcomes, seen):
    """A DDGS whose successive searches either return rows or raise, as listed in `outcomes`."""

    class Fake:
        def __init__(self, *args, **kwargs):
            seen["init"] = kwargs

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def text(self, query, **options):
            seen.setdefault("calls", []).append(options)
            outcome = outcomes.pop(0)

            if isinstance(outcome, Exception):
                raise outcome

            return outcome

    monkeypatch.setattr("app.tools.web_search.DDGS", Fake)


ROW = [{"title": "A", "href": "https://example.com/a", "body": "b"}]


def test_a_slow_search_is_retried_and_waits_longer_than_five_seconds(monkeypatch):
    seen = {}
    _fake_ddgs(monkeypatch, [TimeoutError("timed out"), TimeoutError("timed out"), ROW], seen)

    results = search_web("hostels in Manali", max_results=3)

    assert [r.url for r in results] == ["https://example.com/a"]
    assert len(seen["calls"]) == 3
    assert seen["init"]["timeout"] >= 10
    assert seen["calls"][0]["region"] == "wt-wt"


def test_retries_are_limited_and_the_last_error_is_raised(monkeypatch):
    import pytest

    seen = {}
    _fake_ddgs(monkeypatch, [TimeoutError("one"), TimeoutError("two"), TimeoutError("three"), ROW], seen)

    with pytest.raises(TimeoutError, match="three"):
        search_web("hostels in Manali")

    assert len(seen["calls"]) == 3                       # 1 try + SEARCH_RETRIES (2)


def test_retries_can_be_switched_off(monkeypatch):
    import pytest

    monkeypatch.setenv("SEARCH_RETRIES", "0")
    seen = {}
    _fake_ddgs(monkeypatch, [TimeoutError("one"), ROW], seen)

    with pytest.raises(TimeoutError):
        search_web("hostels in Manali")

    assert len(seen["calls"]) == 1


def test_no_results_found_is_an_empty_answer_not_a_failure(monkeypatch):
    seen = {}
    _fake_ddgs(monkeypatch, [DDGSException("No results found.")], seen)

    assert search_web("zzzz qqqq unlikely") == []
    assert len(seen["calls"]) == 1                       # nothing to retry


def test_the_retry_pause_is_announced_so_the_page_does_not_look_stuck(monkeypatch, capsys):
    seen = {}
    _fake_ddgs(monkeypatch, [TimeoutError("timed out"), ROW], seen)

    search_web("hostels in Manali")

    assert "retrying" in capsys.readouterr().out
