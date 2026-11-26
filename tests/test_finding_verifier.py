from app.graph.finding_verifier import (
    verify_findings_with_llm,
)


def test_finding_verifier():
    findings = [
        {
            "finding_id": "finding_1",
            "type": "OBSERVATION",
            "statement": (
                "Guests frequently mention "
                "cleanliness."
            ),
            "evidence_ids": [
                "evidence_1"
            ],
        },
        {
            "finding_id": "finding_2",
            "type": "OBSERVATION",
            "statement": (
                "Manali is the most beautiful "
                "destination in India."
            ),
            "evidence_ids": [
                "evidence_2"
            ],
        },
    ]

    evidence = [
        {
            "evidence_id": "evidence_1",
            "claim": (
                "Several guests mentioned that "
                "the rooms were clean."
            ),
            "source_title": "Guest Reviews",
            "source_url": "https://example.com/reviews",
        },
        {
            "evidence_id": "evidence_2",
            "claim": (
                "The hostel provides hiking "
                "and biking activities."
            ),
            "source_title": "Hostel Website",
            "source_url": "https://example.com/hostel",
        },
    ]

    result = verify_findings_with_llm(
        question=(
            "Research hostels in Manali and "
            "identify common guest complaints."
        ),
        findings=findings,
        evidence=evidence,
    )

    assert len(result) == 2

    for finding in result:
        assert (
            finding["verification_status"]
            in {
                "VERIFIED",
                "UNSUPPORTED",
                "IRRELEVANT",
            }
        )