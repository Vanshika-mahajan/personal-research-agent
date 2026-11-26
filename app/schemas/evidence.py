from pydantic import BaseModel, Field


class Evidence(BaseModel):
    claim: str = Field(min_length=1)
    source_title: str = Field(min_length=1)
    source_url: str = Field(min_length=1)
    source_type: str = Field(default="web")
    confidence: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
    )


class Finding(BaseModel):
    statement: str = Field(min_length=1)
    evidence_ids: list[str] = Field(
        default_factory=list
    )
    confidence: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
    )