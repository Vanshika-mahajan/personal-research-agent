from typing import Literal

from pydantic import BaseModel, Field


class Insight(BaseModel):
    claim: str = Field(description="The research finding.")
    evidence: list[str] = Field(
        description="Evidence supporting the finding."
    )
    source_urls: list[str] = Field(
        default_factory=list,
        description="URLs supporting the finding."
    )
    confidence: Literal["low", "medium", "high"] = "medium"
    type: Literal["fact", "observation", "hypothesis"] = "observation"