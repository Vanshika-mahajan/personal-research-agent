from pydantic import BaseModel, Field


class Source(BaseModel):
    title: str = Field(
        min_length=1,
        description="Title of the research source.",
    )

    url: str = Field(
        min_length=1,
        description="URL of the research source.",
    )

    source_type: str = Field(
        default="web",
        description="Type of source, such as web, review, booking, or social.",
    )

    credibility: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Estimated credibility score from 0 to 1.",
    )