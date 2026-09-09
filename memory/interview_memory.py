"""
InterviewMemoryStore — candidate-scoped cognitive memory for interview coaching.

Implements docs/openresearch-integration-requirements.md §6/§6.1: markdown
files with YAML frontmatter (not JSON rows) as the source of truth, a
chromadb vector layer for paraphrase-tolerant retrieval, and a lightweight
typed-edge graph linking topics/questions/answer-bank entries. Topic mastery
is a derived summary computed from an append-only log of versioned
Assessment facts — never a field mutated in place.

Layout (one directory per candidate):
    interview_memory/<candidate_id>/
        profile.md
        answer_bank/<entry_id>.md
        answer_bank/<entry_id>_images/<image_id>.<ext>  (§2.1 — real files, not base64-in-frontmatter)
        topics/<topic_slug>.md              (derived, safe to regenerate)
        assessments/<timestamp>_<hash>.md   (append-only)
        questions/<timestamp>_<hash>.md      (append-only)
        graph.json

Live-question images (§2.1, a candidate's screenshot sent with /v1/interview/answer)
are deliberately NOT persisted here — they're ephemeral, passed straight to the
LLM for that one answer via LiveInterviewCoachSkill, and discarded. Only images
attached to a saved AnswerBankEntry are stored long-term.

This is a separate system from store/skills_store.py (the existing
single-user SM-2 tracker) and schemas/interview.py (pre-interview JD/resume
research) — see docs/openresearch-integration-requirements.md §6.1 for why
those are not being merged.
"""

import base64
import logging
import re
import shutil
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from memory.interview_graph import CandidateGraph
from memory.interview_vector_store import InterviewVectorStore
from memory.markdown_frontmatter import read_markdown_file, write_markdown_file
from schemas.interview_memory import (
    Assessment,
    AnswerBankEntry,
    ImageAttachment,
    InterviewProfile,
    MatchedSource,
    QuestionRecord,
    RetrievedContext,
    TopicSummary,
)

logger = logging.getLogger(__name__)

_DEFAULT_BASE_DIR = Path("data") / "interview_memory"

# Mnemosyne-style near-duplicate threshold for the answer bank only (§6.1) —
# chromadb's default distance is not a calibrated cosine similarity, so this
# is an approximate threshold to tune once real answer-bank content exists,
# not a precise Shannon-limit-style guarantee.
_ANSWER_BANK_DEDUP_DISTANCE = 0.08

_MEDIA_TYPE_EXT = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/webp": "webp",
    "image/gif": "gif",
}


def _ext_for_media_type(media_type: str) -> str:
    return _MEDIA_TYPE_EXT.get(media_type.lower(), "bin")


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "uncategorized"


def _new_id(prefix: str = "") -> str:
    """Timestamp for readability/sort order + uuid4 for actual uniqueness.

    NOTE: an earlier version derived the uniqueness suffix from hashlib of
    id(object()) — CPython can reuse the same address for a rapidly created
    and immediately garbage-collected object, so consecutive fast calls
    produced identical IDs and silently overwrote each other's files. uuid4
    doesn't have that failure mode.
    """
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    suffix = uuid.uuid4().hex[:8]
    return f"{prefix}{stamp}_{suffix}" if prefix else f"{stamp}_{suffix}"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class InterviewMemoryStore:
    def __init__(
        self,
        candidate_id: str,
        base_dir: Path | str = _DEFAULT_BASE_DIR,
        vector_store: Optional[InterviewVectorStore] = None,
    ):
        self.candidate_id = candidate_id
        self.root = Path(base_dir) / candidate_id
        self.answer_bank_dir = self.root / "answer_bank"
        self.topics_dir = self.root / "topics"
        self.assessments_dir = self.root / "assessments"
        self.questions_dir = self.root / "questions"
        for d in (self.answer_bank_dir, self.topics_dir, self.assessments_dir, self.questions_dir):
            d.mkdir(parents=True, exist_ok=True)
        self.profile_path = self.root / "profile.md"
        self.graph = CandidateGraph(self.root / "graph.json")
        self.vector_store = vector_store
        self._lock = threading.Lock()
        # entry_id -> ImageAttachment list. InterviewMemoryStore instances are
        # long-lived per candidate (cached in server.py), and this class is
        # the only writer of answer_bank/<id>_images/, so it can safely own
        # this cache — avoids re-reading + re-base64-encoding every attached
        # image on every /v1/interview/answer request that retrieves the
        # entry (a real cost directly in the §2 latency path otherwise).
        self._image_cache: dict[str, list[ImageAttachment]] = {}

    # ── Profile ──────────────────────────────────────────────────────────────

    def get_profile(self) -> InterviewProfile:
        if not self.profile_path.exists():
            return InterviewProfile(candidate_id=self.candidate_id)
        frontmatter, body = read_markdown_file(self.profile_path)
        return InterviewProfile(
            candidate_id=self.candidate_id,
            resume_text=frontmatter.get("resume_text", ""),
            job_description_text=frontmatter.get("job_description_text", ""),
            custom_instructions=body,
        )

    def set_profile(self, profile: InterviewProfile) -> None:
        write_markdown_file(
            self.profile_path,
            {
                "candidate_id": self.candidate_id,
                "resume_text": profile.resume_text,
                "job_description_text": profile.job_description_text,
                "updated_at": _now_iso(),
            },
            profile.custom_instructions,
        )

    # ── Answer bank ──────────────────────────────────────────────────────────

    def _answer_bank_path(self, entry_id: str) -> Path:
        return self.answer_bank_dir / f"{entry_id}.md"

    def _answer_bank_images_dir(self, entry_id: str) -> Path:
        return self.answer_bank_dir / f"{entry_id}_images"

    def add_answer_bank_entry(self, entry: AnswerBankEntry) -> AnswerBankEntry:
        """Images (§2.1) are decoded and written as real files under
        <entry_id>_images/, not kept as base64 in the frontmatter — a
        multi-hundred-KB base64 blob inline in the markdown would defeat the
        "human-readable, inspectable" point of storing this as markdown at
        all (§6.1/§5.5). Frontmatter only carries filename/media_type/caption;
        get_answer_bank_entry() re-reads and re-encodes the files on the way out.

        Every image is base64-decoded up front, before any file is touched —
        a malformed image on an update request must not destroy the entry's
        previous, still-valid image set, and a malformed image partway
        through a multi-image entry must not leave earlier images orphaned
        on disk with no corresponding markdown file (both were real bugs in
        an earlier version that wrote-as-it-decoded)."""
        with self._lock:
            now = _now_iso()
            entry.candidate_id = self.candidate_id
            entry.created_at = entry.created_at or now
            entry.updated_at = now

            decoded_images = [(img, base64.b64decode(img.data)) for img in entry.images]

            images_dir = self._answer_bank_images_dir(entry.id)
            if images_dir.exists():
                shutil.rmtree(images_dir)  # re-write path (update) — replace the prior image set
            image_meta = []
            if decoded_images:
                images_dir.mkdir(parents=True, exist_ok=True)
                for img, raw_bytes in decoded_images:
                    filename = f"{uuid.uuid4().hex[:8]}.{_ext_for_media_type(img.media_type)}"
                    (images_dir / filename).write_bytes(raw_bytes)
                    image_meta.append(
                        {"filename": filename, "media_type": img.media_type, "caption": img.caption}
                    )

            write_markdown_file(
                self._answer_bank_path(entry.id),
                {
                    "id": entry.id,
                    "title": entry.title,
                    "category": entry.category,
                    "tags": entry.tags,
                    "images": image_meta,
                    "created_at": entry.created_at,
                    "updated_at": entry.updated_at,
                },
                entry.content,
            )
            if self.vector_store:
                # content only, not title+content, not image captions — must
                # match exactly what find_near_duplicate_answer_bank_entry()
                # embeds for dedup, or the two silently drift out of sync
                # (this was a real bug once already — see git history).
                self.vector_store.upsert(
                    doc_id=f"answer_bank:{self.candidate_id}:{entry.id}",
                    text=entry.content,
                    candidate_id=self.candidate_id,
                    doc_type="answer_bank",
                )
            # We already have the decoded images in hand — cache them now
            # instead of making the very next read re-decode them from disk.
            self._image_cache[entry.id] = list(entry.images)
            return entry

    def _load_answer_bank_images(self, entry_id: str, frontmatter: dict) -> list[ImageAttachment]:
        if entry_id in self._image_cache:
            return self._image_cache[entry_id]
        images_dir = self._answer_bank_images_dir(entry_id)
        images = []
        for meta in frontmatter.get("images", []):
            img_path = images_dir / meta.get("filename", "")
            if not img_path.exists():
                continue
            images.append(
                ImageAttachment(
                    media_type=meta.get("media_type", "application/octet-stream"),
                    data=base64.b64encode(img_path.read_bytes()).decode("utf-8"),
                    caption=meta.get("caption"),
                )
            )
        self._image_cache[entry_id] = images
        return images

    def get_answer_bank_entry(self, entry_id: str) -> Optional[AnswerBankEntry]:
        path = self._answer_bank_path(entry_id)
        if not path.exists():
            return None
        frontmatter, body = read_markdown_file(path)
        images = self._load_answer_bank_images(entry_id, frontmatter)
        return AnswerBankEntry(
            id=frontmatter.get("id", entry_id),
            candidate_id=self.candidate_id,
            title=frontmatter.get("title", ""),
            content=body,
            category=frontmatter.get("category", "talking_point"),
            tags=frontmatter.get("tags", []),
            images=images,
            created_at=frontmatter.get("created_at", ""),
            updated_at=frontmatter.get("updated_at", ""),
        )

    def list_answer_bank(self) -> list[AnswerBankEntry]:
        entries = []
        for path in sorted(self.answer_bank_dir.glob("*.md")):
            entry = self.get_answer_bank_entry(path.stem)
            if entry:
                entries.append(entry)
        return entries

    def delete_answer_bank_entry(self, entry_id: str) -> bool:
        with self._lock:
            path = self._answer_bank_path(entry_id)
            if not path.exists():
                return False
            path.unlink()
            images_dir = self._answer_bank_images_dir(entry_id)
            if images_dir.exists():
                shutil.rmtree(images_dir)
            self._image_cache.pop(entry_id, None)
            if self.vector_store:
                self.vector_store.delete(f"answer_bank:{self.candidate_id}:{entry_id}")
            self.graph.remove_node(entry_id)
            self.graph.save()
            return True

    def find_near_duplicate_answer_bank_entry(self, content: str) -> Optional[str]:
        """Mnemosyne-style dedup check (§6.1) — returns the existing entry_id if
        a near-duplicate answer-bank entry already exists, else None."""
        if not self.vector_store:
            return None
        result = self.vector_store.most_similar(self.candidate_id, content, doc_type="answer_bank")
        if not result:
            return None
        doc_id, distance = result
        if distance <= _ANSWER_BANK_DEDUP_DISTANCE:
            return doc_id.split(":")[-1]
        return None

    # ── Questions (append-only) ─────────────────────────────────────────────

    def record_question(self, record: QuestionRecord) -> QuestionRecord:
        with self._lock:
            record.candidate_id = self.candidate_id
            record.id = record.id or _new_id()
            record.timestamp = record.timestamp or _now_iso()
            record.next_review_date = record.next_review_date or record.timestamp[:10]

            path = self.questions_dir / f"{record.id}.md"
            write_markdown_file(
                path,
                {
                    "id": record.id,
                    "session_id": record.session_id,
                    "topic": record.topic,
                    "judge_score": record.judge_score,
                    # exclude images — they're already stored under the answer-bank
                    # entry's own <id>_images/ dir; embedding base64 here would
                    # repeat it per question and bloat every question's frontmatter.
                    "matched_sources": [m.model_dump(exclude={"images"}) for m in record.matched_sources],
                    "timestamp": record.timestamp,
                    "ease_factor": record.ease_factor,
                    "interval_days": record.interval_days,
                    "repetitions": record.repetitions,
                    "next_review_date": record.next_review_date,
                    "last_reviewed": record.last_reviewed,
                    "last_quality": record.last_quality,
                },
                f"## Question\n\n{record.question_text}\n\n"
                f"## Answer\n\n{record.answer_text}\n\n"
                f"## Judge rationale\n\n{record.judge_rationale}",
            )
            if self.vector_store:
                self.vector_store.upsert(
                    doc_id=f"question:{self.candidate_id}:{record.id}",
                    text=f"{record.question_text}\n\n{record.answer_text}",
                    candidate_id=self.candidate_id,
                    doc_type="question",
                    topic=record.topic,
                )
            self.graph.add_edge(f"question:{record.id}", f"topic:{record.topic}", "tests_topic")
            for source in record.matched_sources:
                self.graph.add_edge(f"question:{record.id}", f"answer_bank:{source.id}", "grounded_by")
            self.graph.save()
            return record

    def get_question(self, question_id: str) -> Optional[QuestionRecord]:
        path = self.questions_dir / f"{question_id}.md"
        if not path.exists():
            return None
        return self._parse_question_file(path)

    def _parse_question_file(self, path: Path) -> QuestionRecord:
        frontmatter, body = read_markdown_file(path)
        question_text = _extract_section(body, "Question")
        answer_text = _extract_section(body, "Answer")
        judge_rationale = _extract_section(body, "Judge rationale")
        return QuestionRecord(
            id=frontmatter.get("id", path.stem),
            candidate_id=self.candidate_id,
            session_id=frontmatter.get("session_id", ""),
            question_text=question_text,
            topic=frontmatter.get("topic", "uncategorized"),
            answer_text=answer_text,
            judge_score=frontmatter.get("judge_score"),
            judge_rationale=judge_rationale,
            matched_sources=[MatchedSource(**m) for m in frontmatter.get("matched_sources", [])],
            timestamp=frontmatter.get("timestamp", ""),
            ease_factor=frontmatter.get("ease_factor", 2.5),
            interval_days=frontmatter.get("interval_days", 1),
            repetitions=frontmatter.get("repetitions", 0),
            next_review_date=frontmatter.get("next_review_date", ""),
            last_reviewed=frontmatter.get("last_reviewed"),
            last_quality=frontmatter.get("last_quality"),
        )

    def list_questions(self) -> list[QuestionRecord]:
        return [self._parse_question_file(p) for p in sorted(self.questions_dir.glob("*.md"))]

    def update_question_drill_state(self, record: QuestionRecord) -> None:
        """Rewrite SM-2 fields on an existing question record after a drill review."""
        path = self.questions_dir / f"{record.id}.md"
        if not path.exists():
            return
        frontmatter, body = read_markdown_file(path)
        frontmatter.update(
            {
                "ease_factor": record.ease_factor,
                "interval_days": record.interval_days,
                "repetitions": record.repetitions,
                "next_review_date": record.next_review_date,
                "last_reviewed": record.last_reviewed,
                "last_quality": record.last_quality,
            }
        )
        write_markdown_file(path, frontmatter, body)

    def update_question_after_judge(self, record: QuestionRecord) -> None:
        """Rewrite topic/judge_score/rationale once the judge has scored an
        answer that was already streamed back with a provisional (or no)
        topic — see LiveInterviewCoachSkill.judge_and_record()."""
        path = self.questions_dir / f"{record.id}.md"
        if not path.exists():
            return
        frontmatter, _ = read_markdown_file(path)
        frontmatter["topic"] = record.topic
        frontmatter["judge_score"] = record.judge_score
        write_markdown_file(
            path,
            frontmatter,
            f"## Question\n\n{record.question_text}\n\n"
            f"## Answer\n\n{record.answer_text}\n\n"
            f"## Judge rationale\n\n{record.judge_rationale}",
        )
        if self.vector_store:
            self.vector_store.upsert(
                doc_id=f"question:{self.candidate_id}:{record.id}",
                text=f"{record.question_text}\n\n{record.answer_text}",
                candidate_id=self.candidate_id,
                doc_type="question",
                topic=record.topic,
            )
        self.graph.add_edge(f"question:{record.id}", f"topic:{record.topic}", "tests_topic")
        self.graph.save()

    # ── Assessments + derived topic mastery ─────────────────────────────────

    def record_assessment(self, assessment: Assessment) -> TopicSummary:
        with self._lock:
            assessment.candidate_id = self.candidate_id
            assessment.id = assessment.id or _new_id()
            assessment.timestamp = assessment.timestamp or _now_iso()

            write_markdown_file(
                self.assessments_dir / f"{assessment.id}.md",
                {
                    "id": assessment.id,
                    "topic": assessment.topic,
                    "question_ref": assessment.question_ref,
                    "judge_score": assessment.judge_score,
                    "source": assessment.source,
                    "override_reason": assessment.override_reason,
                    "timestamp": assessment.timestamp,
                },
                assessment.rationale,
            )
            return self._recompute_topic_summary(assessment.topic)

    def _assessments_for_topic(self, topic: str) -> list[Assessment]:
        results = []
        for path in sorted(self.assessments_dir.glob("*.md")):
            frontmatter, body = read_markdown_file(path)
            if frontmatter.get("topic") != topic:
                continue
            results.append(
                Assessment(
                    id=frontmatter.get("id", path.stem),
                    candidate_id=self.candidate_id,
                    topic=topic,
                    question_ref=frontmatter.get("question_ref", ""),
                    judge_score=frontmatter.get("judge_score", 0.5),
                    source=frontmatter.get("source", "llm_judge"),
                    rationale=body,
                    override_reason=frontmatter.get("override_reason"),
                    timestamp=frontmatter.get("timestamp", ""),
                )
            )
        return sorted(results, key=lambda a: a.timestamp)

    def _recompute_topic_summary(self, topic: str) -> TopicSummary:
        """Current mastery is a query over assessment history, not a stored
        mutable field (§6.1) — a candidate_override is just another fact and
        naturally wins by being the most recent one."""
        assessments = self._assessments_for_topic(topic)
        if not assessments:
            summary = TopicSummary(topic=topic, candidate_id=self.candidate_id)
        else:
            overrides = [a for a in assessments if a.source == "candidate_override"]
            basis = overrides[-3:] if overrides else assessments[-5:]
            mastery_score = sum(a.judge_score for a in basis) / len(basis)
            summary = TopicSummary(
                topic=topic,
                candidate_id=self.candidate_id,
                mastery_score=round(mastery_score, 3),
                sample_count=len(assessments),
                last_judged_at=assessments[-1].timestamp,
                derived_from=[f"assessments/{a.id}.md" for a in assessments],
                related_topics=self.graph.related_topics(f"topic:{topic}"),
            )

        existing_notes = ""
        existing_path = self.topics_dir / f"{_slugify(topic)}.md"
        if existing_path.exists():
            _, existing_notes = read_markdown_file(existing_path)
        summary.notes = existing_notes

        write_markdown_file(
            existing_path,
            {
                "topic": summary.topic,
                "mastery_score": summary.mastery_score,
                "sample_count": summary.sample_count,
                "last_judged_at": summary.last_judged_at,
                "derived_from": summary.derived_from,
                "related_topics": summary.related_topics,
            },
            summary.notes,
        )
        if self.vector_store:
            self.vector_store.upsert(
                doc_id=f"topic:{self.candidate_id}:{_slugify(topic)}",
                text=f"{summary.topic}\n\n{summary.notes}",
                candidate_id=self.candidate_id,
                doc_type="topic",
                topic=summary.topic,
            )
        return summary

    def get_topic_summary(self, topic: str) -> Optional[TopicSummary]:
        path = self.topics_dir / f"{_slugify(topic)}.md"
        if not path.exists():
            return None
        frontmatter, body = read_markdown_file(path)
        return TopicSummary(
            topic=frontmatter.get("topic", topic),
            candidate_id=self.candidate_id,
            mastery_score=frontmatter.get("mastery_score", 0.5),
            sample_count=frontmatter.get("sample_count", 0),
            last_judged_at=frontmatter.get("last_judged_at", ""),
            derived_from=frontmatter.get("derived_from", []),
            related_topics=frontmatter.get("related_topics", []),
            notes=body,
        )

    def list_topic_summaries(self) -> list[TopicSummary]:
        summaries = []
        for path in sorted(self.topics_dir.glob("*.md")):
            frontmatter, body = read_markdown_file(path)
            summaries.append(
                TopicSummary(
                    topic=frontmatter.get("topic", path.stem),
                    candidate_id=self.candidate_id,
                    mastery_score=frontmatter.get("mastery_score", 0.5),
                    sample_count=frontmatter.get("sample_count", 0),
                    last_judged_at=frontmatter.get("last_judged_at", ""),
                    derived_from=frontmatter.get("derived_from", []),
                    related_topics=frontmatter.get("related_topics", []),
                    notes=body,
                )
            )
        return summaries

    def record_topic_co_occurrence(self, topics: list[str]) -> None:
        self.graph.record_topic_co_occurrence([f"topic:{t}" for t in topics])
        self.graph.save()

    # ── Retrieval for answer generation ─────────────────────────────────────

    # Cheap nearest-topic guess threshold — a full LLM topic classification
    # before generation would blow §2's ~2s first-token budget, so this is a
    # single vector lookup against already-embedded topic notes instead. The
    # LLM judge reclassifies the definitive topic afterward (may differ).
    _TOPIC_GUESS_DISTANCE = 0.5

    def _guess_topic(self, query_text: str) -> Optional[str]:
        if not self.vector_store:
            return None
        result = self.vector_store.query(self.candidate_id, query_text, n_results=1, doc_type="topic")
        ids = result.get("ids", [[]])[0]
        distances = result.get("distances", [[]])[0]
        if not ids or distances[0] > self._TOPIC_GUESS_DISTANCE:
            return None
        return ids[0].split(":")[-1]

    def retrieve_context(self, query_text: str, topic: Optional[str] = None, n_results: int = 3) -> RetrievedContext:
        context = RetrievedContext()
        topic = topic or self._guess_topic(query_text)
        if topic:
            context.topic_summary = self.get_topic_summary(topic)
            for related in self.graph.related_topics(f"topic:{topic}"):
                summary = self.get_topic_summary(related.removeprefix("topic:"))
                if summary:
                    context.related_topic_summaries.append(summary)

        if not self.vector_store:
            return context

        result = self.vector_store.query(
            self.candidate_id, query_text, n_results=n_results, doc_type="answer_bank"
        )
        for doc_id in result.get("ids", [[]])[0]:
            entry_id = doc_id.split(":")[-1]
            entry = self.get_answer_bank_entry(entry_id)
            if entry:
                context.matched_answer_bank.append(entry)

        # Weak topic with no direct answer-bank match of its own — fall back to
        # a related topic's grounded entries via the graph (§6.1).
        if not context.matched_answer_bank and topic:
            for related in self.graph.related_topics(f"topic:{topic}"):
                related_topic = related.removeprefix("topic:")
                result = self.vector_store.query(
                    self.candidate_id, related_topic, n_results=n_results, doc_type="answer_bank"
                )
                for doc_id in result.get("ids", [[]])[0]:
                    entry = self.get_answer_bank_entry(doc_id.split(":")[-1])
                    if entry:
                        context.matched_answer_bank.append(entry)
                if context.matched_answer_bank:
                    break

        return context

    # ── Construction ─────────────────────────────────────────────────────────

    @classmethod
    def from_config(cls, candidate_id: str, config_path: str = "config.yaml") -> "InterviewMemoryStore":
        import yaml

        with open(config_path) as f:
            cfg = yaml.safe_load(f)
        mem_cfg = cfg.get("interview_memory", {})
        data_dir = mem_cfg.get("data_dir", "data")
        vector_store = InterviewVectorStore(Path(data_dir) / "interview_memory_vectors")
        return cls(candidate_id, Path(data_dir) / "interview_memory", vector_store)


def _extract_section(body: str, heading: str) -> str:
    match = re.search(
        rf"^## {re.escape(heading)}\n\n(.*?)(?=\n## |\Z)", body, re.DOTALL | re.MULTILINE
    )
    return match.group(1).strip() if match else ""
