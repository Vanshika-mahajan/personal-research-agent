from app.graph.evidence_utils import build_evidence, mentions_subject, subject_tokens
from app.schemas.source import SearchResult


def result(title, url, snippet="", content="", source_type="web", platform=""):
    return SearchResult(
        title=title, url=url, snippet=snippet, content=content,
        source_type=source_type, platform=platform,
    )


def test_subject_tokens_drop_generic_and_place_words():
    assert subject_tokens("Zostel Old Manali", "Manali") == ["zostel"]
    assert subject_tokens("The Hosteller Manali, Old Manali", "Manali") == ["hosteller"]
    assert subject_tokens("Cafe 1947", "Manali") == ["1947"]
    assert subject_tokens("Dylan's Toasted & Roasted", "Manali")[0] == "dylans"


def test_mentions_subject_handles_apostrophes_and_numbers():
    assert mentions_subject("Dylan’s coffee is great", "Dylan's Toasted & Roasted", "Manali")
    assert mentions_subject("Cafe 1947 sits by the river", "Cafe 1947", "Manali")
    assert not mentions_subject("India gained independence in 1947 after partition", "Cafe 1947", "Manali")
    assert not mentions_subject("Moustache hostel has dirty rooms", "Zostel Old Manali", "Manali")


def test_passages_about_other_venues_are_dropped():
    sources = [
        result(
            "Best hostels in Manali",
            "https://blog.example.com/best",
            snippet=(
                "Moustache Hostel has dirty rooms and rude staff, guests say.\n"
                "Zostel Old Manali guests complained that the bathroom was dirty."
            ),
        )
    ]

    evidence = build_evidence(sources, subject="Zostel Old Manali", place="Manali")

    claims = " ".join(item["claim"] for item in evidence)

    assert "Zostel" in claims
    assert "Moustache" not in claims


def test_page_about_the_venue_keeps_unnamed_passages():
    sources = [
        result(
            "Zostel Old Manali - Booking.com",
            "https://www.booking.com/hotel/in/zostel-old-manali.html",
            content="Guests say the staff were unhelpful and the room was cold at night.",
            source_type="booking",
        )
    ]

    evidence = build_evidence(sources, subject="Zostel Old Manali", place="Manali")

    assert len(evidence) == 1  # the passage never says "Zostel" but the page is about it


def test_caps_dedupe_and_ids():
    long_snippets = "\n".join(f"Guests complained about problem number {i} at the hostel today." for i in range(30))

    sources = [
        result("One", "https://a.example.com", snippet=long_snippets),
        result("Two", "https://b.example.com", snippet=long_snippets),  # duplicates of One
    ]

    evidence = build_evidence(sources, max_total=10, per_source=4)

    assert len(evidence) <= 8  # 4 per source, duplicates removed
    assert len({item["claim"] for item in evidence}) == len(evidence)
    assert [item["evidence_id"] for item in evidence] == [f"evidence_{i}" for i in range(1, len(evidence) + 1)]


def test_manual_notes_come_first_and_are_marked():
    sources = [result("Blog", "https://x.example.com", snippet="Zostel Old Manali has a rooftop cafe with views.")]

    manual = [{"text": "Google review: the hot water never worked in our dorm.", "platform": "Google Maps"}]

    evidence = build_evidence(sources, manual=manual, subject="Zostel Old Manali", place="Manali")

    assert evidence[0]["source_type"] == "manual"
    assert evidence[0]["origin"] == "manual"
    assert evidence[0]["confidence"] >= 0.8


def test_noise_is_filtered():
    sources = [result("x", "https://x.example.com", snippet="Accept cookies and sign in to continue reading our site now.")]

    assert build_evidence(sources) == []
