from typing import TypedDict, List, Dict, Any

from app.schemas.research import (
    ResearchQuestion,
    ResearchPlan,
)

from app.schemas.source import Source

from app.schemas.evidence import (
    Evidence,
    Finding,
)


class ResearchState(TypedDict, total=False):

    # User input
    question: ResearchQuestion

    # Planning
    research_plan: ResearchPlan

    search_queries: List[str]
    pending_queries: List[str]

    # Research
    sources: List[Source]
    evidence: List[Evidence]
    contradictions: List[Dict[str, Any]]

    # Analysis
    findings: List[Finding]
    insights: List[str]

    # Quality control
    missing_information: List[str]
    evidence_score: float

    # Loop control
    iteration: int
    max_iterations: int

    quality_decision: str

    # Final output
    report: str