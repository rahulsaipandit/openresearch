"""Pydantic schemas for the interview cognitive memory system.

See docs/openresearch-integration-requirements.md §6/§6.1 for the design
this implements: markdown + frontmatter storage (not JSON rows), a chromadb
vector layer for paraphrase-tolerant retrieval, and a lightweight typed-edge
graph linking topics/questions/answer-bank entries. Topic mastery is derived
from an append-only log of versioned Assessment facts, never mutated in place.

This is a separate system from schemas/interview.py (pre-interview JD/resume
research) and schemas/skills.py (the existing single-user SM-2 tracker) —
candidate_id-scoped from the start, per the Pluely live-interview-coaching
integration.
"""

from typing import Literal, Optional

from pydantic import BaseModel, Field

# Re-exported for backward compatibility — these moved to schemas/answer_common.py
# so the domain "answer a question" endpoints (Stock, Real Estate — §10) could
# share them without importing an interview-specific module. Existing
# `from schemas.interview_memory import AnswerStyle, ImageAttachment, MatchedSource`
# call sites keep working unchanged.
from schemas.answer_common import AnswerStyle, ImageAttachment, MatchedSource  # noqa: F401

AnswerBankCategory = Literal["story", "prepared_answer", "talking_point"]
AssessmentSource = Literal["llm_judge", "candidate_override"]
DocumentType = Literal["resume", "candidate_document", "seed_question", "answer_bank_manual"]


class InterviewProfile(BaseModel):
    """Single active profile per candidate — replace-on-update, not versioned."""
    candidate_id: str
    resume_text: str = ""
    job_description_text: str = ""
    custom_instructions: str = ""


class AnswerBankEntry(BaseModel):
    id: str
    candidate_id: str
    title: str
    content: str
    category: AnswerBankCategory
    tags: list[str] = Field(default_factory=list)
    images: list[ImageAttachment] = Field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""


class AnswerBankEntryCreate(BaseModel):
    """Request body for creating/updating an answer-bank entry — id and
    candidate_id come from the URL, not the body."""
    title: str
    content: str
    category: AnswerBankCategory = "talking_point"
    tags: list[str] = Field(default_factory=list)
    images: list[ImageAttachment] = Field(default_factory=list)


class DocumentRecord(BaseModel):
    """Registry entry for one ingested document — see docs/designInterviewTool.md's
    "RAG / Document Ingestion Architecture" section for the full design.

    `doc_id` is a UUID assigned once per logical document (per candidate +
    filename), not derived from content — re-uploading an edited version of
    the same file keeps the same `doc_id` so citations/graph edges pointing
    at it stay valid; only its vectors need re-indexing (see staleness
    fields below).
    """
    doc_id: str
    candidate_id: str
    filename: str
    doc_type: DocumentType
    page_count: int = 0
    ingested_at: str = ""

    # Staleness tracking (docs/designInterviewTool.md "Staleness tracking" —
    # lets the app know when a document's vectors/graph edges no longer
    # match its current content, instead of silently serving stale answers).
    content_hash: str = ""
    source_modified_at: str = ""
    last_indexed_at: str = ""
    last_graph_synced_at: str = ""

    @property
    def stale(self) -> bool:
        return bool(self.source_modified_at) and self.source_modified_at > self.last_indexed_at


class DocumentUploadResult(BaseModel):
    document: DocumentRecord
    chunks_indexed: int
    reindexed: bool = False  # true if this replaced an existing doc_id's content


class SkillApplyRequest(BaseModel):
    """Request body for POST /v1/interview/skills/{skill_name}/apply."""
    candidate_id: str
    args: dict = Field(default_factory=dict)


class QuestionRecord(BaseModel):
    """One answered question — append-only, never rewritten.

    Also carries SM-2 spaced-repetition state so the pre_interview_drill
    skill can schedule re-practice of previously asked questions, without
    needing a second question store.
    """
    id: str
    candidate_id: str
    session_id: str
    question_text: str
    topic: str = "uncategorized"
    answer_text: str = ""
    judge_score: Optional[float] = None
    judge_rationale: str = ""
    matched_sources: list[MatchedSource] = Field(default_factory=list)
    timestamp: str = ""

    # SM-2 drilling state (pre_interview_drill skill)
    ease_factor: float = 2.5
    interval_days: int = 1
    repetitions: int = 0
    next_review_date: str = ""
    last_reviewed: Optional[str] = None
    last_quality: Optional[int] = None


class Assessment(BaseModel):
    """One immutable, timestamped judgment of a candidate's answer on a topic.

    Topic mastery is a derived query over these, never a mutated field —
    see InterviewMemoryStore.recompute_topic_summary().
    """
    id: str
    candidate_id: str
    topic: str
    question_ref: str = ""          # relative path to the QuestionRecord this judged
    judge_score: float              # 0-1
    source: AssessmentSource = "llm_judge"
    rationale: str = ""
    override_reason: Optional[str] = None
    timestamp: str = ""


class TopicSummary(BaseModel):
    """Derived, rebuildable summary — safe to regenerate from assessments/*."""
    topic: str
    candidate_id: str
    mastery_score: float = 0.5
    sample_count: int = 0
    last_judged_at: str = ""
    derived_from: list[str] = Field(default_factory=list)
    related_topics: list[str] = Field(default_factory=list)
    notes: str = ""


class DocumentChunkMatch(BaseModel):
    """One retrieved chunk of an ingested document, with enough on it to
    build both a MatchedSource (for the graph edge) and a Citation (for
    display) without a second lookup."""
    doc_id: str
    filename: str
    doc_type: DocumentType
    page_number: Optional[int] = None
    chunk_text: str
    content_hash_at_citation: str = ""


class RetrievedContext(BaseModel):
    """Context assembled for the answer-generation step."""
    matched_answer_bank: list[AnswerBankEntry] = Field(default_factory=list)
    matched_documents: list[DocumentChunkMatch] = Field(default_factory=list)
    topic_summary: Optional[TopicSummary] = None
    related_topic_summaries: list[TopicSummary] = Field(default_factory=list)


class Citation(BaseModel):
    """Display-shaped pointer back to the exact source of a claim in an answer."""
    doc_id: str
    filename: str
    doc_type: DocumentType
    page_number: Optional[int] = None
    chunk_excerpt: str = ""
    stale: bool = False  # source document has changed since this citation was made


class AnswerRequest(BaseModel):
    """Request body for POST /v1/interview/answer (requirements doc §2)."""
    session_id: str
    candidate_id: str                # not yet in the Pluely contract — see §8 open item
    question: str
    conversation_history: list[dict] = Field(default_factory=list)
    answer_style: AnswerStyle = Field(default_factory=AnswerStyle)
    images: list[ImageAttachment] = Field(default_factory=list)  # §2.1 — a live screenshot, ephemeral
    # RAG scoping control (docs/designInterviewTool.md "Full Plan: Per-Document
    # Selection + Source Traceability"). None/empty = search the whole
    # candidate corpus (current behavior); non-empty = restrict retrieval to
    # exactly these doc_ids.
    document_ids: Optional[list[str]] = None


class AnswerResult(BaseModel):
    """Full (non-streamed) result — the server chunks this into SSE frames."""
    answer_text: str
    matched_sources: list[MatchedSource] = Field(default_factory=list)
    topic: str = "uncategorized"
    question_record_id: str = ""
    images_ignored: bool = False  # true if images were sent but the configured model couldn't use them
    # Traceability: same underlying retrieval hits as matched_sources, shaped
    # for display — "which page of which document backs this claim, if any."
    citations: list[Citation] = Field(default_factory=list)
