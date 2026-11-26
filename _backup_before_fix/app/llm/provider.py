import requests


def get_llm():
    """
    Return the local Ollama model configuration.
    """
    return {
        "base_url": "http://localhost:11434",
        "model": "llama3.2:3b",
    }


def generate_text(
    prompt: str,
    json_mode: bool = True,
    timeout: int = 120,
) -> str:
    """
    Send a prompt to the local Ollama model.

    json_mode=True:
        Used for structured LLM outputs such as
        evidence analysis and follow-up queries.

    json_mode=False:
        Used for normal text generation such as
        the final research report.
    """

    llm = get_llm()

    payload = {
        "model": llm["model"],
        "prompt": prompt,
        "stream": False,
        "temperature": 0,
    }

    if json_mode:
        payload["format"] = "json"

    response = requests.post(
        f"{llm['base_url']}/api/generate",
        json=payload,
        timeout=timeout,
    )

    response.raise_for_status()

    return response.json()["response"]