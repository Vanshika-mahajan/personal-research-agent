"""
One function that runs the whole research graph and saves the result.

Everything else (CLI, property profiles, briefs) goes through run_research().
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.graph.graph import build_graph
from app.schemas.research import ResearchQuestion
from app.storage import new_run_id, save_run

DEPTH_ITERATIONS = {"quick": 1, "standard": 2, "deep": 3}


def iterations_for(depth: str) -> int:
    return DEPTH_ITERATIONS.get((depth or "standard").lower(), 2)


def run_research(
    question: ResearchQuestion,
    *,
    label: Optional[str] = None,
    manual_evidence: Optional[List[Dict[str, Any]]] = None,
    save: bool = True,
) -> Dict[str, Any]:
    """
    Run planner -> research -> ... -> report for one question.

    Returns {"run_id", "state", "paths"}; state["report"] is the Markdown
    report and paths point at the saved files.
    """

    run_id = new_run_id(label or question.subject or question.question)

    initial_state = {
        "question": question,
        "run_id": run_id,
        "search_queries": [],
        "pending_queries": [],
        "sources": [],
        "manual_evidence": manual_evidence or [],
        "evidence": [],
        "contradictions": [],
        "findings": [],
        "verified_findings": [],
        "insights": [],
        "missing_information": [],
        "evidence_score": 0.0,
        "iteration": 0,
        "max_iterations": question.max_iterations,
        "quality_decision": "",
        "report": "",
    }

    # Default recursion limit (25) is too low once the follow-up loop runs
    # more than a couple of times.
    final_state = build_graph().invoke(
        initial_state,
        config={"recursion_limit": 100},
    )

    paths = save_run(run_id, final_state) if save else {}

    return {"run_id": run_id, "state": final_state, "paths": paths}
