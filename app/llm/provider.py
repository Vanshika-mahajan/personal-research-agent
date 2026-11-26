"""
Local Ollama client.

Fixes compared with the first version:
  * temperature must live inside "options" - at the top level Ollama
    ignores it, so runs were not deterministic.
  * num_ctx is raised, otherwise long evidence prompts are silently cut.
  * clear error + health check when Ollama is not running.
"""

from __future__ import annotations

import time
from typing import Tuple

import requests

from app.config import get_settings


class LLMUnavailableError(RuntimeError):
    """Raised when the local Ollama server cannot be reached."""


def get_llm() -> dict:
    """Return the local Ollama model configuration."""

    settings = get_settings()

    return {
        "base_url": settings.ollama_base_url,
        "model": settings.ollama_model,
        "num_ctx": settings.ollama_num_ctx,
    }


def llm_health() -> Tuple[bool, str]:
    """
    Check that Ollama is running and the configured model is installed.

    Returns (ok, human readable message).
    """

    llm = get_llm()

    try:
        response = requests.get(f"{llm['base_url']}/api/tags", timeout=5)
        response.raise_for_status()
    except requests.RequestException:
        return False, (
            f"Ollama is not reachable at {llm['base_url']}. "
            f"Start it with `ollama serve`, then run "
            f"`ollama pull {llm['model']}`."
        )

    installed = [
        item.get("name", "") for item in response.json().get("models", [])
    ]

    wanted = llm["model"]

    if not any(name == wanted or name.split(":")[0] == wanted for name in installed):
        return False, (
            f"Ollama is running but model '{wanted}' is not installed. "
            f"Run `ollama pull {wanted}` (or set OLLAMA_MODEL in .env)."
        )

    return True, f"Ollama OK - model {wanted}, context {llm['num_ctx']} tokens."


def generate_text(
    prompt: str,
    json_mode: bool = True,
    timeout: int | None = None,
) -> str:
    """
    Send a prompt to the local Ollama model.

    json_mode=True:
        Ollama is forced to return valid JSON. Use for structured output
        (plans, findings, verification, follow-up queries).

    json_mode=False:
        Normal prose. Use for summaries.
        (The old code used json mode for the final report, which made the
        "report" a JSON blob.)
    """

    llm = get_llm()
    settings = get_settings()

    payload = {
        "model": llm["model"],
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0,
            "num_ctx": llm["num_ctx"],
        },
    }

    if json_mode:
        payload["format"] = "json"

    last_error: Exception | None = None

    for attempt in range(2):
        try:
            response = requests.post(
                f"{llm['base_url']}/api/generate",
                json=payload,
                timeout=timeout or settings.llm_timeout,
            )
            response.raise_for_status()
            return response.json()["response"]

        except requests.ConnectionError as exc:
            # Ollama is simply not running - retrying will not help.
            raise LLMUnavailableError(
                f"Cannot reach Ollama at {llm['base_url']}. "
                f"Start it with `ollama serve`."
            ) from exc

        except (requests.Timeout, requests.HTTPError) as exc:
            last_error = exc
            time.sleep(1.5)

    raise RuntimeError(f"LLM request failed: {last_error}")
