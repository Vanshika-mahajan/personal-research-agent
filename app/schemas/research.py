from typing import List

from pydantic import BaseModel, Field


class ResearchQuestion(BaseModel):
    question: str = Field(
        min_length=5,
        description="The research question provided by the user.",
    )

    depth: str = Field(
        default="deep",
        description="Research depth: quick, deep, or exhaustive.",
    )

    max_iterations: int = Field(
        default=3,
        ge=1,
        le=10,
        description="Maximum number of research iterations.",
    )


class ResearchQuery(BaseModel):
    query: str = Field(
        min_length=3,
        description="Search query to execute.",
    )

    purpose: str = Field(
        min_length=3,
        description="Why this query is needed.",
    )

    priority: int = Field(
        default=3,
        ge=1,
        le=5,
        description="Query priority from 1 to 5.",
    )


class ResearchPlan(BaseModel):
    queries: List[ResearchQuery]

    research_goals: List[str]

    expected_output: str