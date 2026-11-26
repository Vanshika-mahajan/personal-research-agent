import time
from typing import Iterable, List

from ddgs import DDGS

from app.config import get_settings
from app.schemas.source import SearchResult
from app.tools.source_types import classify_url


class SearchUnavailable(RuntimeError):
    """Web search has failed so many times in a row that carrying on is pointless."""


def _is_empty_answer(exc: Exception) -> bool:
    """ddgs raises DDGSException('No results found.') for a search that simply had no hits."""

    return (
        exc.__class__.__name__ == "DDGSException"
        and str(exc).strip().rstrip(".").lower() == "no results found"
    )


def _text_search(query: str, max_results: int) -> list:
    """One DuckDuckGo search, retried after a pause when it times out or is throttled."""

    settings = get_settings()
    attempts = 1 + max(0, settings.search_retries)
    options = {"max_results": max_results}

    if settings.search_region:
        options["region"] = settings.search_region

    for attempt in range(attempts):
        try:
            with DDGS(timeout=settings.search_timeout) as ddgs:
                return list(ddgs.text(query, **options))
        except Exception as exc:
            if _is_empty_answer(exc):
                return []

            if attempt + 1 >= attempts:
                raise

            pause = settings.search_delay * 2 * (attempt + 1)
            print(f"   (search slow: {exc.__class__.__name__}; retrying in {pause:g}s)")
            time.sleep(pause)

    return []


def search_web(
    query: str,
    max_results: int = 5,
    official_domains: Iterable[str] = (),
) -> List[SearchResult]:
    """
    Search the web using DuckDuckGo.

    Returns SearchResult objects with:
        title
        url
        snippet
        source_type   (maps / social / review / booking / forum / ... / web)
        platform      (e.g. "Booking.com", "Instagram")

    Tip: DuckDuckGo understands `site:` so a query such as
    "site:instagram.com zostel manali" targets one platform.
    """

    if not query.strip():
        raise ValueError("Search query cannot be empty.")

    results: List[SearchResult] = []

    for result in _text_search(query, max_results):
        url = result.get("href", "")

        source_type, platform = classify_url(
            url,
            official_domains,
        )

        results.append(
            SearchResult(
                title=result.get("title", ""),
                url=url,
                snippet=result.get("body", ""),
                source_type=source_type,
                platform=platform,
            )
        )

    return results


if __name__ == "__main__":
    for result in search_web("best hostels in Manali", max_results=3):
        print("\nTITLE:", result.title)
        print("URL:", result.url)
        print("TYPE:", result.source_type, "/", result.platform)
        print("SNIPPET:", result.snippet)
