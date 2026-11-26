import pytest

from app.llm.json_utils import parse_json


def test_plain_json():
    assert parse_json('{"a": 1}') == {"a": 1}


def test_markdown_fenced_json():
    assert parse_json('```json\n{"a": [1, 2]}\n```') == {"a": [1, 2]}


def test_json_surrounded_by_prose():
    assert parse_json('Sure! Here you go: {"a": 1} hope that helps') == {"a": 1}


@pytest.mark.parametrize("bad", ["", "no json here", None, "{broken"])
def test_garbage_raises_value_error(bad):
    with pytest.raises(ValueError):
        parse_json(bad)
