from typing import List, TypedDict

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

    # Research
    sources: List[Source]
    evidence: List[Evidence]

    # Analysis
    findings: List[Finding]
    insights: List[str]

    # Quality control
    missing_information: List[str]
    evidence_score: float

    # Loop control
    iteration: int
    max_iterations: int

    # Final output
    report: str