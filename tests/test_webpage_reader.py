from app.tools.webpage_reader import read_webpage


def test_read_webpage_rejects_empty_url():
    try:
        read_webpage("")
        assert False
    except ValueError:
        assert True