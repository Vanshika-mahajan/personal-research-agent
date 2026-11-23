from typing import Literal
from pydantic import BaseModel, Field


class Insight(BaseModel):
    statement: str
    type: Literal["FACT", "OBSERVATION", "HYPOTHESIS"]
    supporting_evidence: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str = ""