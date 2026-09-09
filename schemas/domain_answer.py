"""
Domain "answer a question" schemas — Stock and Real Estate (docs/
openresearch-integration-requirements.md §10). Mirrors the shape of
schemas/interview_memory.py's AnswerRequest/AnswerResult, but deliberately
has NO candidate_id: unlike interview memory, these domains stay
single-tenant local stores/pipelines, not per-person cognitive memory.

Domain is never inferred from the question text — it's whichever endpoint
the client calls (POST /v1/stock/answer vs /v1/realestate/answer). See §10
for why an LLM-based cross-domain classifier was explicitly rejected as the
default routing mechanism.
"""

from typing import Optional
from pydantic import BaseModel, Field

from schemas.answer_common import AnswerStyle, ImageAttachment, MatchedSource


class DomainAnswerRequest(BaseModel):
    session_id: Optional[str] = None
    question: str
    conversation_history: list[dict] = Field(default_factory=list)
    answer_style: AnswerStyle = Field(default_factory=AnswerStyle)
    images: list[ImageAttachment] = Field(default_factory=list)


class DomainAnswerResult(BaseModel):
    answer_text: str
    matched_sources: list[MatchedSource] = Field(default_factory=list)
    images_ignored: bool = False
