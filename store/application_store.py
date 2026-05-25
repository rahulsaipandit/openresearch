"""
ApplicationStore — persistent local storage for the application tracker.

Maintains applications.json and applications.md (human-readable table).
The markdown file is always kept in sync after every write.

Usage:
    store  = ApplicationStore()
    record = store.add(company, role, fit_score, fit_recommendation)
    store.update_stage(record.id, "technical", outcome="passed")
    all    = store.list()
    md     = store.to_markdown()
"""

import json
import logging
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from schemas.tracker import ApplicationRecord, ApplicationTracker, ApplicationStage, ApplicationOutcome

logger = logging.getLogger(__name__)

_DEFAULT_DIR  = Path("data")
_lock = threading.Lock()


def _parse_iso(ts: str):
    """Parse an ISO 8601 timestamp string, returning a timezone-aware datetime or epoch."""
    from datetime import datetime, timezone
    try:
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        from datetime import datetime, timezone
        return datetime(1970, 1, 1, tzinfo=timezone.utc)


def _derive_action_items(
    apps, win_rate, most_common_failure, avg_fit_score,
    avg_offers, avg_rejected, by_rec, total
) -> list[str]:
    """
    Generate plain-English action items from tracker analytics.
    Returns up to 5 actionable strings.
    """
    items: list[str] = []

    # Win rate signal
    if total >= 5 and win_rate == 0.0:
        items.append(
            "0% offer rate across all applications — review whether you're targeting roles "
            "in the right fit tier (strong_fit / worth_pursuing) before applying."
        )
    elif total >= 5 and win_rate < 0.10:
        items.append(
            f"Win rate is {win_rate*100:.0f}% — below the 10% benchmark. "
            "Focus applications on roles where fit_score ≥ 7."
        )

    # Failure stage pattern
    if most_common_failure:
        stage_advice = {
            "phone_screen": (
                "Most failures happen at phone screen. "
                "Practice your 90-second intro, your motivation story, and salary framing."
            ),
            "technical": (
                "Most failures happen at the technical round. "
                "Run GET /api/learn/due and do daily mock sessions to close skill gaps."
            ),
            "onsite": (
                "Most failures happen at onsite. "
                "Rehearse full-length mock interviews and tighten your STAR answers — "
                "check /api/learn/due for high-overdue questions."
            ),
        }
        if most_common_failure in stage_advice:
            items.append(stage_advice[most_common_failure])
        else:
            items.append(
                f"Most failures happen at '{most_common_failure}' stage — "
                "review your prep for that specific round type."
            )

    # Fit score gap
    if avg_offers is not None and avg_rejected is not None:
        gap = avg_offers - avg_rejected
        if gap < 1.0:
            items.append(
                f"Fit score doesn't strongly predict outcomes (offers avg {avg_offers}, "
                f"rejections avg {avg_rejected}). Company research and interview execution "
                "matter more than the raw fit score for your applications."
            )
        elif gap >= 2.0:
            items.append(
                f"Fit score is a strong predictor (offers avg {avg_offers} vs rejections avg "
                f"{avg_rejected}). Stop applying to roles where fit_score < 6.5."
            )

    # Recommendation mix
    stretch_count = by_rec.get("stretch", 0) + by_rec.get("not_recommended", 0)
    strong_count  = by_rec.get("strong_fit", 0) + by_rec.get("worth_pursuing", 0)
    if stretch_count > strong_count and total >= 3:
        items.append(
            f"{stretch_count} of your applications are stretch or not-recommended roles "
            f"vs {strong_count} strong/worth-pursuing. Rebalance toward higher-fit roles to "
            "improve pipeline efficiency."
        )

    # Average fit score nudge
    if avg_fit_score is not None and avg_fit_score < 6.0 and total >= 3:
        items.append(
            f"Average fit score across your pipeline is {avg_fit_score}/10. "
            "Consider whether the roles you're pursuing match your current profile, "
            "or update your master profile with your most recent experience."
        )

    if not items:
        items.append(
            "Pipeline looks healthy. Keep tracking outcomes to surface patterns over time."
        )

    return items[:5]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class ApplicationStore:
    def __init__(self, data_dir: Path | str = _DEFAULT_DIR):
        self.data_dir   = Path(data_dir)
        self.json_path  = self.data_dir / "applications.json"
        self.md_path    = self.data_dir / "applications.md"
        self.data_dir.mkdir(parents=True, exist_ok=True)

    # ── Read ──────────────────────────────────────────────────────────────────

    def _load(self) -> ApplicationTracker:
        if not self.json_path.exists():
            return ApplicationTracker()
        try:
            with open(self.json_path, encoding="utf-8") as f:
                return ApplicationTracker(**json.load(f))
        except Exception as e:
            logger.error(f"ApplicationStore._load failed: {e}")
            return ApplicationTracker()

    def list(self) -> list[ApplicationRecord]:
        return self._load().applications

    def get(self, application_id: str) -> Optional[ApplicationRecord]:
        for app in self._load().applications:
            if app.id == application_id:
                return app
        return None

    def to_markdown(self) -> str:
        return self._load().to_markdown()

    # ── Write ─────────────────────────────────────────────────────────────────

    def _save(self, tracker: ApplicationTracker) -> None:
        """Write JSON + regenerate markdown (atomic JSON write)."""
        tmp = self.json_path.with_suffix(".tmp")
        try:
            tmp.write_text(tracker.model_dump_json(indent=2), encoding="utf-8")
            tmp.replace(self.json_path)
            self.md_path.write_text(
                "# Application Tracker\n\n" + tracker.to_markdown(),
                encoding="utf-8",
            )
        except Exception as e:
            tmp.unlink(missing_ok=True)
            logger.error(f"ApplicationStore._save failed: {e}")
            raise

    def add(
        self,
        company_name: str,
        role_title: str,
        fit_score: float,
        fit_recommendation: str,
    ) -> ApplicationRecord:
        """
        Log a new pipeline run. If an entry for the same company+role already
        exists, increment its run_count and refresh the fit score instead of
        creating a duplicate.
        """
        with _lock:
            tracker = self._load()
            now = _now()

            # Check for existing entry (same company + role, case-insensitive)
            for app in tracker.applications:
                if (app.company_name.lower() == company_name.lower()
                        and app.role_title.lower() == role_title.lower()):
                    app.fit_score          = fit_score
                    app.fit_recommendation = fit_recommendation
                    app.pipeline_run_count += 1
                    app.last_updated        = now
                    self._save(tracker)
                    return app

            record = ApplicationRecord(
                id=str(uuid.uuid4())[:8],
                company_name=company_name,
                role_title=role_title,
                created_at=now,
                last_updated=now,
                fit_score=fit_score,
                fit_recommendation=fit_recommendation,
            )
            tracker.applications.append(record)
            self._save(tracker)
            return record

    def update_stage(
        self,
        application_id: str,
        stage: ApplicationStage,
        outcome: Optional[ApplicationOutcome] = None,
        notes: Optional[str] = None,
    ) -> Optional[ApplicationRecord]:
        """Update the stage (and optionally outcome + notes) for an application."""
        with _lock:
            tracker = self._load()
            for app in tracker.applications:
                if app.id == application_id:
                    app.stage        = stage
                    app.last_updated = _now()
                    if outcome is not None:
                        app.outcome = outcome
                    if notes is not None:
                        app.notes = notes
                    self._save(tracker)
                    return app
            return None

    def insights(self) -> dict:
        """
        Analyse the application tracker and surface patterns.

        Returns a dict with no LLM calls — pure analytics over applications.json.

        Fields:
          total_applications      — total entries
          win_rate                — offers / total (0.0–1.0)
          offers                  — count of offer_accepted + offer_declined
          by_stage                — count at each stage (current)
          by_outcome              — count per outcome value
          by_recommendation       — fit_recommendation distribution (strong_fit, etc.)
          stage_funnel            — how many applications reached each stage or beyond
          most_common_failure_stage — the stage where most "failed" outcomes happen
          average_fit_score       — mean fit_score across all applications
          avg_fit_score_offers    — mean fit_score for applications that reached offer
          avg_fit_score_rejections — mean fit_score for failed/rejected applications
          fit_score_gap           — avg_offers minus avg_rejections (higher = good predictor)
          applications_last_30d   — count created in the last 30 days
          top_companies           — list of companies with highest fit scores (max 5)
          action_items            — plain-English list of what to focus on next
        """
        from collections import Counter
        from datetime import datetime, timezone, timedelta

        apps = self._load().applications

        if not apps:
            return {
                "total_applications": 0,
                "message": "No applications tracked yet. Run /api/interview-prep to log your first.",
            }

        total = len(apps)

        # Stage and outcome distributions
        by_stage   = dict(Counter(a.stage   for a in apps))
        by_outcome = dict(Counter(a.outcome for a in apps))
        by_rec     = dict(Counter(a.fit_recommendation for a in apps if a.fit_recommendation))

        # Offer count
        offer_outcomes = {"offer_accepted", "offer_declined"}
        offers = sum(1 for a in apps if a.outcome in offer_outcomes)
        win_rate = round(offers / total, 2) if total > 0 else 0.0

        # Stage funnel — how many applications reached each stage or advanced past it
        stage_order = ["saved", "applied", "phone_screen", "technical", "onsite", "offer",
                       "rejected", "withdrawn"]
        # For funnel, only count forward-progress stages (not rejected/withdrawn as "reached")
        forward_stages = ["saved", "applied", "phone_screen", "technical", "onsite", "offer"]
        stage_index    = {s: i for i, s in enumerate(forward_stages)}
        funnel: dict[str, int] = {}
        for s in forward_stages:
            idx = stage_index[s]
            # Count apps whose stage is at this level OR further along
            count = sum(
                1 for a in apps
                if a.stage in stage_index and stage_index[a.stage] >= idx
            )
            funnel[s] = count

        # Most common failure stage
        failure_stages = Counter(
            a.stage for a in apps
            if a.outcome in ("failed",) or a.stage == "rejected"
        )
        most_common_failure = failure_stages.most_common(1)[0][0] if failure_stages else None

        # Fit score stats
        all_scores      = [a.fit_score for a in apps if a.fit_score is not None]
        offer_scores    = [a.fit_score for a in apps
                          if a.outcome in offer_outcomes and a.fit_score is not None]
        rejected_scores = [a.fit_score for a in apps
                          if (a.outcome == "failed" or a.stage == "rejected")
                          and a.fit_score is not None]

        avg_all      = round(sum(all_scores)   / len(all_scores),    1) if all_scores      else None
        avg_offers   = round(sum(offer_scores)  / len(offer_scores),  1) if offer_scores    else None
        avg_rejected = round(sum(rejected_scores) / len(rejected_scores), 1) if rejected_scores else None
        fit_gap      = round(avg_offers - avg_rejected, 1) if (avg_offers and avg_rejected) else None

        # Applications in last 30 days
        now    = datetime.now(timezone.utc)
        cutoff = now - timedelta(days=30)
        recent = sum(
            1 for a in apps
            if a.created_at and _parse_iso(a.created_at) >= cutoff
        )

        # Top companies by fit score (max 5)
        scored = sorted(
            [a for a in apps if a.fit_score is not None],
            key=lambda a: a.fit_score,
            reverse=True,
        )
        top_companies = [
            {"company": a.company_name, "role": a.role_title, "fit_score": a.fit_score,
             "stage": a.stage, "outcome": a.outcome}
            for a in scored[:5]
        ]

        # Actionable insights
        action_items = _derive_action_items(
            apps=apps,
            win_rate=win_rate,
            most_common_failure=most_common_failure,
            avg_fit_score=avg_all,
            avg_offers=avg_offers,
            avg_rejected=avg_rejected,
            by_rec=by_rec,
            total=total,
        )

        return {
            "total_applications":         total,
            "win_rate":                   win_rate,
            "offers":                     offers,
            "by_stage":                   by_stage,
            "by_outcome":                 by_outcome,
            "by_recommendation":          by_rec,
            "stage_funnel":               funnel,
            "most_common_failure_stage":  most_common_failure,
            "average_fit_score":          avg_all,
            "avg_fit_score_offers":       avg_offers,
            "avg_fit_score_rejections":   avg_rejected,
            "fit_score_gap":              fit_gap,
            "applications_last_30d":      recent,
            "top_companies":              top_companies,
            "action_items":               action_items,
        }

    @classmethod
    def from_config(cls, config_path: str = "config.yaml") -> "ApplicationStore":
        import yaml
        with open(config_path) as f:
            cfg = yaml.safe_load(f)
        data_dir = cfg.get("interview_research", {}).get("data_dir", "data")
        return cls(Path(data_dir))
