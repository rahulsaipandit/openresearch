"""Pydantic schemas for the Executive Board pipeline."""

from typing import Literal, Optional
from pydantic import BaseModel, Field


class Project(BaseModel):
    name: str
    status: Literal["on_track", "at_risk", "blocked", "completed"] = "on_track"
    owner: Optional[str] = None
    due_date: Optional[str] = None
    blockers: list[str] = Field(default_factory=list)
    progress_pct: Optional[int] = None


class Risk(BaseModel):
    description: str
    severity: Literal["low", "medium", "high", "critical"] = "medium"
    owner: Optional[str] = None
    mitigation: Optional[str] = None


class Decision(BaseModel):
    title: str
    description: str
    owner: Optional[str] = None
    due_date: Optional[str] = None
    options: list[str] = Field(default_factory=list)
    recommended: Optional[str] = None


class Initiative(BaseModel):
    name: str
    description: str
    status: Literal["planning", "active", "blocked", "complete"] = "active"
    teams_involved: list[str] = Field(default_factory=list)
    target_date: Optional[str] = None


class OrgMetrics(BaseModel):
    total_headcount: int = 0
    open_roles: int = 0
    sprint_velocity_trend: Optional[Literal["improving", "stable", "declining"]] = None
    budget_utilization_pct: Optional[float] = None
    projects_at_risk_count: int = 0


class TeamStatus(BaseModel):
    vp_name: str
    team_name: str
    headcount: int = 0
    active_projects: list[Project] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    morale_signal: Optional[Literal["green", "yellow", "red"]] = None
    budget_status: Optional[Literal["on_track", "at_risk", "over"]] = None
    notes: Optional[str] = None


class OrgSnapshot(BaseModel):
    snapshot_date: str
    teams: list[TeamStatus] = Field(default_factory=list)
    org_metrics: OrgMetrics = Field(default_factory=OrgMetrics)
    active_initiatives: list[Initiative] = Field(default_factory=list)
    open_risks: list[Risk] = Field(default_factory=list)
    decisions_pending: list[Decision] = Field(default_factory=list)
    raw_input: Optional[str] = None     # original paste / JSON before normalization


class Conflict(BaseModel):
    description: str
    parties: list[str] = Field(default_factory=list)
    severity: Literal["low", "medium", "high"] = "medium"
    suggested_resolution: Optional[str] = None


class ActionItem(BaseModel):
    description: str
    owner: str
    due_date: Optional[str] = None
    priority: Literal["low", "medium", "high"] = "medium"


class BoardMemberView(BaseModel):
    agent_id: str
    role: str
    key_findings: list[str] = Field(default_factory=list)
    risks: list[Risk] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    questions_for_ceo: list[str] = Field(default_factory=list)
    confidence: float = 0.8


class ConflictReport(BaseModel):
    conflicts: list[Conflict] = Field(default_factory=list)
    resource_contentions: list[str] = Field(default_factory=list)
    timeline_clashes: list[str] = Field(default_factory=list)
    summary: str = ""


class BoardBriefing(BaseModel):
    session_date: str
    mode: Literal["weekly_review", "decision_advisory", "health_scan"]
    executive_summary: str
    org_health_score: float             # 0-10
    red_flags: list[str] = Field(default_factory=list)
    cross_team_conflicts: list[Conflict] = Field(default_factory=list)
    top_priorities: list[str] = Field(default_factory=list)
    action_items: list[ActionItem] = Field(default_factory=list)
    board_member_views: list[BoardMemberView] = Field(default_factory=list)
    decisions_recommended: list[Decision] = Field(default_factory=list)


class BoardSessionInput(BaseModel):
    mode: Literal["weekly_review", "decision_advisory", "health_scan"] = "weekly_review"
    context: Optional[str] = None       # decision proposal text for advisory mode
    data_sources: list[str] = Field(default_factory=list)  # ["jira", "linear", "notion"]
    org_snapshot: Optional[OrgSnapshot] = None   # pre-built snapshot (manual paste)
    raw_paste: Optional[str] = None     # fallback: plain text / JSON paste
