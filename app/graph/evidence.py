from typing import List

from app.schemas.source import Source


def extract_evidence(sources: List[Source]) -> List[dict]:
    """
    Convert collected sources into structured evidence records.

    For now, this is intentionally simple.
    Later, an LLM will read the actual webpage content
    and extract claims and supporting evidence.
    """

    evidence = []

    for source in sources:
        evidence.append(
            {
                "claim": source.title,
                "evidence": f"Source found: {source.title}",
                "source": source.title,
                "url": source.url,
                "confidence": source.credibility,
            }
        )

    return evidence