import json

from app.llm.provider import generate_text


def generate_followup_queries_with_llm(
    question: str,
    evidence: list,
    missing_information: list,
    previous_queries: list,
) -> list[str]:
    """
    Ask the LLM to generate targeted follow-up
    search queries based on research gaps.
    """

    prompt = f"""
You are a research follow-up query generator.

Your job is to decide what the research agent should
search for next.

Original research question:
{question}

Information already found:
{json.dumps(evidence, indent=2)}

Information still missing:
{json.dumps(missing_information, indent=2)}

Search queries already used:
{json.dumps(previous_queries, indent=2)}

Generate 2 to 4 targeted follow-up web search queries.

Rules:
- Do NOT repeat previous queries.
- Each query must address a specific missing piece
  of information.
- Prefer factual and verifiable information.
- Prefer independent sources when source diversity
  is missing.
- Search for both positive and negative evidence
  when relevant.
- Do not invent facts.
- Do not answer the research question.
- Return ONLY valid JSON.

Return exactly this format:

{{
    "queries": [
        "specific search query 1",
        "specific search query 2",
        "specific search query 3"
    ]
}}
"""

    response = generate_text(prompt)

    try:
        data = json.loads(response)
        queries = data.get("queries", [])

        if not isinstance(queries, list):
            return []

        return [
            query.strip()
            for query in queries
            if isinstance(query, str)
            and query.strip()
        ]

    except json.JSONDecodeError:
        return []