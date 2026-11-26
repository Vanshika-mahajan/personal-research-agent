from app.tools import webpage_reader
from app.tools.webpage_reader import fetch_page_text, split_passages


def test_fetch_page_text_never_raises(monkeypatch):
    def boom(url):
        raise RuntimeError("403")

    monkeypatch.setattr(webpage_reader, "read_webpage", boom)

    assert fetch_page_text("https://blocked.example.com") == ""


def test_fetch_page_text_truncates_and_collapses_whitespace(monkeypatch):
    monkeypatch.setattr(webpage_reader, "read_webpage", lambda url: "a  b\n\n c " * 1000)

    text = fetch_page_text("https://x.example.com", max_chars=50)

    assert len(text) <= 50
    assert "  " not in text


def test_split_passages_groups_sentences():
    text = ("First sentence about the hostel. " * 30).strip()

    passages = split_passages(text, target=200, maximum=400)

    assert len(passages) > 1
    assert all(len(p) <= 400 for p in passages)


def test_split_passages_keeps_snippet_paragraphs_and_chops_giants():
    assert split_passages("Line one is here.\nLine two is here.") == [
        "Line one is here.",
        "Line two is here.",
    ]

    giant = "x" * 2000
    assert all(len(p) <= 700 for p in split_passages(giant))
    assert split_passages("") == []
