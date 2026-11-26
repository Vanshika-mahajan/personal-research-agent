"""
Central settings for the research agent.

Every value can be overridden from the .env file or the shell, e.g.

    OLLAMA_MODEL=llama3.1:8b
    OLLAMA_NUM_CTX=8192
    FETCH_PAGES=false

Settings are read each time get_settings() is called, so tests (and you)
can change environment variables without restarting anything.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

try:  # python-dotenv is in requirements.txt, but never crash without it
    from dotenv import load_dotenv

    load_dotenv(PROJECT_ROOT / ".env", override=False)
except Exception:  # pragma: no cover
    pass


def _str(name: str, default: str) -> str:
    value = os.getenv(name)
    return value.strip() if value and value.strip() else default


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "").strip() or default)
    except ValueError:
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, "").strip() or default)
    except ValueError:
        return default


def _bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    # --- LLM (local Ollama) -------------------------------------------
    ollama_base_url: str
    ollama_model: str
    ollama_num_ctx: int
    llm_timeout: int

    # --- Where results are written -----------------------------------
    research_dir: Path

    # --- Search / reading --------------------------------------------
    results_per_query: int
    search_delay: float
    search_timeout: int
    search_retries: int
    search_region: str
    fetch_pages: bool
    max_pages_per_query: int
    page_max_chars: int

    # --- Evidence / analysis size limits -----------------------------
    max_evidence: int
    evidence_per_source: int
    analyze_batch_size: int
    verify_batch_size: int


def get_settings() -> Settings:
    return Settings(
        ollama_base_url=_str("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/"),
        ollama_model=_str("OLLAMA_MODEL", "llama3.2:3b"),
        # Ollama's default context is small. Evidence lists need more room,
        # otherwise the model silently ignores the start of the prompt.
        ollama_num_ctx=_int("OLLAMA_NUM_CTX", 8192),
        llm_timeout=_int("LLM_TIMEOUT", 240),
        research_dir=Path(_str("RESEARCH_DIR", str(PROJECT_ROOT / "research"))),
        results_per_query=_int("RESULTS_PER_QUERY", 6),
        # DuckDuckGo throttles quick bursts, so pause between searches, wait longer
        # than the library's 5 s default, and retry a failed search after a pause.
        search_delay=_float("SEARCH_DELAY", 1.5),
        search_timeout=_int("SEARCH_TIMEOUT", 15),
        search_retries=_int("SEARCH_RETRIES", 2),
        search_region=_str("SEARCH_REGION", "wt-wt"),
        fetch_pages=_bool("FETCH_PAGES", True),
        max_pages_per_query=_int("MAX_PAGES_PER_QUERY", 2),
        page_max_chars=_int("PAGE_MAX_CHARS", 20000),
        max_evidence=_int("MAX_EVIDENCE", 60),
        evidence_per_source=_int("EVIDENCE_PER_SOURCE", 4),
        analyze_batch_size=_int("ANALYZE_BATCH_SIZE", 10),
        verify_batch_size=_int("VERIFY_BATCH_SIZE", 6),
    )
