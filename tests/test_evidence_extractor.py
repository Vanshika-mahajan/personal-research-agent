from app.llm.evidence_extractor import extract_claim


def test_extract_claim():

    text = """
    The hostel is located near Mall Road and guests
    frequently mention that the location makes it easy
    to access restaurants and shops.
    """

    claim = extract_claim(text)

    assert claim
    assert "NO_USEFUL_CLAIM" not in claim