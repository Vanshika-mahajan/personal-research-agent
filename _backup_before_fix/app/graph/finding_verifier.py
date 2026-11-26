import json
from typing import Any, Dict, List

from app.llm.provider import generate_text


def verify_findings_with_llm(
    question: str,
    findings: List[Dict[str, Any]],
    evidence: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Verify each finding against both:

    1. The available evidence.
    2. The actual research question.

    A finding is VERIFIED only when it is:
    - supported by the supplied evidence, and
    - relevant to what the user actually asked.

    The verifier does not create or rewrite findings.
    """

    if not findings:
        return []

    if not evidence:
        return [
            {
                **finding,
                "verification_status": "UNSUPPORTED",
                "verification_reason": (
                    "No evidence was available to verify this finding."
                ),
            }
            for finding in findings
        ]

    evidence_text = "\n".join(
        [
            (
                f"[{item.get('evidence_id', '')}] "
                f"{item.get('claim', '')}"
            )
            for item in evidence
        ]
    )

    findings_text = "\n".join(
        [
            (
                f"[{finding.get('finding_id', '')}] "
                f"{finding.get('statement', '')}"
            )
            for finding in findings
        ]
    )

    prompt = f"""
You are a strict research finding verifier.

Your job is to verify whether each finding should be accepted
as a valid answer to the user's research question.

USER RESEARCH QUESTION:
{question}

IMPORTANT:
A finding must satisfy BOTH conditions:

1. EVIDENCE SUPPORT
The supplied evidence must directly support the finding.

2. QUESTION RELEVANCE
The finding must directly help answer the user's research question.

Do NOT mark a finding VERIFIED merely because it is factually
true or appears in the evidence.

For example, if the question asks for:
"common guest complaints"

then findings about:
- hostel popularity
- positive experiences
- high ratings
- beautiful locations
- available facilities
- community atmosphere
- tourist attractions

should generally be marked IRRELEVANT unless they directly
identify a guest complaint or issue.

Likewise, if the question asks for complaints, a statement such as
"guests rate hostels 9.0/10" is NOT a complaint even if the
evidence clearly supports the rating.

Classify every finding as exactly one of:

VERIFIED
- Evidence directly supports the finding.
- The finding directly answers the research question.

UNSUPPORTED
- The finding is relevant to the question, but the evidence
  does not sufficiently support it.

IRRELEVANT
- The finding may be supported by the evidence, but it does
  not meaningfully answer the research question.

Return ONLY valid JSON.

Expected format:

{{
    "verifications": [
        {{
            "finding_id": "finding_1",
            "status": "VERIFIED",
            "reason": "Short explanation."
        }}
    ]
}}

FINDINGS:
{findings_text}

EVIDENCE:
{evidence_text}
"""

    try:
        raw_response = generate_text(prompt)
        parsed = json.loads(raw_response)

        verifications = parsed.get("verifications", [])

    except Exception as exc:
        print(
            f"FINDING VERIFIER ERROR: {exc}"
        )

        # Fail closed. If the verifier itself fails,
        # findings should not accidentally become verified.
        verifications = []

    verification_map = {
        item.get("finding_id"): item
        for item in verifications
        if isinstance(item, dict)
    }

    verified_findings: List[Dict[str, Any]] = []

    verified_count = 0
    unsupported_count = 0
    irrelevant_count = 0

    for finding in findings:
        finding_id = finding.get("finding_id")

        verification = verification_map.get(
            finding_id
        )

        if verification is None:
            status = "UNSUPPORTED"
            reason = (
                "The verifier did not return a valid "
                "verification result."
            )
        else:
            status = str(
                verification.get(
                    "status",
                    "UNSUPPORTED",
                )
            ).upper()

            reason = str(
                verification.get(
                    "reason",
                    "No verification reason provided.",
                )
            )

            if status not in {
                "VERIFIED",
                "UNSUPPORTED",
                "IRRELEVANT",
            }:
                status = "UNSUPPORTED"
                reason = (
                    "The verifier returned an invalid "
                    "verification status."
                )

        enriched_finding = {
            **finding,
            "verification_status": status,
            "verification_reason": reason,
        }

        verified_findings.append(
            enriched_finding
        )

        if status == "VERIFIED":
            verified_count += 1

        elif status == "UNSUPPORTED":
            unsupported_count += 1

        elif status == "IRRELEVANT":
            irrelevant_count += 1

    print("\nFINDING VERIFICATION")
    print(f"VERIFIED: {verified_count}")
    print(f"UNSUPPORTED: {unsupported_count}")
    print(f"IRRELEVANT: {irrelevant_count}")

    return verified_findings