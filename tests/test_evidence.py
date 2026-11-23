from app.graph.evidence import extract_evidence
from app.schemas.source import SearchResult


def test_extract_evidence_from_search_results():

    results = [
        SearchResult(
            title="Manali Hostel Example",
            url="https://example.com/hostel",
            snippet="Guests appreciated the social atmosphere.",
            source_type="web",
        ),
        SearchResult(
            title="Manali Travel Guide",
            url="https://example.com/manali",
            snippet="Manali attracts travellers throughout the year.",
            source_type="web",
        ),
    ]

    evidence = extract_evidence(results)

    assert len(evidence) == 2

    assert (
        evidence[0].claim
        == "Guests appreciated the social atmosphere."
    )

    assert (
        evidence[0].source_title
        == "Manali Hostel Example"
    )

    assert (
        evidence[0].source_url
        == "https://example.com/hostel"
    )

    assert evidence[0].source_type == "web"


def test_extract_evidence_ignores_empty_snippets():

    results = [
        SearchResult(
            title="Empty Source",
            url="https://example.com",
            snippet="",
            source_type="web",
        )
    ]

    evidence = extract_evidence(results)

    assert evidence == []