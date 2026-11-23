from app.tools.webpage_reader import read_webpage


def test_read_webpage_rejects_empty_url():
    try:
        read_webpage("")
        assert False
    except ValueError:
        assert True


def test_read_webpage_extracts_text(monkeypatch):
    class FakeResponse:
        text = """
        <html>
            <head>
                <style>body { color: red; }</style>
            </head>
            <body>
                <h1>Manali Hostel</h1>
                <p>Great location near the mall.</p>
                <script>ignore this</script>
            </body>
        </html>
        """

        def raise_for_status(self):
            pass

    def fake_get(*args, **kwargs):
        return FakeResponse()

    monkeypatch.setattr(
        "app.tools.webpage_reader.requests.get",
        fake_get,
    )

    text = read_webpage("https://example.com")

    assert "Manali Hostel" in text
    assert "Great location near the mall." in text
    assert "ignore this" not in text