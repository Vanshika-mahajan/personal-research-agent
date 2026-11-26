import json
from typing import Any, Dict, List

from app.graph.state import ResearchState
from app.llm.provider import generate_text
from app.schemas.research import ResearchPlan, ResearchQuery
from app.schemas.evidence import Evidence, Finding
from app.tools.web_search import search_web
from app.tools.webpage_reader import read_webpage


# ============================================================
# HELPERS
# ============================================================

def _safe_text(value: Any) -> str:
    """
    Convert a value to clean text.
    """
    if value is None:
        return ""

    return str(value).strip()


def _normalize_evidence_item(
    item: Any,
    index: int,
) -> Dict[str, Any]:
    """
    Normalize different evidence representations into
    a consistent dictionary.
    """

    if isinstance(item, Evidence):
        return {
            "evidence_id": f"evidence_{index}",
            "claim": item.claim,
            "source_title": item.source_title,
            "source_url": item.source_url,
            "source_type": item.source_type,
            "confidence": item.confidence,
        }

    if isinstance(item, dict):
        return {
            "evidence_id": (
                item.get("evidence_id")
                or f"evidence_{index}"
            ),
            "claim": (
                item.get("claim")
                or item.get("supporting_text")
                or item.get("content")
                or item.get("snippet")
                or ""
            ),
            "source_title": (
                item.get("source_title")
                or item.get("title")
                or "Unknown source"
            ),
            "source_url": (
                item.get("source_url")
                or item.get("url")
                or ""
            ),
            "source_type": item.get(
                "source_type",
                "web",
            ),
            "confidence": item.get(
                "confidence",
                0.5,
            ),
        }

    return {
        "evidence_id": f"evidence_{index}",
        "claim": _safe_text(item),
        "source_title": "Unknown source",
        "source_url": "",
        "source_type": "web",
        "confidence": 0.5,
    }


def _normalize_evidence(
    evidence: List[Any],
) -> List[Dict[str, Any]]:
    """
    Normalize the complete evidence collection.
    """

    normalized = []

    for index, item in enumerate(
        evidence,
        start=1,
    ):
        normalized.append(
            _normalize_evidence_item(
                item,
                index,
            )
        )

    return normalized


# ============================================================
# RESEARCH PLANNER
# ============================================================

def research_planner(
    state: ResearchState,
) -> Dict[str, Any]:
    """
    Convert the user's research question into
    focused web-search queries.

    The planner should identify:

    1. What entities need to be researched.
    2. What information is actually requested.
    3. What evidence is needed to answer the question.
    """

    question = state["question"].question

    prompt = f"""
You are an expert research planner.

Create a focused web research plan for the following question:

QUESTION:
{question}

Your goal is NOT to generate generic searches.

First identify:
1. What entities need to be researched.
2. What specific information about those entities the user wants.
3. What evidence would actually answer the question.

For questions asking for multiple entities, such as:

"Research 5 hostels in Manali and identify common guest complaints"

the research should be decomposed into:

- finding relevant hostels
- investigating guest complaints for those hostels
- finding recurring complaint patterns across them

IMPORTANT SEARCH RULES:

If the question asks for complaints, reviews, negative experiences,
or problems, prioritize queries containing terms such as:

- complaints
- negative reviews
- guest experiences
- problems
- issues
- dissatisfaction
- cleanliness
- staff
- noise
- bathrooms
- food
- service

Do NOT prioritize generic searches such as:

- best places
- positive experiences
- beautiful
- tourism
- general attractions
- generic facilities

unless they directly help answer the question.

Every query must have a clear research purpose.

Generate 6-10 focused queries.

Queries should be complementary rather than repetitive.

Priority MUST be an integer from 1 to 5.

Return ONLY valid JSON:

{{
    "queries": [
        {{
            "query": "search query",
            "purpose": "why this query is needed",
            "priority": 1
        }}
    ],
    "research_goals": [
        "goal 1",
        "goal 2"
    ],
    "expected_output": "description of the evidence-backed result"
}}
"""

    try:
        raw_response = generate_text(
            prompt
        )

        parsed = json.loads(
            raw_response
        )

        # LLMs sometimes produce priorities such as 6,
        # 7, 8, etc. Normalize them before Pydantic
        # validation because the schema allows only 1-5.
        for query in parsed.get(
            "queries",
            [],
        ):
            try:
                priority = int(
                    query.get(
                        "priority",
                        3,
                    )
                )
            except (
                TypeError,
                ValueError,
            ):
                priority = 3

            query["priority"] = max(
                1,
                min(
                    priority,
                    5,
                ),
            )

        plan = ResearchPlan.model_validate(
            parsed
        )

    except Exception as exc:
        print(
            f"RESEARCH PLANNER ERROR: {exc}"
        )

        # Deterministic complaint-focused fallback.
        plan = ResearchPlan(
            queries=[
                ResearchQuery(
                    query=(
                        f"{question} "
                        f"reviews complaints"
                    ),
                    purpose=(
                        "Find guest reviews that "
                        "explicitly describe complaints "
                        "and negative experiences."
                    ),
                    priority=5,
                ),
                ResearchQuery(
                    query=(
                        f"{question} "
                        f"negative reviews cleanliness "
                        f"noise staff"
                    ),
                    purpose=(
                        "Find recurring complaints involving "
                        "cleanliness, noise, and staff service."
                    ),
                    priority=4,
                ),
                ResearchQuery(
                    query=(
                        "Manali hostels guest "
                        "complaints reviews"
                    ),
                    purpose=(
                        "Find independent guest reports "
                        "describing problems experienced "
                        "at Manali hostels."
                    ),
                    priority=4,
                ),
            ],
            research_goals=[
                "Identify the hostels relevant to the question.",
                "Collect evidence describing actual guest complaints.",
                "Identify recurring complaints across independent sources.",
            ],
            expected_output=(
                "Evidence-backed common guest complaints "
                "across Manali hostels."
            ),
        )

    print("\nRESEARCH PLAN")
    print(
        f"GOALS: "
        f"{len(plan.research_goals)}"
    )

    for query in plan.queries:
        print(
            f"  → [{query.priority}] "
            f"{query.query}"
        )

    search_queries = [
        query.query
        for query in sorted(
            plan.queries,
            key=lambda item: item.priority,
            reverse=True,
        )
    ]

    return {
        "research_plan": plan,
        "search_queries": search_queries,
        "pending_queries": search_queries.copy(),
        "iteration": 0,
    }


# ============================================================
# RESEARCH
# ============================================================

def research(
    state: ResearchState,
) -> Dict[str, Any]:
    """
    Execute pending web searches and accumulate sources.
    """

    pending_queries = state.get(
        "pending_queries",
        [],
    )

    existing_sources = state.get(
        "sources",
        [],
    )

    sources = list(
        existing_sources
    )

    if not pending_queries:
        return {
            "sources": sources,
            "pending_queries": [],
        }

    for query in pending_queries:
        query = _safe_text(query)

        if not query:
            continue

        print(
            f"\nSEARCHING: {query}"
        )

        try:
            results = search_web(
                query,
                max_results=5,
            )

            for result in results:
                sources.append(
                    result
                )

        except Exception as exc:
            print(
                f"SEARCH ERROR: {exc}"
            )

    print(
        f"\nTOTAL SOURCES: "
        f"{len(sources)}"
    )

    return {
        "sources": sources,
        "pending_queries": [],
        "iteration": (
            state.get(
                "iteration",
                0,
            )
            + 1
        ),
    }


# ============================================================
# EVIDENCE EXTRACTION
# ============================================================

def extract_evidence(
    state: ResearchState,
) -> Dict[str, Any]:
    """
    Extract evidence from collected search results.

    Only reasonably substantive text is retained.
    """

    sources = state.get(
        "sources",
        [],
    )

    evidence: List[Evidence] = []

    irrelevant_phrases = [
        "cookie policy",
        "privacy policy",
        "terms of use",
        "terms and conditions",
        "sign in",
        "log in",
        "subscribe",
        "all rights reserved",
        "accept cookies",
        "enable javascript",
    ]

    for source_index, source in enumerate(
        sources,
        start=1,
    ):
        if isinstance(
            source,
            dict,
        ):
            title = _safe_text(
                source.get(
                    "title"
                )
            )

            url = _safe_text(
                source.get(
                    "url"
                )
            )

            text = _safe_text(
                source.get(
                    "snippet"
                )
                or source.get(
                    "content"
                )
                or source.get(
                    "claim"
                )
            )

            source_type = _safe_text(
                source.get(
                    "source_type",
                    "web",
                )
            )

        else:
            title = _safe_text(
                getattr(
                    source,
                    "title",
                    "",
                )
            )

            url = _safe_text(
                getattr(
                    source,
                    "url",
                    "",
                )
            )

            text = _safe_text(
                getattr(
                    source,
                    "snippet",
                    "",
                )
            )

            source_type = _safe_text(
                getattr(
                    source,
                    "source_type",
                    "web",
                )
            )

        if not text:
            continue

        paragraphs = [
            paragraph.strip()
            for paragraph in text.split(
                "\n"
            )
            if paragraph.strip()
        ]

        if not paragraphs:
            paragraphs = [
                text
            ]

        for paragraph in paragraphs:
            if len(paragraph) < 40:
                continue

            lower = paragraph.lower()

            if any(
                phrase in lower
                for phrase in irrelevant_phrases
            ):
                continue

            evidence_id = (
                f"evidence_{len(evidence) + 1}"
            )

            evidence.append(
                Evidence(
                    claim=paragraph[
                        :1000
                    ],
                    source_title=(
                        title
                        or "Unknown source"
                    ),
                    source_url=url,
                    source_type=(
                        source_type
                        or "web"
                    ),
                    confidence=0.5,
                )
            )

    print(
        f"EVIDENCE EXTRACTED: "
        f"{len(evidence)}"
    )

    normalized_evidence = _normalize_evidence(
        evidence
    )

    return {
        "evidence": normalized_evidence
    }


# ============================================================
# FINDING GENERATION
# ============================================================

def analyze_evidence_with_llm(
    state: ResearchState,
) -> Dict[str, Any]:
    """
    Generate research findings from the collected evidence.

    Findings must directly answer the research question
    and must be grounded in explicit evidence.

    The model is allowed to return zero findings when
    the evidence does not support a valid conclusion.
    """

    question = state[
        "question"
    ].question

    evidence = _normalize_evidence(
        state.get(
            "evidence",
            [],
        )
    )

    if not evidence:
        print(
            "\nLLM ANALYZING EVIDENCE..."
        )

        print(
            "NO EVIDENCE AVAILABLE"
        )

        return {
            "findings": []
        }

    evidence_lines = []

    for item in evidence:
        evidence_lines.append(
            (
                f"[{item['evidence_id']}]\n"
                f"Claim: {item['claim']}\n"
                f"Source: {item['source_title']}\n"
                f"URL: {item['source_url']}"
            )
        )

    evidence_text = "\n\n".join(
        evidence_lines
    )

    prompt = f"""
You are an evidence-grounded research analyst.

USER RESEARCH QUESTION:
{question}

AVAILABLE EVIDENCE:
{evidence_text}

Your task is to generate findings that directly answer
the user's research question.

STRICT RULES:

1. Every finding MUST be directly supported by one or more
   supplied evidence items.

2. Every finding MUST directly answer the user's question.

3. Do NOT generate generic facts merely because they appear
   interesting.

4. Do NOT generate findings about:
   - popularity
   - general quality
   - ratings
   - prices
   - facilities
   - locations
   - positive experiences
   - source/platform reputation

   unless the research question specifically asks for them.

5. If the question asks about guest complaints, generate
   findings ONLY when the evidence explicitly describes:
   - a complaint
   - a problem
   - a negative experience
   - dissatisfaction
   - a recurring issue

6. Do NOT treat the name of a review platform as evidence.

   For example:
   "Hostelworld" appearing in evidence does NOT support:
   "Most Hostelworld reviews are negative."

7. Do NOT infer an aggregate pattern from a single review.

8. Do NOT invent:
   - statistics
   - percentages
   - ratings
   - prices
   - frequencies
   - counts

9. Do NOT use outside knowledge.

10. If the evidence does not contain enough information
    to support a meaningful finding, return fewer findings.

11. It is better to return ZERO valid findings than
    to invent an irrelevant finding.

12. Prefer findings that identify recurring problems
    across multiple independent evidence items.

13. Every finding MUST include evidence IDs that directly
    support the finding.

For a question about common guest complaints, good findings
would look like:

"Multiple guests reported cleanliness issues in bathrooms."

"Noise was mentioned as a recurring problem by guests
at several hostels."

Bad findings would look like:

"Hostels in Manali are highly rated."

"Most hostels have shared lounges."

"Hostelworld reviews are negative."

"Zostel Manali is popular."

Return ONLY valid JSON.

Expected format:

{{
    "findings": [
        {{
            "type": "COMPLAINT",
            "statement": "Specific evidence-backed finding.",
            "evidence_ids": [
                "evidence_1",
                "evidence_4"
            ],
            "confidence": 0.85
        }}
    ]
}}

If there are no valid findings:

{{
    "findings": []
}}
"""

    print(
        "\nLLM ANALYZING EVIDENCE..."
    )

    try:
        raw_response = generate_text(
            prompt
        )

        parsed = json.loads(
            raw_response
        )

        raw_findings = parsed.get(
            "findings",
            [],
        )

        findings = []

        for index, finding in enumerate(
            raw_findings,
            start=1,
        ):
            if not isinstance(
                finding,
                dict,
            ):
                continue

            statement = _safe_text(
                finding.get(
                    "statement"
                )
            )

            if not statement:
                continue

            evidence_ids = finding.get(
                "evidence_ids",
                [],
            )

            if not isinstance(
                evidence_ids,
                list,
            ):
                evidence_ids = []

            evidence_ids = [
                _safe_text(
                    item
                )
                for item in evidence_ids
                if _safe_text(
                    item
                )
            ]

            # Never accept a finding that has
            # no evidence references.
            if not evidence_ids:
                continue

            finding_type = (
                _safe_text(
                    finding.get(
                        "type",
                        "OBSERVATION",
                    )
                ).upper()
            )

            try:
                confidence = float(
                    finding.get(
                        "confidence",
                        0.5,
                    )
                )

            except (
                TypeError,
                ValueError,
            ):
                confidence = 0.5

            confidence = max(
                0.0,
                min(
                    confidence,
                    1.0,
                ),
            )

            findings.append(
                {
                    "finding_id": (
                        f"finding_{index}"
                    ),
                    "type": finding_type,
                    "statement": statement,
                    "evidence_ids": evidence_ids,
                    "confidence": confidence,
                }
            )

        print(
            f"LLM FINDINGS GENERATED: "
            f"{len(findings)}"
        )

        for finding in findings:
            print(
                "  → "
                f"[{finding['type']}] "
                f"{finding['statement']}"
            )

        return {
            "findings": findings
        }

    except Exception as exc:
        print(
            f"LLM ANALYSIS ERROR: "
            f"{exc}"
        )

        return {
            "findings": []
        }


# ============================================================
# FINDING VERIFICATION
# ============================================================

def verify_findings(
    state: ResearchState,
) -> Dict[str, Any]:
    """
    Verify generated findings against both:

    1. Evidence support.
    2. Research-question relevance.
    """

    from app.graph.finding_verifier import (
        verify_findings_with_llm,
    )

    question = state[
        "question"
    ].question

    findings = state.get(
        "findings",
        [],
    )

    evidence = _normalize_evidence(
        state.get(
            "evidence",
            [],
        )
    )

    if not findings:
        print(
            "\nFINDING VERIFICATION"
        )

        print(
            "NO FINDINGS TO VERIFY"
        )

        return {
            "verified_findings": []
        }

    verified_findings = (
        verify_findings_with_llm(
            question=question,
            findings=findings,
            evidence=evidence,
        )
    )

    return {
        "verified_findings": (
            verified_findings
        )
    }


# ============================================================
# QUALITY CHECK
# ============================================================

def quality_check(
    state: ResearchState,
) -> Dict[str, Any]:
    """
    Evaluate whether the collected research is strong enough
    to produce a final answer.
    """

    evidence = state.get(
        "evidence",
        [],
    )

    verified_findings = state.get(
        "verified_findings",
        [],
    )

    search_queries = state.get(
        "search_queries",
        [],
    )

    unique_sources = set()

    for item in evidence:
        url = _safe_text(
            item.get(
                "source_url",
                "",
            )
        )

        if url:
            unique_sources.add(
                url
            )

    verified_count = sum(
        1
        for finding in verified_findings
        if finding.get(
            "verification_status"
        ) == "VERIFIED"
    )

    evidence_score = min(
        len(evidence) / 10,
        1.0,
    )

    finding_score = min(
        verified_count / 5,
        1.0,
    )

    source_diversity_score = min(
        len(unique_sources) / 3,
        1.0,
    )

    review_query_count = sum(
        1
        for query in search_queries
        if any(
            keyword in query.lower()
            for keyword in [
                "review",
                "complaint",
                "experience",
                "guest",
                "negative",
                "issue",
                "problem",
            ]
        )
    )

    review_coverage_score = min(
        review_query_count / 3,
        1.0,
    )

    final_score = (
        0.35 * evidence_score
        + 0.25 * finding_score
        + 0.20 * source_diversity_score
        + 0.20 * review_coverage_score
    )

    missing_information = []

    if not evidence:
        missing_information.append(
            "Research found no usable evidence."
        )

    if len(unique_sources) < 3:
        missing_information.append(
            "Research needs more independent sources."
        )

    if verified_count < 3:
        missing_information.append(
            "Research needs more verified findings."
        )

    if review_query_count < 3:
        missing_information.append(
            "Research needs more review-focused queries."
        )

    if (
        final_score >= 0.70
        and not missing_information
    ):
        decision = (
            "RESEARCH SUFFICIENT"
        )

    else:
        decision = (
            "RESEARCH INSUFFICIENT"
        )

    print(
        "\n======================================================="
    )

    print(
        f"RESEARCH ITERATION: "
        f"{state.get('iteration', 0)}"
    )

    print(
        f"SOURCES: "
        f"{len(state.get('sources', []))}"
    )

    print(
        f"EVIDENCE: "
        f"{len(evidence)}"
    )

    print(
        f"RAW FINDINGS: "
        f"{len(state.get('findings', []))}"
    )

    print(
        f"VERIFIED FINDINGS: "
        f"{verified_count}"
    )

    print(
        "======================================================="
    )

    print(
        f"UNIQUE SOURCES: "
        f"{len(unique_sources)}"
    )

    print(
        f"REVIEW-RELATED SOURCES: "
        f"{review_query_count}"
    )

    print(
        f"EVIDENCE SCORE: "
        f"{evidence_score:.2f}"
    )

    print(
        f"VERIFIED FINDING SCORE: "
        f"{finding_score:.2f}"
    )

    print(
        f"SOURCE DIVERSITY SCORE: "
        f"{source_diversity_score:.2f}"
    )

    print(
        f"REVIEW COVERAGE SCORE: "
        f"{review_coverage_score:.2f}"
    )

    print(
        f"FINAL QUALITY SCORE: "
        f"{final_score:.2f}"
    )

    if missing_information:
        print(
            "MISSING INFORMATION:"
        )

        for item in missing_information:
            print(
                f"  - {item}"
            )

    print(
        f"DECISION: {decision}"
    )

    return {
        "missing_information": (
            missing_information
        ),
        "evidence_score": (
            final_score
        ),
        "quality_decision": (
            decision
        ),
    }


# ============================================================
# CONDITIONAL ROUTING
# ============================================================

def should_continue(
    state: ResearchState,
) -> str:
    """
    Decide whether research should continue
    or move to insights/report generation.
    """

    if (
        state.get(
            "quality_decision"
        )
        == "RESEARCH SUFFICIENT"
    ):
        return "insights"

    max_iterations = state.get(
        "max_iterations",
        2,
    )

    iteration = state.get(
        "iteration",
        0,
    )

    if iteration >= max_iterations:
        return "insights"

    return "followup"


# ============================================================
# FOLLOW-UP QUERY GENERATION
# ============================================================

def generate_followup_queries(
    state: ResearchState,
) -> Dict[str, Any]:
    """
    Generate additional queries based on missing information.
    """

    question = state[
        "question"
    ].question

    missing_information = state.get(
        "missing_information",
        [],
    )

    existing_queries = state.get(
        "search_queries",
        [],
    )

    missing_text = "\n".join(
        f"- {item}"
        for item in missing_information
    )

    prompt = f"""
You are a research follow-up query generator.

ORIGINAL QUESTION:
{question}

MISSING INFORMATION:
{missing_text}

EXISTING QUERIES:
{json.dumps(existing_queries, indent=2)}

Generate 2-3 NEW search queries that directly address
the missing information.

The queries must stay tightly focused on the original
research question.

If the question asks for complaints, the queries should
specifically seek complaints, negative reviews, problems,
or guest experiences.

Do NOT generate queries about unrelated positive information.

Return ONLY valid JSON:

{{
    "queries": [
        "query 1",
        "query 2",
        "query 3"
    ]
}}
"""

    try:
        raw_response = generate_text(
            prompt
        )

        parsed = json.loads(
            raw_response
        )

        queries = parsed.get(
            "queries",
            [],
        )

        queries = [
            _safe_text(
                query
            )
            for query in queries
            if _safe_text(
                query
            )
        ]

    except Exception as exc:
        print(
            f"FOLLOW-UP QUERY ERROR: "
            f"{exc}"
        )

        queries = [
            (
                "Manali hostel guest "
                "complaints negative reviews"
            ),
            (
                "Manali hostels cleanliness "
                "noise staff complaints"
            ),
            (
                "Manali hostel negative "
                "guest experiences reviews"
            ),
        ]

    print(
        "\nGENERATED FOLLOW-UP QUERIES:"
    )

    for query in queries:
        print(
            f"  → {query}"
        )

    return {
        "pending_queries": queries,
        "search_queries": (
            existing_queries
            + queries
        ),
    }


# ============================================================
# INSIGHTS
# ============================================================

def generate_insights(
    state: ResearchState,
) -> Dict[str, Any]:
    """
    Generate higher-level insights only from
    verified findings.
    """

    question = state[
        "question"
    ].question

    verified_findings = [
        finding
        for finding in state.get(
            "verified_findings",
            [],
        )
        if finding.get(
            "verification_status"
        ) == "VERIFIED"
    ]

    if not verified_findings:
        return {
            "insights": [
                (
                    "The available evidence was "
                    "insufficient to establish "
                    "reliable findings for the "
                    "research question."
                )
            ]
        }

    findings_text = "\n".join(
        [
            (
                f"- {finding.get('statement', '')} "
                f"(confidence: "
                f"{finding.get('confidence', 0.5)})"
            )
            for finding in verified_findings
        ]
    )

    prompt = f"""
You are a research synthesis analyst.

QUESTION:
{question}

VERIFIED FINDINGS:
{findings_text}

Generate 2-4 concise insights that synthesize
the verified findings.

Rules:

- Use ONLY the verified findings.
- Do not introduce outside knowledge.
- Do not invent statistics.
- Do not turn unrelated findings into conclusions.
- Highlight recurring patterns, differences,
  or important implications.
- If the evidence is weak, say so.

Return ONLY valid JSON:

{{
    "insights": [
        "Insight 1",
        "Insight 2"
    ]
}}
"""

    try:
        raw_response = generate_text(
            prompt
        )

        parsed = json.loads(
            raw_response
        )

        insights = [
            _safe_text(
                item
            )
            for item in parsed.get(
                "insights",
                []
            )
            if _safe_text(
                item
            )
        ]

    except Exception as exc:
        print(
            f"INSIGHT GENERATION ERROR: "
            f"{exc}"
        )

        insights = [
            finding.get(
                "statement",
                "",
            )
            for finding in verified_findings
            if finding.get(
                "statement"
            )
        ]

    return {
        "insights": insights
    }


# ============================================================
# REPORT
# ============================================================

def generate_report(
    state: ResearchState,
) -> Dict[str, Any]:
    """
    Generate the final research report using
    only verified findings and generated insights.
    """

    question = state[
        "question"
    ].question

    verified_findings = [
        finding
        for finding in state.get(
            "verified_findings",
            [],
        )
        if finding.get(
            "verification_status"
        ) == "VERIFIED"
    ]

    insights = state.get(
        "insights",
        [],
    )

    evidence = _normalize_evidence(
        state.get(
            "evidence",
            [],
        )
    )

    if not verified_findings:
        report = (
            f"# Research Report\n\n"
            f"## Question\n\n"
            f"{question}\n\n"
            f"## Result\n\n"
            f"The available research evidence "
            f"was insufficient to establish "
            f"reliable findings for this question.\n\n"
            f"Additional targeted research is "
            f"required before drawing conclusions."
        )

        print(
            "\nGENERATING FINAL REPORT..."
        )

        print(
            "FINAL REPORT GENERATED"
        )

        return {
            "report": report
        }

    findings_text = "\n".join(
        [
            (
                f"- {finding.get('statement', '')}"
            )
            for finding in verified_findings
        ]
    )

    insights_text = "\n".join(
        [
            f"- {item}"
            for item in insights
            if item
        ]
    )

    sources = []

    seen_urls = set()

    for item in evidence:
        url = _safe_text(
            item.get(
                "source_url",
                "",
            )
        )

        title = _safe_text(
            item.get(
                "source_title",
                "",
            )
        )

        if (
            url
            and url not in seen_urls
        ):
            seen_urls.add(
                url
            )

            sources.append(
                f"- {title}: {url}"
            )

    sources_text = "\n".join(
        sources
    )

    prompt = f"""
You are a research report writer.

QUESTION:
{question}

VERIFIED FINDINGS:
{findings_text}

INSIGHTS:
{insights_text}

SOURCES:
{sources_text}

Write a concise evidence-backed research report.

Use this structure:

# Research Report

## Research Question

## Key Findings

## Insights

## Sources

## Limitations

Rules:

- Use only the verified findings.
- Do not introduce outside facts.
- Do not invent statistics.
- Clearly distinguish findings from insights.
- Mention limitations when evidence is incomplete.
"""

    print(
        "\nGENERATING FINAL REPORT..."
    )

    try:
        report = generate_text(
            prompt
        )

    except Exception as exc:
        print(
            f"REPORT GENERATION ERROR: "
            f"{exc}"
        )

        report = (
            "# Research Report\n\n"
            f"## Research Question\n\n"
            f"{question}\n\n"
            f"## Key Findings\n\n"
            f"{findings_text}\n\n"
            f"## Insights\n\n"
            f"{insights_text}\n\n"
            f"## Sources\n\n"
            f"{sources_text}\n\n"
            f"## Limitations\n\n"
            f"The report is limited to the "
            f"verified evidence collected "
            f"during the research process."
        )

    print(
        "FINAL REPORT GENERATED"
    )

    return {
        "report": report
    }


# ============================================================
# COMPATIBILITY ALIASES
# ============================================================

research_node = research

build_report = generate_report