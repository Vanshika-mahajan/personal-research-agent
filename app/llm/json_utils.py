"""Tolerant JSON parsing for LLM output."""

from __future__ import annotations

import json
import re
from typing import Any

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


def parse_json(text: str) -> Any:
    """
    Parse JSON that may be wrapped in markdown fences or surrounded by prose.

    Raises ValueError when no JSON object/array can be recovered, so callers
    can use a single `except Exception` fallback.
    """

    if text is None:
        raise ValueError("empty LLM response")

    cleaned = _FENCE.sub("", text.strip()).strip()

    if not cleaned:
        raise ValueError("empty LLM response")

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # Fall back to the outermost {...} or [...] block.
    for opener, closer in (("{", "}"), ("[", "]")):
        start = cleaned.find(opener)
        end = cleaned.rfind(closer)

        if start != -1 and end > start:
            try:
                return json.loads(cleaned[start : end + 1])
            except json.JSONDecodeError:
                continue

    raise ValueError("response did not contain valid JSON")
