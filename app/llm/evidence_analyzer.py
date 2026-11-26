import json

from app.llm.provider import generate_text


def analyze_evidence_with_llm(
    question: str,
    evidence: list,
) -> list[dict]:
    """
    Analyze collected evidence and extract only findings
    directly supported by the supplied evidence.
    """

    prompt = f"""
You are a strict research evidence analyst.

Your job is to extract findings ONLY from the evidence
provided below.

Original research question:
{question}

Evidence:
{json.dumps(evidence, indent=2)}

IMPORTANT RULES:

1. The evidence is the ONLY source of truth.
2. Do NOT use your general knowledge.
3. Do NOT invent facts.
4. Do NOT assume facts that are not explicitly present.
5. Do NOT add information from the original question
   unless that information also appears in the evidence.
6. If the evidence contains only one claim, return only
   findings supported by that claim.
7. You MUST preserve claims that are explicitly stated
   in the evidence.
8. Never create additional complaints, features,
   policies, ratings, or facts.
9. If there is not enough evidence for a finding,
   do not create that finding.
10. If a claim is explicitly stated in the evidence,
    return that claim as a finding.

For each supported finding return:

- statement
- type
- confidence
- supporting_sources

The type must be one of:

POSITIVE
NEGATIVE
FACT
CONTRADICTION
OBSERVATION

Confidence rules:

- 1.0 = explicitly stated in the evidence
- 0.8 = strongly supported by the evidence
- 0.6 = reasonably supported
- Never give high confidence to an unsupported inference.

Return ONLY valid JSON.

Return exactly this structure:

{{
    "findings": [
        {{
            "statement": "The exact claim supported by the evidence.",
            "type": "POSITIVE",
            "confidence": 1.0,
            "supporting_sources": [
                "https://example.com"
            ]
        }}
    ]
}}

If the evidence does not support any reliable finding,
return:

{{
    "findings": []
}}
"""

    response = generate_text(prompt)

    try:
        data = json.loads(response)

    except json.JSONDecodeError:
        return []

    findings = data.get("findings", [])

    if not isinstance(findings, list):
        return []

    valid_findings = []

    for finding in findings:

        if not isinstance(finding, dict):
            continue

        statement = finding.get(
            "statement",
            "",
        )

        finding_type = finding.get(
            "type",
            "OBSERVATION",
        )

        confidence = finding.get(
            "confidence",
            0.5,
        )

        supporting_sources = finding.get(
            "supporting_sources",
            [],
        )

        if not isinstance(statement, str):
            continue

        if not statement.strip():
            continue

        allowed_types = {
            "POSITIVE",
            "NEGATIVE",
            "FACT",
            "CONTRADICTION",
            "OBSERVATION",
        }

        if finding_type not in allowed_types:
            finding_type = "OBSERVATION"

        try:
            confidence = float(confidence)
        except (TypeError, ValueError):
            confidence = 0.5

        confidence = max(
            0.0,
            min(
                1.0,
                confidence,
            ),
        )

        if not isinstance(
            supporting_sources,
            list,
        ):
            supporting_sources = []

        valid_findings.append(
            {
                "statement": statement.strip(),
                "type": finding_type,
                "confidence": confidence,
                "supporting_sources": [
                    source.strip()
                    for source in supporting_sources
                    if isinstance(source, str)
                    and source.strip()
                ],
            }
        )

    return valid_findings