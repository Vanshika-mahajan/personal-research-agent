from typing import List

from app.schemas.evidence import Evidence
from app.schemas.source import SearchResult
from app.llm.evidence_extractor import extract_claim

def extract_evidence(
    results: List[SearchResult],
) -> List[Evidence]:
    """
    Convert search results into structured evidence.

    Splits long webpage text into smaller evidence passages
    instead of treating the entire page as one claim.
    """

    evidence: List[Evidence] = []

    for result in results:

        text = result.snippet.strip()

        if not text:
            continue

        # Split the page into paragraphs.
        paragraphs = [
            paragraph.strip()
            for paragraph in text.split("\n")
            if paragraph.strip()
        ]

        # If the page has no paragraph structure,
        # use the full text as one passage.
        if not paragraphs:
            paragraphs = [text]

        for paragraph in paragraphs:

            # Ignore very short or obviously irrelevant fragments.
            if len(paragraph) < 40:
                continue

            lower = paragraph.lower()

            irrelevant_phrases = [
                "cookie policy",
                "privacy policy",
                "terms of use",
                "sign in",
                "log in",
                "subscribe",
                "all rights reserved",
            ]

            if any(
                phrase in lower
                for phrase in irrelevant_phrases
            ):
                continue

            # Keep each evidence passage reasonably small.
            claim = extract_claim(paragraph[:1000])
            if not claim:
                continue

            if "NO_USEFUL_CLAIM" in claim:
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