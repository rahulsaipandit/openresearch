"""Pydantic schemas for the application tracker."""

from typing import Literal, Optional
from pydantic import BaseModel, Field

ApplicationStage = Literal[
    "saved",
    "applied",
    "phone_screen",
    "technical",
    "onsite",
    "offer",
    "rejected",
    "withdrawn",
]

ApplicationOutcome = Literal[
    "pending",
    "passed",
    "failed",
    "withdrawn",
    "offer_accepted",
    "offer_declined",
]


class ApplicationRecord(BaseModel):
    id: str                                         # short uuid
    company_name: str
    role_title: str
    created_at: str                                 # ISO datetime of first pipeline run
    last_updated: str
    fit_score: float                                # from FitVerdict.overall_score
    fit_recommendation: str                         # from FitVerdict.recommendation
    stage: ApplicationStage = "saved"
    outcome: ApplicationOutcome = "pending"
    notes: Optional[str] = None
    pipeline_run_count: int = 1                     # how many times prep was regenerated


class ApplicationTracker(BaseModel):
    applications: list[ApplicationRecord] = Field(default_factory=list)

    def to_markdown(self) -> str:
        """Render as a human-readable markdown table."""
        if not self.applications:
            return "_No applications tracked yet._\n"

        header = (
            "| Company | Role | Stage | Outcome | Fit | Recommendation | Last Updated |\n"
            "|---------|------|-------|---------|-----|----------------|-------------|\n"
        )
        rows = []
        for app in sorted(
            self.applications,
            key=lambda a: a.last_updated,
            reverse=True,
        ):
            score_bar = "⬛" * round(app.fit_score / 2) + "⬜" * (5 - round(app.fit_score / 2))
            rows.append(
                f"| {app.company_name} | {app.role_title} | {app.stage} "
                f"| {app.outcome} | {score_bar} {app.fit_score:.1f} "
                f"| {app.fit_recommendation} | {app.last_updated[:10]} |"
            )

        return header + "\n".join(rows) + "\n"
