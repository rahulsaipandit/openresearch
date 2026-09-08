"""Tests for the SM-2 pre_interview_drill skill over interview cognitive memory."""

from pathlib import Path

import pytest

from agents.interview.skills.pre_interview_drill import PreInterviewDrillSkill
from memory.interview_memory import InterviewMemoryStore
from schemas.interview_memory import QuestionRecord


@pytest.fixture
def store(tmp_path: Path) -> InterviewMemoryStore:
    return InterviewMemoryStore("cand_drill", base_dir=tmp_path)


@pytest.fixture
def skill() -> PreInterviewDrillSkill:
    return PreInterviewDrillSkill()


def _make_question(store: InterviewMemoryStore, text: str) -> QuestionRecord:
    return store.record_question(
        QuestionRecord(id="", candidate_id="", session_id="s1", question_text=text, topic="behavioral")
    )


def test_new_question_is_due_immediately(store, skill):
    record = _make_question(store, "Tell me about a time you failed.")
    due = skill.due_today(store)
    assert any(d["id"] == record.id for d in due)


def test_record_review_failure_resets_interval(store, skill):
    record = _make_question(store, "Tell me about a conflict.")
    updated = skill.record_review(store, record.id, quality=1)
    assert updated.repetitions == 0
    assert updated.interval_days == 1


def test_record_review_success_advances_interval(store, skill):
    record = _make_question(store, "Describe a leadership moment.")
    r1 = skill.record_review(store, record.id, quality=4)
    assert r1.repetitions == 1
    assert r1.interval_days == 1

    r2 = skill.record_review(store, record.id, quality=4)
    assert r2.repetitions == 2
    assert r2.interval_days == 6

    r3 = skill.record_review(store, record.id, quality=5)
    assert r3.repetitions == 3
    assert r3.interval_days > 6  # round(6 * EF)


def test_reviewed_question_no_longer_due_today(store, skill):
    record = _make_question(store, "What's your biggest weakness?")
    skill.record_review(store, record.id, quality=5)
    due_ids = [d["id"] for d in skill.due_today(store)]
    assert record.id not in due_ids


def test_apply_dispatches_by_action(store, skill):
    record = _make_question(store, "Why this company?")
    result = skill.apply(store, action="due_today")
    assert any(d["id"] == record.id for d in result)

    reviewed = skill.apply(store, action="record_review", question_id=record.id, quality=3)
    assert reviewed.last_quality == 3

    with pytest.raises(ValueError):
        skill.apply(store, action="bogus")


def test_invalid_quality_rejected(store, skill):
    record = _make_question(store, "A question.")
    with pytest.raises(ValueError):
        skill.record_review(store, record.id, quality=9)
