from typing import List

from app.schemas.evidence import Evidence


def check_evidence_quality(
    evidence: List[Evidence],
    min_evidence: int = 3,
) -> dict:
    """
    Evaluate whether the collected evidence is sufficient
    to continue to the insight stage.

    Returns:
        {
            "sufficient": bool,
            "score": float,
            "missing_information": list[str],
        }
    """

    if not evidence:
        return {
            "sufficient": False,
            "score": 0.0,
            "missing_information": [
                "No evidence was collected."
            ],
        }

    valid_evidence = [
        item
        for item in evidence
        if item.claim.strip()
        and item.source_url.strip()
    ]

    if len(valid_evidence) < min_evidence:
        return {
            "sufficient": False,
            "score": min(
                len(valid_evidence) / min_evidence,
                1.0,
            ),
            "missing_information": [
                "More supporting evidence is needed."
            ],
        }

    average_confidence = sum(
        item.confidence
        for item in valid_evidence
    ) / len(valid_evidence)

    score = min(
        0.5 + (0.5 * average_confidence),
        1.0,
    )

    return {
        "sufficient": True,
        "score": score,
        "missing_information": [],
    }