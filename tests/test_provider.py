import pytest
import requests

from app.llm import provider


class FakeResponse:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self._data


def test_payload_puts_temperature_and_context_in_options(monkeypatch):
    seen = {}

    def fake_post(url, json=None, timeout=None):
        seen.update(url=url, payload=json, timeout=timeout)
        return FakeResponse({"response": "hello"})

    monkeypatch.setattr(provider.requests, "post", fake_post)
    monkeypatch.setenv("OLLAMA_NUM_CTX", "4096")
    monkeypatch.setenv("OLLAMA_MODEL", "mymodel:1b")

    assert provider.generate_text("hi") == "hello"

    payload = seen["payload"]
    assert payload["options"]["temperature"] == 0
    assert payload["options"]["num_ctx"] == 4096
    assert "temperature" not in payload  # top-level temperature is ignored by Ollama
    assert payload["format"] == "json"
    assert payload["model"] == "mymodel:1b"


def test_prose_mode_does_not_force_json(monkeypatch):
    seen = {}

    def fake_post(url, json=None, timeout=None):
        seen.update(payload=json)
        return FakeResponse({"response": "text"})

    monkeypatch.setattr(provider.requests, "post", fake_post)

    provider.generate_text("hi", json_mode=False)

    assert "format" not in seen["payload"]


def test_connection_error_becomes_clear_error(monkeypatch):
    def boom(*args, **kwargs):
        raise requests.ConnectionError("refused")

    monkeypatch.setattr(provider.requests, "post", boom)

    with pytest.raises(provider.LLMUnavailableError) as info:
        provider.generate_text("hi")

    assert "ollama serve" in str(info.value)


def test_health_reports_missing_server_and_missing_model(monkeypatch):
    def down(*args, **kwargs):
        raise requests.ConnectionError("refused")

    monkeypatch.setattr(provider.requests, "get", down)
    ok, message = provider.llm_health()
    assert not ok and "ollama serve" in message

    class Tags:
        def raise_for_status(self):
            pass

        def json(self):
            return {"models": [{"name": "other:7b"}]}

    monkeypatch.setattr(provider.requests, "get", lambda *a, **k: Tags())
    monkeypatch.setenv("OLLAMA_MODEL", "llama3.2:3b")
    ok, message = provider.llm_health()
    assert not ok and "ollama pull llama3.2:3b" in message

    monkeypatch.setenv("OLLAMA_MODEL", "other:7b")
    assert provider.llm_health()[0]
