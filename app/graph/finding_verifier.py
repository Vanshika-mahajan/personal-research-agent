import json
from typing import Any, Dict, List, Optional

from app.config import get_settings
from app.graph.evidence_utils import keywords
from app.llm.json_utils import parse_json
from app.llm.provider import generate_text


def _stem_set(text: str) -> set:
    # 5-letter stems so "complained" matches "complaints".
    return {word[:5] for word in keywords(text) if len(word) > 2}


def is_grounded(statement: str, claims: List[str]) -> bool:
    """
    Cheap, deterministic sanity check that a finding really shares
    vocabulary with the evidence it cites. A 3B model can say "VERIFIED"
    about a finding it invented - this catches that.
    """

    wanted = _stem_set(statement)

    if not wanted or not claims:
        return False

    available = set()

    for claim in claims:
        available |= _stem_set(claim)

    shared = wanted & available

    return len(shared) >= 2 or (len(shared) / len(wanted)) >= 0.4


def _relevance_rules(question: str, aspects: Optional[List[str]]) -> str:
    if aspects:
        listed = "\n".join(f"- {aspect}" for aspect in aspects)

        return f"""
The research question covers several aspects:
{listed}

A finding is RELEVANT when it answers ANY of these aspects
(a complaint, a thing guests praise, a reason guests choose the place,
a way it attracts or retains customers, a booking-experience problem,
a pricing fact, or something missing). Do NOT reject praise or
facilities merely because they are positive.
"""

    return """
Do NOT mark a finding VERIFIED merely because it is factually true or
appears in the evidence.

For example, if the question asks for "common guest complaints" then
findings about popularity, positive experiences, high ratings, beautiful
locations or available facilities should be marked IRRELEVANT unless they
directly identify a guest complaint or issue.
"""


def verify_findings_with_llm(
    question: str,
    findings: List[Dict[str, Any]],
    evidence: List[Dict[str, Any]],
    aspects: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """
    Verify each finding against both:

    1. The evidence it cites (and only that evidence - keeps prompts small).
    2. The actual research question.

    A finding is VERIFIED only when the LLM says so AND the statement shares
    real vocabulary with the cited evidence. The verifier does not create or
    rewrite findings, and it fails closed: any error means UNSUPPORTED.
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

    settings = get_settings()

    evidence_by_id = {
        item.get("evidence_id"): item for item in evidence
    }

    relevance_rules = _relevance_rules(question, aspects)

    verification_map: Dict[str, Dict[str, Any]] = {}

    batch_size = max(settings.verify_batch_size, 1)

    for start in range(0, len(findings), batch_size):
        batch = findings[start : start + batch_size]

        cited_ids: List[str] = []

        for finding in batch:
            for evidence_id in finding.get("evidence_ids", []):
                if evidence_id in evidence_by_id and evidence_id not in cited_ids:
                    cited_ids.append(evidence_id)

        evidence_text = "\n".join(
            f"[{evidence_id}] "
            f"{str(evidence_by_id[evidence_id].get('claim', ''))[:500]}"
            for evidence_id in cited_ids
        )

        findings_text = "\n".join(
            f"[{finding.get('finding_id', '')}] "
            f"{finding.get('statement', '')} "
            f"(cites: {', '.join(finding.get('evidence_ids', []))})"
            for finding in batch
        )

        prompt = f"""
You are a strict research finding verifier.

Your job is to verify whether each finding should be accepted
as a valid answer to the user's research question.

USER RESEARCH QUESTION:
{question}

A finding must satisfy BOTH conditions:

1. EVIDENCE SUPPORT
The cited evidence must directly support the finding.
Do not accept a finding that goes beyond what the evidence says.

2. QUESTION RELEVANCE
The finding must directly help answer the user's research question.
{relevance_rules}

Classify every finding as exactly one of:

VERIFIED
- Evidence directly supports the finding.
- The finding directly answers the research question.

UNSUPPORTED
- The finding is relevant, but the evidence does not sufficiently
  support it.

IRRELEVANT
- The finding may be supported, but it does not meaningfully answer
  the research question.

Return ONLY valid JSON:

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
            parsed = parse_json(generate_text(prompt))

            for item in parsed.get("verifications", []):
                if isinstance(item, dict) and item.get("finding_id"):
                    verification_map[item["finding_id"]] = item

        except Exception as exc:
            # Fail closed. If the verifier itself fails, findings must not
            # accidentally become verified.
            print(f"FINDING VERIFIER ERROR: {exc}")

    results: List[Dict[str, Any]] = []

    counts = {"VERIFIED": 0, "UNSUPPORTED": 0, "IRRELEVANT": 0}

    for finding in findings:
        verification = verification_map.get(finding.get("finding_id"))

        if verification is None:
            status = "UNSUPPORTED"
            reason = "The verifier did not return a valid verification result."

        else:
            status = str(verification.get("status", "UNSUPPORTED")).upper()
            reason = str(
                verification.get("reason", "No verification reason provided.")
            )

            if status not in counts:
                status = "UNSUPPORTED"
                reason = "The verifier returned an invalid verification status."

        if status == "VERIFIED":
            cited_claims = [
                str(evidence_by_id[evidence_id].get("claim", ""))
                for evidence_id in finding.get("evidence_ids", [])
                if evidence_id in evidence_by_id
            ]

            if not is_grounded(finding.get("statement", ""), cited_claims):
                status = "UNSUPPORTED"
                reason = (
                    "Downgraded: the statement does not share enough wording "
                    "with the evidence it cites."
                )

        counts[status] += 1

        results.append(
            {
                **finding,
                "verification_status": status,
                "verification_reason": reason,
            }
        )

    print("\nFINDING VERIFICATION")
    print(f"VERIFIED: {counts['VERIFIED']}")
    print(f"UNSUPPORTED: {counts['UNSUPPORTED']}")
    print(f"IRRELEVANT: {counts['IRRELEVANT']}")

    return results
