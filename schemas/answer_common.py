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

from typing import Literal, Optional

from pydantic import BaseModel, Field

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
    """A piece of grounding material an answer drew on.

    `source_type` distinguishes a hand-written answer-bank entry from a
    chunk of an ingested document (resume, candidate write-up, seed
    question, ...) — see docs/designInterviewTool.md's "RAG / Document
    Ingestion Architecture" section. `doc_id`/`page_number` are only set for
    `source_type="document"`; `content_hash_at_citation` snapshots the
    source document's content_hash at the moment this citation was made, so
    a later document edit can be detected as making the historical citation
    possibly stale (compare against the current DocumentRecord.content_hash).
    """
    id: str
    title: str
    category: str
    images: list[ImageAttachment] = Field(default_factory=list)
    source_type: Literal["answer_bank", "document"] = "answer_bank"
    doc_id: Optional[str] = None
    page_number: Optional[int] = None
    content_hash_at_citation: Optional[str] = None
