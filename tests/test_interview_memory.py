"""
Tests for the interview cognitive memory system
(docs/openresearch-integration-requirements.md §6/§6.1).

Uses a FakeVectorStore (no chromadb dependency) so these tests exercise the
markdown + graph + derivation logic — the parts unique to this design —
without requiring an embedding model download.
"""

from pathlib import Path

import pytest

from memory.interview_memory import InterviewMemoryStore
from memory.markdown_frontmatter import read_frontmatter, write_frontmatter
from schemas.interview_memory import (
    Assessment,
    AnswerBankEntry,
    InterviewProfile,
    MatchedSource,
    QuestionRecord,
)


class FakeVectorStore:
    """Deterministic word-overlap 'similarity' — enough to test retrieval and
    dedup wiring without needing real embeddings."""

    def __init__(self):
        self._docs: dict[str, dict] = {}

    def upsert(self, doc_id, text, candidate_id, doc_type, topic=None):
        self._docs[doc_id] = {
            "text": text,
            "candidate_id": candidate_id,
            "doc_type": doc_type,
            "topic": topic,
        }

    def delete(self, doc_id):
        self._docs.pop(doc_id, None)

    def _distance(self, a: str, b: str) -> float:
        wa, wb = set(a.lower().split()), set(b.lower().split())
        if not wa or not wb:
            return 1.0
        overlap = len(wa & wb) / len(wa | wb)
        return 1.0 - overlap

    def query(self, candidate_id, query_text, n_results=5, doc_type=None):
        candidates = [
            (doc_id, self._distance(query_text, d["text"]))
            for doc_id, d in self._docs.items()
            if d["candidate_id"] == candidate_id and (doc_type is None or d["doc_type"] == doc_type)
        ]
        candidates.sort(key=lambda x: x[1])
        top = candidates[:n_results]
        return {"ids": [[c[0] for c in top]], "distances": [[c[1] for c in top]]}

    def most_similar(self, candidate_id, text, doc_type):
        result = self.query(candidate_id, text, n_results=1, doc_type=doc_type)
        ids = result["ids"][0]
        if not ids:
            return None
        return ids[0], result["distances"][0][0]


@pytest.fixture
def store(tmp_path: Path) -> InterviewMemoryStore:
    return InterviewMemoryStore("cand_test1", base_dir=tmp_path, vector_store=FakeVectorStore())


# ── Frontmatter ──────────────────────────────────────────────────────────────

def test_frontmatter_roundtrip_with_nested_structures():
    """Real YAML round-trips nested lists/dicts — the specific failure mode
    of the cognitiveBrain reference's hand-rolled parser."""
    fm = {"tags": ["a", "b"], "matched_sources": [{"id": "x", "title": "Y", "category": "story"}]}
    text = write_frontmatter(fm, "body text")
    parsed, body = read_frontmatter(text)
    assert parsed == fm
    assert body.strip() == "body text"


# ── Profile ──────────────────────────────────────────────────────────────────

def test_profile_roundtrip(store: InterviewMemoryStore):
    store.set_profile(
        InterviewProfile(
            candidate_id="cand_test1",
            resume_text="Senior engineer, 10 years",
            job_description_text="Staff engineer role",
            custom_instructions="Be concise.",
        )
    )
    profile = store.get_profile()
    assert profile.resume_text == "Senior engineer, 10 years"
    assert profile.job_description_text == "Staff engineer role"
    assert profile.custom_instructions == "Be concise."


# ── Answer bank ──────────────────────────────────────────────────────────────

def test_answer_bank_crud(store: InterviewMemoryStore):
    entry = store.add_answer_bank_entry(
        AnswerBankEntry(
            id="e1", candidate_id="", title="Conflict with manager",
            content="Disagreed on scope, resolved via data.", category="story", tags=["conflict"],
        )
    )
    assert entry.candidate_id == "cand_test1"
    assert store.get_answer_bank_entry("e1").title == "Conflict with manager"
    assert len(store.list_answer_bank()) == 1

    assert store.delete_answer_bank_entry("e1") is True
    assert store.get_answer_bank_entry("e1") is None
    assert store.delete_answer_bank_entry("e1") is False


def test_answer_bank_dedup_detection(store: InterviewMemoryStore):
    store.add_answer_bank_entry(
        AnswerBankEntry(
            id="e1", candidate_id="", title="Conflict with manager",
            content="Disagreed on project scope with my manager, resolved with data.",
            category="story",
        )
    )
    duplicate_id = store.find_near_duplicate_answer_bank_entry(
        "Disagreed on project scope with my manager, resolved with data."
    )
    assert duplicate_id == "e1"

    unrelated_id = store.find_near_duplicate_answer_bank_entry(
        "Completely unrelated content about database migrations."
    )
    assert unrelated_id is None


# ── Questions (append-only) ──────────────────────────────────────────────────

def test_record_and_parse_question(store: InterviewMemoryStore):
    record = store.record_question(
        QuestionRecord(
            id="", candidate_id="", session_id="sess1",
            question_text="Tell me about a conflict.",
            topic="conflict-resolution",
            answer_text="I disagreed with a peer about the API design...",
            matched_sources=[MatchedSource(id="e1", title="Conflict story", category="story")],
        )
    )
    assert record.id

    fetched = store.get_question(record.id)
    assert fetched.question_text == "Tell me about a conflict."
    assert fetched.answer_text.startswith("I disagreed")
    assert fetched.matched_sources[0].id == "e1"

    # tests_topic + grounded_by edges recorded
    assert f"topic:conflict-resolution" in store.graph.neighbors(f"question:{record.id}")
    assert f"answer_bank:e1" in store.graph.neighbors(f"question:{record.id}")


# ── Versioned assessments + derived topic mastery ────────────────────────────

def test_topic_mastery_is_derived_not_mutated(store: InterviewMemoryStore):
    store.record_assessment(
        Assessment(id="", candidate_id="", topic="system-design", judge_score=0.4, rationale="weak")
    )
    summary = store.record_assessment(
        Assessment(id="", candidate_id="", topic="system-design", judge_score=0.6, rationale="better")
    )
    assert summary.sample_count == 2
    assert summary.mastery_score == pytest.approx((0.4 + 0.6) / 2, abs=1e-6)
    assert len(summary.derived_from) == 2

    # Rebuilding from scratch (as if regenerated) gives the same result —
    # confirms topics/*.md is a safe-to-regenerate derivation, not authoritative state.
    rebuilt = store._recompute_topic_summary("system-design")
    assert rebuilt.mastery_score == summary.mastery_score
    assert rebuilt.sample_count == summary.sample_count


def test_candidate_override_takes_precedence(store: InterviewMemoryStore):
    store.record_assessment(
        Assessment(id="", candidate_id="", topic="behavioral", judge_score=0.3, source="llm_judge")
    )
    store.record_assessment(
        Assessment(id="", candidate_id="", topic="behavioral", judge_score=0.2, source="llm_judge")
    )
    summary = store.record_assessment(
        Assessment(
            id="", candidate_id="", topic="behavioral", judge_score=0.9,
            source="candidate_override", override_reason="Judge missed the STAR structure I used.",
        )
    )
    # Override is the only thing basis draws from once present, per §6.1.
    assert summary.mastery_score == pytest.approx(0.9)
    assert summary.sample_count == 3  # history isn't lost, just not the basis for current mastery


def test_topic_notes_preserved_across_recompute(store: InterviewMemoryStore):
    store.record_assessment(Assessment(id="", candidate_id="", topic="system-design", judge_score=0.5))
    topic_path = store.topics_dir / "system-design.md"
    frontmatter, _ = read_frontmatter(topic_path.read_text(encoding="utf-8"))
    topic_path.write_text(
        write_frontmatter(frontmatter, "Freeform coaching note added by the LLM judge."),
        encoding="utf-8",
    )
    store.record_assessment(Assessment(id="", candidate_id="", topic="system-design", judge_score=0.7))
    summary = store.get_topic_summary("system-design")
    assert "Freeform coaching note" in summary.notes


# ── Graph ────────────────────────────────────────────────────────────────────

def test_topic_co_occurrence_creates_bidirectional_related_to(store: InterviewMemoryStore):
    store.record_topic_co_occurrence(["system-design", "tradeoff-analysis"])
    assert "topic:tradeoff-analysis" in store.graph.related_topics("topic:system-design")
    assert "topic:system-design" in store.graph.related_topics("topic:tradeoff-analysis")


# ── Retrieval ────────────────────────────────────────────────────────────────

def test_retrieve_context_returns_topic_and_related(store: InterviewMemoryStore):
    store.record_assessment(Assessment(id="", candidate_id="", topic="system-design", judge_score=0.4))
    store.record_topic_co_occurrence(["system-design", "tradeoff-analysis"])
    store.record_assessment(Assessment(id="", candidate_id="", topic="tradeoff-analysis", judge_score=0.8))

    context = store.retrieve_context("How do you approach system design?", topic="system-design")
    assert context.topic_summary.topic == "system-design"
    assert any(s.topic == "tradeoff-analysis" for s in context.related_topic_summaries)


# ── Candidate isolation ──────────────────────────────────────────────────────

def test_candidates_are_isolated(tmp_path: Path):
    shared_vectors = FakeVectorStore()
    store_a = InterviewMemoryStore("cand_a", base_dir=tmp_path, vector_store=shared_vectors)
    store_b = InterviewMemoryStore("cand_b", base_dir=tmp_path, vector_store=shared_vectors)

    store_a.add_answer_bank_entry(
        AnswerBankEntry(id="e1", candidate_id="", title="A's story", content="...", category="story")
    )
    assert store_b.get_answer_bank_entry("e1") is None
    assert len(store_a.list_answer_bank()) == 1
    assert len(store_b.list_answer_bank()) == 0
