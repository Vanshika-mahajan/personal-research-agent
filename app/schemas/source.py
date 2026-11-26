from pydantic import BaseModel, Field


class SearchResult(BaseModel):
    """One search hit, optionally enriched with the full page text."""

    title: str

    url: str

    snippet: str

    source_type: str = "web"

    # Human readable channel, e.g. "Booking.com", "Instagram".
    platform: str = ""

    # Full page text when the page could be downloaded (else empty and the
    # snippet is all we have).
    content: str = ""


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
        description=(
            "Type of source: web, review, booking, social, maps, "
            "forum, video, official or manual."
        ),
    )

    credibility: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Estimated credibility score from 0 to 1.",
    )
