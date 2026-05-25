"""Pydantic schemas for the SM-2 skills learning tracker."""

from typing import Optional
from pydantic import BaseModel, Field


class TrackedQuestion(BaseModel):
    """One question under SM-2 spaced-repetition management."""
    id: str                                     # sha256[:12] of question text
    question: str
    category: str                               # behavioural | technical | culture_fit | curveball
    company_name: str
    role_title: str

    # SM-2 state
    ease_factor: float = 2.5                    # EF: starts at 2.5, min 1.3
    interval: int = 1                           # days until next review
    repetitions: int = 0                        # successful reviews in a row
    next_review_date: str = ""                  # ISO date; empty = due immediately
    last_reviewed: Optional[str] = None         # ISO date of last review
    last_quality: Optional[int] = None          # 0-5 score from last review

    # Context for the review session
    notes: Optional[str] = None                 # user can annotate after a session


class ReviewResult(BaseModel):
    question_id: str
    quality: int                                # 0-5 (0=blackout, 3=correct with effort, 5=perfect)
    notes: Optional[str] = None


class DueQuestion(BaseModel):
    """A question surfaced for today's review session."""
    tracked: TrackedQuestion
    days_overdue: int                           # 0 = due today, >0 = overdue


class SkillsBank(BaseModel):
    """Full persisted state for the skills tracker."""
    questions: list[TrackedQuestion] = Field(default_factory=list)

    def due_today(self, as_of_date: str) -> list[DueQuestion]:
        """
        Return all questions whose next_review_date is on or before as_of_date.
        Sorted: most overdue first, then by category.
        """
        from datetime import date

        today = date.fromisoformat(as_of_date)
        due: list[DueQuestion] = []

        for q in self.questions:
            if not q.next_review_date:
                due.append(DueQuestion(tracked=q, days_overdue=0))
                continue
            review_date = date.fromisoformat(q.next_review_date)
            if review_date <= today:
                due.append(DueQuestion(
                    tracked=q,
                    days_overdue=(today - review_date).days,
                ))

        due.sort(key=lambda d: (-d.days_overdue, d.tracked.category))
        return due
