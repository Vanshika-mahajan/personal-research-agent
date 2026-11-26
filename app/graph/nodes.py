"""
LangGraph nodes.

planner -> research -> extract_evidence -> analyze -> verify -> quality_check
        -> (follow-up queries -> research ...)  or  insights -> report

What changed compared with the first version
--------------------------------------------
* planner      : hand-written queries (property / topic mode) skip the LLM;
                 fallback queries are built from the question, not hard-coded
                 to "Manali hostels".
* research     : de-duplicates URLs and actually reads pages (not just search
                 snippets); instagram / google maps are kept as snippets.
* evidence     : passages are ranked, filtered to the right venue and capped,
                 so a small model is not flooded.
* analyze      : works in batches, validates evidence ids, tags a category.
* verify       : see finding_verifier.py (grounding check, small prompts).
* quality      : review-coverage is only demanded for review-type questions.
* report       : built deterministically (findings + links); the LLM only
                 contributes an optional short summary, in prose mode.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List

from app.config import get_settings
from app.graph.evidence_utils import build_evidence
from app.graph.report_builder import build_report_markdown
from app.graph.state import ResearchState
from app.graph.taxonomy import CATEGORIES, normalise_category
from app.llm.json_utils import parse_json
from app.llm.provider import generate_text
from app.schemas.research import ResearchPlan, ResearchQuery
from app.schemas.source import SearchResult
from app.tools.source_types import classify_url, is_walled
from app.tools.web_search import search_web
from app.tools.webpage_reader import fetch_page_text

REVIEW_WORDS = (
    "review", "complaint", "complain", "experience", "guest", "negative",
    "issue", "problem", "customer", "feedback", "opinion", "praise",
)


# ============================================================
# HELPERS
# ============================================================

def _safe_text(value: Any) -> str:
    if value is None:
        return ""

    return str(value).strip()


def _question(state: ResearchState):
    return state.get("question")


def _question_text(state: ResearchState) -> str:
    question = _question(state)

    return question.question if question else ""


def _mode(state: ResearchState) -> str:
    question = _question(state)

    return getattr(question, "mode", "general") if question else "general"


def _aspects(state: ResearchState) -> List[str]:
    question = _question(state)

    return list(getattr(question, "aspects", []) or []) if question else []


def _is_review_question(state: ResearchState) -> bool:
    if _mode(state) == "property":
        return True

    text = _question_text(state).lower()

    return any(word in text for word in REVIEW_WORDS)


def _norm_url(url: str) -> str:
    url = _safe_text(url).lower()

    for prefix in ("https://", "http://"):
        if url.startswith(prefix):
            url = url[len(prefix):]

    if url.startswith("www."):
        url = url[4:]

    return url.rstrip("/")


def _get(source: Any, key: str, default: Any = "") -> Any:
    if isinstance(source, dict):
        return source.get(key, default) or default

    return getattr(source, key, default) or default


def _normalize_evidence_item(item: Any, index: int) -> Dict[str, Any]:
    """Normalize different evidence representations into one dict shape."""

    if hasattr(item, "claim") and not isinstance(item, dict):
        return {
            "evidence_id": f"evidence_{index}",
            "claim": item.claim,
            "source_title": item.source_title,
            "source_url": item.source_url,
            "source_type": item.source_type,
            "platform": "",
            "origin": "snippet",
            "confidence": item.confidence,
        }

    if isinstance(item, dict):
        return {
            "evidence_id": item.get("evidence_id") or f"evidence_{index}",
            "claim": (
                item.get("claim")
                or item.get("supporting_text")
                or item.get("content")
                or item.get("snippet")
                or ""
            ),
            "source_title": (
                item.get("source_title") or item.get("title") or "Unknown source"
            ),
            "source_url": item.get("source_url") or item.get("url") or "",
            "source_type": item.get("source_type", "web"),
            "platform": item.get("platform", ""),
            "origin": item.get("origin", "snippet"),
            "confidence": item.get("confidence", 0.5),
        }

    return {
        "evidence_id": f"evidence_{index}",
        "claim": _safe_text(item),
        "source_title": "Unknown source",
        "source_url": "",
        "source_type": "web",
        "platform": "",
        "origin": "snippet",
        "confidence": 0.5,
    }


def _normalize_evidence(evidence: List[Any]) -> List[Dict[str, Any]]:
    return [
        _normalize_evidence_item(item, index)
        for index, item in enumerate(evidence, start=1)
    ]


def _fallback_queries(state: ResearchState) -> List[str]:
    """Queries built from the question itself - works for any topic."""

    question = _question(state)
    text = _question_text(state)[:120]

    if question and question.mode == "property" and question.subject:
        base = f"{question.subject} {question.place}".strip()

        return [
            f"{base} reviews",
            f"{base} complaints negative reviews",
            f"{base} guest experience",
        ]

    queries = [text]

    if _is_review_question(state):
        queries += [
            f"{text} reviews",
            f"{text} complaints problems",
            f"{text} guest experiences",
        ]
    else:
        queries += [f"{text} latest", f"{text} comparison", f"{text} statistics"]

    return queries


# ============================================================
# RESEARCH PLANNER
# ============================================================

def research_planner(state: ResearchState) -> Dict[str, Any]:
    """
    Convert the research question into focused web-search queries.

    * seed_queries given (property / topic mode)  -> use them as they are.
    * otherwise the LLM plans 6-10 queries; if that fails we fall back to
      queries derived from the question.
    """

    question_obj = state["question"]
    question = question_obj.question

    seed = [
        _safe_text(query)
        for query in getattr(question_obj, "seed_queries", [])
        if _safe_text(query)
    ]

    if seed:
        plan = ResearchPlan(
            queries=[
                ResearchQuery(
                    query=query,
                    purpose="Hand-written query for this research mode.",
                    priority=max(5 - index // 3, 2),
                )
                for index, query in enumerate(seed)
            ],
            research_goals=list(getattr(question_obj, "aspects", []) or []),
            expected_output="Evidence-backed findings",
        )

        search_queries = seed.copy()

    else:
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

For questions asking for multiple entities, decompose the research into:
- finding the relevant entities
- investigating the specific information requested for each of them
- finding recurring patterns across them

If the question asks for complaints, reviews, negative experiences or
problems, prioritise queries containing terms such as: complaints,
negative reviews, guest experiences, problems, issues, cleanliness, staff,
noise, bathrooms, food, service.

Do NOT prioritise generic searches (best places, tourism, general
attractions) unless they directly help answer the question.

Every query must have a clear research purpose.

Generate 6-10 focused, complementary queries (not repetitive).

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
    "research_goals": ["goal 1", "goal 2"],
    "expected_output": "description of the evidence-backed result"
}}
"""

        try:
            parsed = parse_json(generate_text(prompt))

            # LLMs sometimes produce priorities such as 6, 7, 8 ...
            # Normalise before validation (schema allows 1-5).
            for query in parsed.get("queries", []):
                try:
                    priority = int(query.get("priority", 3))
                except (TypeError, ValueError):
                    priority = 3

                query["priority"] = max(1, min(priority, 5))

            plan = ResearchPlan.model_validate(parsed)

            if not plan.queries:
                raise ValueError("planner returned no queries")

        except Exception as exc:
            print(f"RESEARCH PLANNER ERROR: {exc}")

            plan = ResearchPlan(
                queries=[
                    ResearchQuery(
                        query=query,
                        purpose="Fallback query derived from the question.",
                        priority=5 - min(index, 2),
                    )
                    for index, query in enumerate(_fallback_queries(state))
                ],
                research_goals=[
                    "Find evidence that directly answers the question.",
                    "Identify patterns across independent sources.",
                ],
                expected_output="Evidence-backed answer to the question.",
            )

        search_queries = [
            query.query
            for query in sorted(
                plan.queries, key=lambda item: item.priority, reverse=True
            )
        ]

    print("\nRESEARCH PLAN")
    print(f"GOALS: {len(plan.research_goals)}")

    for query in search_queries:
        print(f"  → {query}")

    return {
        "research_plan": plan,
        "search_queries": search_queries,
        "pending_queries": search_queries.copy(),
        "iteration": 0,
    }


# ============================================================
# RESEARCH
# ============================================================

def _search_with_retry(query: str, max_results: int, official: List[str]):
    """search_web already retries with a pause; a final failure just means no results."""

    try:
        return search_web(
            query,
            max_results=max_results,
            official_domains=official,
        )
    except Exception as exc:
        print(f"SEARCH ERROR ({exc.__class__.__name__}): {query}")

    return []


def research(state: ResearchState) -> Dict[str, Any]:
    """
    Execute pending web searches, de-duplicate URLs and read the pages.

    Pages that need a login or JavaScript (Instagram, Google Maps ...) are
    NOT downloaded - their search snippet is kept and the coverage table in
    the report says so honestly.
    """

    settings = get_settings()

    question = _question(state)
    official = list(getattr(question, "official_domains", []) or [])

    pending_queries = state.get("pending_queries", [])
    iteration = state.get("iteration", 0)

    sources = list(state.get("sources", []))

    if not pending_queries and not (question and iteration == 0):
        return {"sources": sources, "pending_queries": []}

    seen = {_norm_url(_get(source, "url")) for source in sources}

    to_fetch: List[SearchResult] = []

    # URLs the user gave us (official website ...) are read first, once.
    if question and iteration == 0:
        for url in getattr(question, "seed_urls", []) or []:
            key = _norm_url(url)

            if not key or key in seen:
                continue

            seen.add(key)

            source_type, platform = classify_url(url, official)

            result = SearchResult(
                title=url,
                url=url,
                snippet="",
                source_type=source_type,
                platform=platform,
            )

            sources.append(result)

            if not is_walled(source_type):
                to_fetch.append(result)

    for index, query in enumerate(pending_queries):
        query = _safe_text(query)

        if not query:
            continue

        print(f"\nSEARCHING: {query}")

        results = _search_with_retry(
            query, settings.results_per_query, official
        )

        taken = 0

        for result in results:
            key = _norm_url(result.url)

            if not key or key in seen:
                continue

            seen.add(key)
            sources.append(result)

            if (
                settings.fetch_pages
                and taken < settings.max_pages_per_query
                and not is_walled(result.source_type)
            ):
                to_fetch.append(result)
                taken += 1

        if settings.search_delay and index < len(pending_queries) - 1:
            time.sleep(settings.search_delay)

    if to_fetch and settings.fetch_pages:
        print(f"\nREADING {len(to_fetch)} PAGES...")

        with ThreadPoolExecutor(max_workers=4) as pool:
            texts = list(
                pool.map(
                    lambda item: fetch_page_text(
                        item.url, settings.page_max_chars
                    ),
                    to_fetch,
                )
            )

        read = 0

        for item, text in zip(to_fetch, texts):
            if text:
                item.content = text
                read += 1

        print(f"PAGES READ: {read}/{len(to_fetch)}")

    print(f"\nTOTAL SOURCES: {len(sources)}")

    return {
        "sources": sources,
        "pending_queries": [],
        "iteration": iteration + 1,
    }


# ============================================================
# EVIDENCE EXTRACTION
# ============================================================

def extract_evidence(state: ResearchState) -> Dict[str, Any]:
    """
    Turn sources (+ any manual notes) into ranked, capped evidence passages.
    """

    settings = get_settings()

    question = _question(state)
    mode = _mode(state)

    focus_text = " ".join([_question_text(state), *_aspects(state)])

    evidence = build_evidence(
        state.get("sources", []),
        focus_text=focus_text,
        subject=getattr(question, "subject", "") if mode == "property" else "",
        place=getattr(question, "place", "") if question else "",
        manual=state.get("manual_evidence", []),
        max_total=settings.max_evidence,
        per_source=settings.evidence_per_source,
        use_profile_lexicon=_is_review_question(state),
    )

    print(f"EVIDENCE EXTRACTED: {len(evidence)}")

    return {"evidence": _normalize_evidence(evidence)}


# ============================================================
# FINDING GENERATION
# ============================================================

def _norm_evidence_id(value: Any) -> str:
    text = _safe_text(value).lower()

    if text.isdigit():
        return f"evidence_{text}"

    if text.startswith("evidence") and text[8:].lstrip("_ -").isdigit():
        return f"evidence_{text[8:].lstrip('_ -')}"

    return text


def _analysis_prompt(
    question: str,
    aspects: List[str],
    batch: List[Dict[str, Any]],
) -> str:
    evidence_text = "\n\n".join(
        (
            f"[{item['evidence_id']}]\n"
            f"Claim: {str(item['claim'])[:450]}\n"
            f"Source: {item['source_title']} "
            f"({item.get('platform') or item.get('source_type', 'web')})\n"
            f"URL: {item['source_url']}"
        )
        for item in batch
    )

    categories = "\n".join(
        f"- {name}: {definition}"
        for name, (_, definition) in CATEGORIES.items()
    )

    if aspects:
        scope = (
            "The question covers these aspects, and findings about ANY of "
            "them are in scope:\n" + "\n".join(f"- {a}" for a in aspects)
        )
    else:
        scope = "Only findings that directly answer the question are in scope."

    return f"""
You are an evidence-grounded research analyst.

USER RESEARCH QUESTION:
{question}

SCOPE:
{scope}

AVAILABLE EVIDENCE:
{evidence_text}

Generate findings that answer the question.

STRICT RULES:

1. Every finding MUST be directly supported by one or more of the
   evidence items above, and MUST cite their ids.
2. Do NOT use outside knowledge.
3. Do NOT invent statistics, percentages, ratings, prices, frequencies
   or counts.
4. Do NOT generate findings that are out of SCOPE (for example generic
   popularity or ratings when nobody asked for them).
5. If the question asks about complaints, only create a COMPLAINT when
   the evidence explicitly describes a complaint, problem or negative
   experience.
6. Do NOT treat the name of a review platform as evidence
   ("Hostelworld" appearing in a source does NOT mean its reviews are bad).
7. Do NOT infer an aggregate pattern ("most", "many", "often") from a
   single evidence item. One review is one review.
8. Prefer recurring points that appear in several evidence items.
9. It is better to return ZERO findings than an invented one.
10. At most 6 findings.

Give every finding exactly one category:
{categories}

Return ONLY valid JSON:

{{
    "findings": [
        {{
            "category": "COMPLAINT",
            "statement": "Specific, evidence-backed finding.",
            "evidence_ids": ["evidence_1", "evidence_4"],
            "confidence": 0.8
        }}
    ]
}}

If there are no valid findings: {{"findings": []}}
"""


def analyze_evidence_with_llm(state: ResearchState) -> Dict[str, Any]:
    """
    Generate findings from the evidence, in batches so the prompt always
    fits the model's context window.

    The model may return zero findings. Findings that cite unknown evidence
    ids are dropped.
    """

    settings = get_settings()

    question = _question_text(state)
    aspects = _aspects(state)

    evidence = _normalize_evidence(state.get("evidence", []))

    print("\nLLM ANALYZING EVIDENCE...")

    if not evidence:
        print("NO EVIDENCE AVAILABLE")
        return {"findings": []}

    batch_size = max(settings.analyze_batch_size, 1)

    findings: List[Dict[str, Any]] = []
    seen_statements = set()

    for start in range(0, len(evidence), batch_size):
        batch = evidence[start : start + batch_size]
        batch_ids = {item["evidence_id"] for item in batch}

        try:
            parsed = parse_json(
                generate_text(_analysis_prompt(question, aspects, batch))
            )

            raw_findings = parsed.get("findings", [])

        except Exception as exc:
            print(f"LLM ANALYSIS ERROR (batch {start // batch_size + 1}): {exc}")
            continue

        for finding in raw_findings:
            if not isinstance(finding, dict):
                continue

            statement = _safe_text(finding.get("statement"))

            if not statement:
                continue

            raw_ids = finding.get("evidence_ids", [])

            if not isinstance(raw_ids, list):
                raw_ids = [raw_ids]

            evidence_ids = [
                evidence_id
                for evidence_id in (_norm_evidence_id(item) for item in raw_ids)
                if evidence_id in batch_ids
            ]

            # Never accept a finding without valid evidence references.
            if not evidence_ids:
                continue

            key = statement.lower()

            if key in seen_statements:
                continue

            seen_statements.add(key)

            try:
                confidence = float(finding.get("confidence", 0.5))
            except (TypeError, ValueError):
                confidence = 0.5

            category = normalise_category(
                finding.get("category") or finding.get("type")
            )

            findings.append(
                {
                    "finding_id": f"finding_{len(findings) + 1}",
                    "type": category,
                    "category": category,
                    "statement": statement,
                    "evidence_ids": evidence_ids,
                    "confidence": max(0.0, min(confidence, 1.0)),
                }
            )

    print(f"LLM FINDINGS GENERATED: {len(findings)}")

    for finding in findings:
        print(f"  → [{finding['category']}] {finding['statement']}")

    return {"findings": findings}


# ============================================================
# FINDING VERIFICATION
# ============================================================

def verify_findings(state: ResearchState) -> Dict[str, Any]:
    """Verify findings against the evidence and the question's scope."""

    from app.graph.finding_verifier import verify_findings_with_llm

    findings = state.get("findings", [])

    if not findings:
        print("\nFINDING VERIFICATION")
        print("NO FINDINGS TO VERIFY")

        return {"verified_findings": []}

    return {
        "verified_findings": verify_findings_with_llm(
            question=_question_text(state),
            findings=findings,
            evidence=_normalize_evidence(state.get("evidence", [])),
            aspects=_aspects(state) or None,
        )
    }


# ============================================================
# QUALITY CHECK
# ============================================================

def quality_check(state: ResearchState) -> Dict[str, Any]:
    """Decide whether the research is strong enough to write the report."""

    evidence = state.get("evidence", [])
    verified_findings = state.get("verified_findings", [])
    search_queries = state.get("search_queries", [])

    unique_sources = {
        _safe_text(item.get("source_url", ""))
        for item in evidence
        if _safe_text(item.get("source_url", ""))
    }

    verified_count = sum(
        1
        for finding in verified_findings
        if finding.get("verification_status") == "VERIFIED"
    )

    needs_reviews = _is_review_question(state)

    review_query_count = sum(
        1
        for query in search_queries
        if any(word in query.lower() for word in REVIEW_WORDS)
    )

    evidence_score = min(len(evidence) / 10, 1.0)
    finding_score = min(verified_count / 5, 1.0)
    source_diversity_score = min(len(unique_sources) / 3, 1.0)
    review_coverage_score = (
        min(review_query_count / 3, 1.0) if needs_reviews else 1.0
    )

    final_score = (
        0.35 * evidence_score
        + 0.25 * finding_score
        + 0.20 * source_diversity_score
        + 0.20 * review_coverage_score
    )

    missing_information: List[str] = []

    if not evidence:
        missing_information.append("Research found no usable evidence.")

    if len(unique_sources) < 3:
        missing_information.append("Research needs more independent sources.")

    if verified_count < 3:
        missing_information.append("Research needs more verified findings.")

    if needs_reviews and review_query_count < 3:
        missing_information.append("Research needs more review-focused queries.")

    decision = (
        "RESEARCH SUFFICIENT"
        if final_score >= 0.70 and not missing_information
        else "RESEARCH INSUFFICIENT"
    )

    print("\n" + "=" * 55)
    print(
        f"ITERATION {state.get('iteration', 0)} | "
        f"sources {len(state.get('sources', []))} | "
        f"evidence {len(evidence)} | "
        f"findings {len(state.get('findings', []))} | "
        f"verified {verified_count}"
    )
    print(
        f"scores: evidence {evidence_score:.2f}, findings {finding_score:.2f}, "
        f"diversity {source_diversity_score:.2f}, "
        f"review-coverage {review_coverage_score:.2f} -> {final_score:.2f}"
    )

    for item in missing_information:
        print(f"  - {item}")

    print(f"DECISION: {decision}")
    print("=" * 55)

    return {
        "missing_information": missing_information,
        "evidence_score": final_score,
        "quality_decision": decision,
    }


# ============================================================
# CONDITIONAL ROUTING
# ============================================================

def should_continue(state: ResearchState) -> str:
    """
    After quality_check: write the report, or search some more?

    (This is the single routing function. edges.py re-exports it; the old
    copy there returned a route the graph does not have.)
    """

    if state.get("quality_decision") == "RESEARCH SUFFICIENT":
        return "insights"

    if state.get("iteration", 0) >= state.get("max_iterations", 2):
        return "insights"

    return "followup"


# ============================================================
# FOLLOW-UP QUERY GENERATION
# ============================================================

def generate_followup_queries(state: ResearchState) -> Dict[str, Any]:
    """Generate additional queries based on missing information."""

    question = _question_text(state)
    missing_information = state.get("missing_information", [])
    existing_queries = state.get("search_queries", [])

    existing_lower = {query.lower().strip() for query in existing_queries}

    missing_text = "\n".join(f"- {item}" for item in missing_information)

    prompt = f"""
You are a research follow-up query generator.

ORIGINAL QUESTION:
{question}

MISSING INFORMATION:
{missing_text}

EXISTING QUERIES:
{chr(10).join(f"- {query}" for query in existing_queries)}

Generate 2-3 NEW search queries that directly address the missing
information and stay tightly focused on the original question.
Do not repeat existing queries.

Return ONLY valid JSON:

{{"queries": ["query 1", "query 2", "query 3"]}}
"""

    queries: List[str] = []

    try:
        parsed = parse_json(generate_text(prompt))

        queries = [
            _safe_text(query)
            for query in parsed.get("queries", [])
            if _safe_text(query)
        ]

    except Exception as exc:
        print(f"FOLLOW-UP QUERY ERROR: {exc}")

    queries = [
        query for query in queries if query.lower().strip() not in existing_lower
    ]

    if not queries:
        question_obj = _question(state)
        base = (
            f"{question_obj.subject} {question_obj.place}".strip()
            if question_obj and question_obj.mode == "property"
            else question[:100]
        )

        suffixes = [
            "customer reviews",
            "complaints problems",
            "tripadvisor reviews",
            "reddit experience",
            "what guests say",
            "booking.com reviews",
        ]

        queries = [
            f"{base} {suffix}"
            for suffix in suffixes
            if f"{base} {suffix}".lower() not in existing_lower
        ][:3]

    print("\nGENERATED FOLLOW-UP QUERIES:")

    for query in queries:
        print(f"  → {query}")

    return {
        "pending_queries": queries,
        "search_queries": existing_queries + queries,
    }


# ============================================================
# INSIGHTS
# ============================================================

def _verified(state: ResearchState) -> List[Dict[str, Any]]:
    return [
        finding
        for finding in state.get("verified_findings", [])
        if finding.get("verification_status") == "VERIFIED"
    ]


def generate_insights(state: ResearchState) -> Dict[str, Any]:
    """Generate higher-level insights only from verified findings."""

    question = _question_text(state)
    verified_findings = _verified(state)

    if not verified_findings:
        return {
            "insights": [
                "The available evidence was insufficient to establish "
                "reliable findings for the research question."
            ]
        }

    findings_text = "\n".join(
        f"- [{finding.get('category', 'OTHER')}] {finding.get('statement', '')} "
        f"(confidence: {finding.get('confidence', 0.5)})"
        for finding in verified_findings
    )

    prompt = f"""
You are a research synthesis analyst.

QUESTION:
{question}

VERIFIED FINDINGS:
{findings_text}

Generate 2-4 concise insights that synthesise the verified findings.

Rules:
- Use ONLY the verified findings.
- Do not introduce outside knowledge.
- Do not invent statistics.
- Do not turn unrelated findings into conclusions.
- Highlight recurring patterns, differences or important implications.
- If the evidence is weak, say so.

Return ONLY valid JSON:

{{"insights": ["Insight 1", "Insight 2"]}}
"""

    try:
        parsed = parse_json(generate_text(prompt))

        insights = [
            _safe_text(item)
            for item in parsed.get("insights", [])
            if _safe_text(item)
        ]

    except Exception as exc:
        print(f"INSIGHT GENERATION ERROR: {exc}")

        insights = [
            finding.get("statement", "")
            for finding in verified_findings
            if finding.get("statement")
        ]

    return {"insights": insights}


# ============================================================
# REPORT
# ============================================================

def _report_title(state: ResearchState) -> str:
    question = _question(state)

    if question and question.mode == "property" and question.subject:
        return f"Property profile - {question.subject}"

    if question and question.mode == "topic" and question.subject:
        return f"Topic research - {question.subject}"

    return "Research report"


def _summary(question: str, verified: List[Dict[str, Any]]) -> str:
    """Optional short prose summary. Returns '' when the LLM misbehaves."""

    if not verified:
        return ""

    findings_text = "\n".join(f"- {f.get('statement', '')}" for f in verified)

    prompt = f"""
Write a 3-4 sentence executive summary of these verified findings.

QUESTION: {question}

VERIFIED FINDINGS:
{findings_text}

Rules: use only the findings above, add no facts, no numbers that are not
in the findings, plain prose, no headings, no lists.
"""

    try:
        text = generate_text(prompt, json_mode=False).strip()
    except Exception as exc:
        print(f"SUMMARY ERROR: {exc}")
        return ""

    if not text or text.startswith(("{", "[", "#")) or len(text) < 40:
        return ""

    return text[:1200]


def generate_report(state: ResearchState) -> Dict[str, Any]:
    """
    Build the final report from verified findings + insights.

    Findings, links and coverage are assembled in code (no hallucinated
    sources); the LLM only adds an optional summary paragraph.
    """

    question = _question_text(state)
    verified = _verified(state)

    print("\nGENERATING FINAL REPORT...")

    report = build_report_markdown(
        title=_report_title(state),
        question=question,
        run_id=state.get("run_id", ""),
        verified=verified,
        all_findings=state.get("verified_findings", []),
        evidence=_normalize_evidence(state.get("evidence", [])),
        insights=state.get("insights", []),
        missing_information=state.get("missing_information", []),
        summary=_summary(question, verified),
    )

    print("FINAL REPORT GENERATED")

    return {"report": report}


# ============================================================
# COMPATIBILITY ALIASES
# ============================================================

research_node = research

build_report = generate_report
