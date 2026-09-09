"""
Shared answer-shape schemas, used by both the interview cognitive memory
(schemas/interview_memory.py, candidate_id-scoped) and the domain "answer a
question" endpoints for Stock/Real Estate (schemas/domain_answer.py,
single-tenant, no candidate_id — see docs/openresearch-integration-
requirements.md §10).

Factored out here rather than having domain_answer.py import from
interview_memory.py, which would be a confusing dependency direction (a
stock/real-estate schema depending on an interview-specific module for
pieces that were never actually interview-specific).
"""

from typing import Optional
from pydantic import BaseModel, Field
from typing import Literal

AnswerFormat = Literal["full_text", "list", "keywords"]
AnswerDepth = Literal["one_liner", "balanced", "detailed"]


class AnswerStyle(BaseModel):
    format: AnswerFormat = "full_text"
    depth: AnswerDepth = "balanced"


class ImageAttachment(BaseModel):
    """A single image, always carried as base64 over the wire.

    Used both as ephemeral input (a live screenshot attached to a question,
    passed to the model for that one answer and never persisted) and as
    persisted content (e.g. an interview answer-bank entry's attached
    diagram) — see each call site for which lifetime applies.
    """
    media_type: str  # e.g. "image/png", "image/jpeg", "image/webp"
    data: str         # base64-encoded image bytes
    caption: Optional[str] = None


class MatchedSource(BaseModel):
    id: str
    title: str
    category: str
    images: list[ImageAttachment] = Field(default_factory=list)
