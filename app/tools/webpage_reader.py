import requests


def read_webpage(url: str) -> str:
    """
    Fetch a webpage and return its HTML.
    """

    if not url.strip():
        raise ValueError("URL cannot be empty.")

    response = requests.get(
        url,
        timeout=15,
        headers={
            "User-Agent": "Mozilla/5.0",
        },
    )

    response.raise_for_status()

    return response.text