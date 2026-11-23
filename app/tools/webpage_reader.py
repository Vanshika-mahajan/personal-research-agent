import requests
from bs4 import BeautifulSoup


def read_webpage(url: str) -> str:
    """
    Fetch a webpage and return readable text.
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

    soup = BeautifulSoup(response.text, "html.parser")

    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    text = soup.get_text(separator=" ", strip=True)

    return text