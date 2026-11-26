from app.llm.provider import generate_text


def extract_claim(text: str) -> str:
    """
    Ask the local LLM to extract one factual claim
    from a research passage.
    """

    prompt = f"""
Read this research passage and extract ONE factual claim.

Return ONLY the claim.
Do not explain your answer.
Do not return NO_USEFUL_CLAIM.

If the passage contains any useful information about
a location, facility, experience, complaint, feature,
price, service, or other factual detail, extract it.

Passage:
{text}

Factual claim:
"""

    response = generate_text(prompt)

    return response.strip()