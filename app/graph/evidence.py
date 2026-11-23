from typing import List

from app.schemas.evidence import Evidence
from app.schemas.source import SearchResult


def extract_evidence(
    results: List[SearchResult],
) -> List[Evidence]:
    """
    Convert search results into structured evidence.

    This first version preserves the source information and
    creates one evidence item per search result.
    """

    evidence: List[Evidence] = []

    for result in results:
        claim = result.snippet.strip()

        if not claim:
            continue

        evidence.append(
            Evidence(
                claim=claim,
                source_title=result.title,
                source_url=result.url,
                source_type=result.source_type,
                confidence=0.5,
            )
        )

    return evidence