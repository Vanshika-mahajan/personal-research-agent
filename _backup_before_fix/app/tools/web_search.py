from typing import List

from ddgs import DDGS

from app.schemas.source import SearchResult


def search_web(
    query: str,
    max_results: int = 5,
) -> List[SearchResult]:
    """
    Search the web using DuckDuckGo.

    Returns SearchResult objects with:
        title
        url
        snippet
        source_type
    """

    if not query.strip():
        raise ValueError("Search query cannot be empty.")

    results: List[SearchResult] = []

    with DDGS() as ddgs:

        search_results = ddgs.text(
            query,
            max_results=max_results,
        )

        for result in search_results:

            results.append(
                SearchResult(
                    title=result.get("title", ""),
                    url=result.get("href", ""),
                    snippet=result.get("body", ""),
                    source_type="web",
                )
            )

    return results

if __name__ == "__main__":
    results = search_web("best hostels in Manali", max_results=3)

    for result in results:
        print("\nTITLE:", result.title)
        print("URL:", result.url)
        print("SNIPPET:", result.snippet)