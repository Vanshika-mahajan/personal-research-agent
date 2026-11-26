"""
Test setup.

* Every test writes into a temporary research/ folder, never your real one.
* Tests that need a live Ollama server or live internet are skipped
  automatically when those are not available (they used to just fail).
"""

import pytest

from tests.fakes import FakeLLM, fake_fetch_page_text, fake_search_web

# Tests that talk to a real local model.
LIVE_LLM = {
    "tests/test_llm.py::test_llm_provider",
    "tests/test_evidence.py::test_extract_evidence_from_search_results",
    "tests/test_evidence_extractor.py::test_extract_claim",
    "tests/test_finding_verifier.py::test_finding_verifier",
}

# Tests that do a real web search.
LIVE_WEB = {
    "tests/test_graph.py::test_research_node",
}


def _llm_up() -> bool:
    from app.llm.provider import llm_health

    return llm_health()[0]


def _web_up() -> bool:
    import os

    quick = {"SEARCH_RETRIES": "0", "SEARCH_TIMEOUT": "8"}
    saved = {key: os.environ.get(key) for key in quick}
    os.environ.update(quick)

    try:
        from app.tools.web_search import search_web

        return bool(search_web("manali hostel", max_results=1))
    except Exception:
        return False
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def pytest_collection_modifyitems(config, items):
    llm_ok = web_ok = None

    for item in items:
        if item.nodeid in LIVE_LLM:
            llm_ok = _llm_up() if llm_ok is None else llm_ok

            if not llm_ok:
                item.add_marker(pytest.mark.skip(reason="needs a running Ollama server"))

        if item.nodeid in LIVE_WEB:
            web_ok = _web_up() if web_ok is None else web_ok

            if not web_ok:
                item.add_marker(pytest.mark.skip(reason="needs internet access"))


@pytest.fixture(autouse=True)
def isolated_research_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("RESEARCH_DIR", str(tmp_path / "research"))
    monkeypatch.setenv("SEARCH_DELAY", "0")

    return tmp_path / "research"


@pytest.fixture
def world(monkeypatch):
    """Replace the LLM and the web everywhere with offline fakes."""

    llm = FakeLLM()

    for target in (
        "app.graph.nodes.generate_text",
        "app.graph.finding_verifier.generate_text",
        "app.workflows.vibers_brief.generate_text",
    ):
        monkeypatch.setattr(target, llm)

    monkeypatch.setattr("app.graph.nodes.search_web", fake_search_web)
    monkeypatch.setattr("app.graph.nodes.fetch_page_text", fake_fetch_page_text)
    monkeypatch.setattr("app.llm.provider.llm_health", lambda: (True, "fake llm"))

    return llm
