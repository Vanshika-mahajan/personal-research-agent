from app.graph.evidence import extract_evidence
from app.schemas.source import Source


def test_extract_evidence():
    sources = [
        Source(
            title="Test Hotel",
            url="https://example.com",
            source_type="web",
            credibility=0.8,
        )
    ]

    evidence = extract_evidence(sources)

    assert len(evidence) == 1
    assert evidence[0]["source"] == "Test Hotel"
    assert evidence[0]["url"] == "https://example.com"
    assert evidence[0]["confidence"] == 0.8