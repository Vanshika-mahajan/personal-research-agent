from pydantic import BaseModel, Field


class Evidence(BaseModel):
    claim: str = Field(
        min_length=1,
        description="A specific factual observation supported by the source.",
    )

    source_title: str = Field(
        min_length=1,
        description="Title of the source supporting the evidence.",
    )

    source_url: str = Field(
        min_length=1,
        description="URL of the source supporting the evidence.",
    )

    source_type: str = Field(
        default="web",
        description="Type of source: web, review, booking, social, etc.",
    )

    confidence: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Confidence that the evidence accurately supports the claim.",
    )


class Finding(BaseModel):
    statement: str = Field(
        min_length=1,
        description="A research finding derived from the evidence.",
    )

    evidence_ids: list[str] = Field(
        default_factory=list,
        description="IDs or references to supporting evidence.",
    )

    confidence: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Confidence in the finding.",
    )