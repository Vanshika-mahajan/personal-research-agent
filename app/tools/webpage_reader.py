import re
from typing import List

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


def fetch_page_text(url: str, max_chars: int = 20000) -> str:
    """
    Like read_webpage, but never raises.

    Returns "" when the page is blocked, slow, not HTML or empty. That is
    normal for booking sites and social networks, so callers simply fall
    back to the search snippet.
    """

    try:
        text = read_webpage(url)
    except Exception:
        return ""

    text = re.sub(r"\s+", " ", text).strip()

    return text[:max_chars]


def fetch_headings(url: str, max_headings: int = 80) -> List[str]:
    """
    Headings (h2-h4) of a page, in order. Never raises.

    "Best hostels in Manali" style articles put each property in its own
    heading ("1. Zostel Manali"), so headings are where the names are.
    Returns [] when the page is blocked, slow or not HTML.
    """

    try:
        response = requests.get(
            url,
            timeout=15,
            headers={"User-Agent": "Mozilla/5.0"},
        )

        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")

        headings = []

        for tag in soup.find_all(["h2", "h3", "h4"]):
            text = re.sub(r"\s+", " ", tag.get_text(" ", strip=True)).strip()

            if text:
                headings.append(text)

            if len(headings) >= max_headings:
                break

        return headings

    except Exception:
        return []


_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'])")


def split_passages(
    text: str,
    target: int = 420,
    maximum: int = 700,
) -> List[str]:
    """
    Cut text into passages of roughly `target` characters on sentence
    boundaries. Newline-separated text (search snippets, pasted notes)
    keeps its own paragraph breaks.
    """

    if not text or not text.strip():
        return []

    blocks = [
        block.strip()
        for block in re.split(r"\n\s*\n|\n", text)
        if block.strip()
    ]

    passages: List[str] = []

    for block in blocks:
        sentences = _SENTENCE_SPLIT.split(block)

        current = ""

        for sentence in sentences:
            sentence = sentence.strip()

            if not sentence:
                continue

            # A single enormous "sentence" (menus, nav text) is chopped.
            while len(sentence) > maximum:
                passages.append(sentence[:maximum].strip())
                sentence = sentence[maximum:].strip()

            if current and len(current) + 1 + len(sentence) > target:
                passages.append(current)
                current = sentence
            else:
                current = f"{current} {sentence}".strip()

        if current:
            passages.append(current)

    return passages
