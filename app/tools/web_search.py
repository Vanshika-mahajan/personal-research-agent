from typing import List
import time

from ddgs import DDGS

from app.schemas.source import Source


def search_web(query: str, max_results: int = 5) -> List[Source]:
    """
    Search the web and convert search results into
    validated Pydantic Source objects.
    """

    sources: List[Source] = []

    queries_to_try = [
        query,
        f"{query} India",
        f"{query} travel",
    ]

    for search_query in queries_to_try:
        try:
            with DDGS(timeout=10) as ddgs:
                results = list(
                    ddgs.text(
                        search_query,
                        max_results=max_results,
                    )
                )

            for result in results:
                title = result.get("title", "").strip()
                url = result.get("href", "").strip()

                if not title or not url:
                    continue

                source = Source(
                    title=title,
                    url=url,
                    source_type="web",
                    credibility=0.5,
                )

                sources.append(source)

            if sources:
                break

        except Exception as e:
            print(
                f"Web search error for query "
                f"'{search_query}': {e}"
            )

            time.sleep(1)

    if not sources:
        print(
            f"Web search failed for query "
            f"'{query}': No results found."
        )

    return sources[:max_results]