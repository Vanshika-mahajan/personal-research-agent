from app.tools.source_types import classify_url, is_walled, source_confidence, domain_of


def test_classifies_known_platforms():
    assert classify_url("https://www.instagram.com/zostel/") == ("social", "Instagram")
    assert classify_url("https://www.google.com/maps/place/Zostel") == ("maps", "Google Maps")
    assert classify_url("https://www.booking.com/hotel/in/x.html") == ("booking", "Booking.com")
    assert classify_url("https://www.hostelworld.com/hostels/p/1/x/") == ("booking", "Hostelworld")
    assert classify_url("https://www.tripadvisor.in/Hotel_Review-x.html") == ("review", "Tripadvisor")
    assert classify_url("https://www.reddit.com/r/solotravel/x") == ("forum", "Reddit")
    assert classify_url("https://www.airbnb.co.in/rooms/1") == ("booking", "Airbnb")


def test_unknown_domain_is_plain_web():
    assert classify_url("https://example.com/post") == ("web", "example.com")
    assert classify_url("") == ("web", "")


def test_official_domain_wins():
    assert classify_url("https://www.zostel.com/zostel/manali/", ["zostel.com"]) == (
        "official",
        "Official website",
    )
    # without the hint it is just another booking site
    assert classify_url("https://www.zostel.com/zostel/manali/")[0] == "booking"


def test_walled_and_confidence():
    assert is_walled("social") and is_walled("maps")
    assert not is_walled("booking") and not is_walled("web")
    assert source_confidence("manual") > source_confidence("web")
    assert domain_of("https://www.zostel.com/a/b") == "zostel.com"
