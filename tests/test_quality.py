from app.graph.quality import check_evidence_quality
from app.schemas.evidence import Evidence


def make_evidence(
    claim: str,
    confidence: float = 0.8,
) -> Evidence:
    return Evidence.model_construct(
        claim=claim,
        source_title="Test Source",
        source_url="https://example.com",
        source_type="web",
        confidence=confidence,
    )


def test_quality_fails_when_evidence_is_empty():

    result = check_evidence_quality([])

    assert result["sufficient"] is False
    assert result["score"] == 0.0
    assert len(result["missing_information"]) > 0


def test_quality_fails_when_evidence_is_insufficient():

    evidence = [
        make_evidence("Guests liked the location.")
    ]

    result = check_evidence_quality(
        evidence,
        min_evidence=3,
    )

    assert result["sufficient"] is False
    assert result["score"] < 1.0


def test_quality_passes_with_enough_evidence():

    evidence = [
        make_evidence("Guests liked the location."),
        make_evidence("Guests appreciated the social atmosphere."),
        make_evidence("Guests mentioned clean rooms."),
    ]

    result = check_evidence_quality(
        evidence,
        min_evidence=3,
    )

    assert result["sufficient"] is True
    assert result["score"] > 0.5
    assert result["missing_information"] == []


def test_quality_ignores_invalid_evidence():

    evidence = [
        make_evidence("Valid evidence."),
        Evidence.model_construct(
            claim="",
            source_title="Invalid Source",
            source_url="https://example.com",
            source_type="web",
            confidence=0.8,
        ),
    ]

    result = check_evidence_quality(
        evidence,
        min_evidence=2,
    )

    assert result["sufficient"] is False