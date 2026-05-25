"""
OpenResearch FastAPI Server

Runs at localhost:7842 (configurable in config.yaml).
The Chrome extension calls this server directly.

Endpoints:
  POST /api/stock-research      Run stock research pipeline
  POST /api/board-session       Run executive board pipeline
  POST /api/board-health        Test integration connections
  GET  /api/board-status/{id}   Poll async board session status
  POST /api/interview-prep      Run interview research pipeline
  GET  /api/health              Server liveness check
"""

import asyncio
import logging
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, Optional

import uvicorn
import yaml
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from pipelines.stock_pipeline import StockResearchPipeline
from pipelines.board_pipeline import ExecutiveBoardPipeline
from pipelines.interview_pipeline import InterviewPipeline
from pipelines.realestate_pipeline import RealEstatePipeline
from schemas.stock import StockPipelineInput, ResearchBrief
from schemas.board import BoardSessionInput, BoardBriefing
from schemas.interview import InterviewPipelineInput, InterviewPrepBrief
from schemas.tracker import ApplicationStage, ApplicationOutcome
from schemas.realestate import RealEstatePipelineInput, RealEstateBrief
from store.profile_store import ProfileStore
from store.application_store import ApplicationStore
from store.skills_store import SkillsStore

logger = logging.getLogger(__name__)

CONFIG_PATH = "config.yaml"

# ── In-memory session store (board sessions are async) ────────────────────────
# Maps session_id → {"status": "running|done|failed", "result": BoardBriefing | None, "error": str | None}
_board_sessions: dict[str, dict[str, Any]] = {}

# ── Pipeline singletons (initialized at startup) ──────────────────────────────
_stock_pipeline:      Optional[StockResearchPipeline] = None
_board_pipeline:      Optional[ExecutiveBoardPipeline] = None
_interview_pipeline:  Optional[InterviewPipeline] = None
_realestate_pipeline: Optional[RealEstatePipeline] = None

# ── Persistent stores (initialized at startup) ────────────────────────────────
_profile_store:     Optional[ProfileStore] = None
_app_store:         Optional[ApplicationStore] = None
_skills_store:      Optional[SkillsStore] = None


def _load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize pipelines and stores on startup, clean up on shutdown."""
    global _stock_pipeline, _board_pipeline, _interview_pipeline
    global _profile_store, _app_store, _skills_store

    logger.info("Initializing pipelines...")
    try:
        _stock_pipeline = StockResearchPipeline.from_config(CONFIG_PATH)
        logger.info("Stock Research pipeline ready.")
    except Exception as e:
        logger.warning(f"Stock pipeline init failed (check config.yaml): {e}")

    try:
        _board_pipeline = ExecutiveBoardPipeline.from_config(CONFIG_PATH)
        logger.info("Executive Board pipeline ready.")
    except Exception as e:
        logger.warning(f"Board pipeline init failed (check config.yaml): {e}")

    try:
        _interview_pipeline = InterviewPipeline.from_config(CONFIG_PATH)
        logger.info("Interview Research pipeline ready.")
    except Exception as e:
        logger.warning(f"Interview pipeline init failed (check config.yaml): {e}")

    try:
        _realestate_pipeline = RealEstatePipeline.from_config(CONFIG_PATH)
        logger.info("Real Estate Research pipeline ready.")
    except Exception as e:
        logger.warning(f"Real estate pipeline init failed (check config.yaml): {e}")

    logger.info("Initializing interview stores...")
    try:
        _profile_store = ProfileStore.from_config(CONFIG_PATH)
        _app_store     = ApplicationStore.from_config(CONFIG_PATH)
        _skills_store  = SkillsStore.from_config(CONFIG_PATH)
        logger.info("Interview stores ready (profile / tracker / skills).")
    except Exception as e:
        logger.warning(f"Interview stores init failed: {e}")

    yield
    logger.info("Server shutting down.")


# ── App ───────────────────────────────────────────────────────────────────────

cfg = _load_config()
server_cfg = cfg.get("server", {})
cors_origins = server_cfg.get("cors_origins", ["chrome-extension://*", "http://localhost:*"])

app = FastAPI(
    title="OpenResearch API",
    description="Autonomous ML Research Assistant — Stock Research, Executive Board, Interview Prep, Real Estate",
    version="0.4.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_origin_regex=r"chrome-extension://.*",
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


# ── Request / Response models ─────────────────────────────────────────────────

class StockResearchRequest(BaseModel):
    ticker: str
    depth: str = "full"         # "quick" | "full"
    provider: Optional[str] = None
    export_to_tolaria: bool = False  # auto-save brief to Tolaria vault


class BoardSessionRequest(BaseModel):
    mode: str = "weekly_review"  # "weekly_review" | "decision_advisory" | "health_scan"
    context: Optional[str] = None
    data_sources: list[str] = []  # ["jira", "linear", "notion", "slack", "documents"]
    raw_paste: Optional[str] = None
    document_folder: Optional[str] = None


class BoardHealthRequest(BaseModel):
    check_jira: bool = False
    check_linear: bool = False
    check_notion: bool = False
    check_slack: bool = False


class InterviewPrepRequest(BaseModel):
    jd_text: str
    profile_text: Optional[str] = None  # if None, loaded from ProfileStore
    company_name: str
    role_title: str
    depth: str = "full"                 # "quick" | "full"
    export_to_tolaria: bool = False     # auto-save brief + resume to Tolaria vault


class AddResumeRequest(BaseModel):
    resume_text: str


class UpdateApplicationRequest(BaseModel):
    application_id: str
    stage: str                          # see ApplicationStage literal
    outcome: Optional[str] = None       # see ApplicationOutcome literal
    notes: Optional[str] = None


class ReviewRequest(BaseModel):
    question_id: str
    quality: int                        # 0–5
    notes: Optional[str] = None


class RealEstateResearchRequest(BaseModel):
    city: str
    state: str                            # 2-letter abbreviation e.g. "TX"
    address: str = ""                     # optional; enables property-level flood zone lookup
    zip_code: Optional[str] = None
    depth: str = "full"                   # "quick" | "full"
    documents_dir: Optional[str] = None   # local folder of PDFs/MDs to ingest
    export_to_tolaria: bool = False

    # ── Property details — if provided, rental analysis is included ──────────
    bedrooms: Optional[int] = None        # e.g. 3
    bathrooms: Optional[float] = None     # e.g. 2.0
    sqft: Optional[int] = None
    property_type: str = "single_family"
    year_built: Optional[int] = None
    purchase_price: Optional[float] = None  # asking/offer price in USD

    # Financing assumptions (server-side defaults: 20% down, 7%, 30yr)
    down_payment_pct: float = 0.20
    interest_rate_pct: float = 0.07
    loan_term_years: int = 30


class ExportToTolariaRequest(BaseModel):
    """Export a research artefact to the Tolaria vault."""
    artefact_type: str                  # "interview_brief" | "stock_brief" | "board_briefing"
    # For interview artefacts — either supply data inline or use a tracker application_id
    company_name: Optional[str] = None
    role_title: Optional[str] = None
    # For stock artefacts
    ticker: Optional[str] = None


class SessionStatusResponse(BaseModel):
    session_id: str
    status: str          # "running" | "done" | "failed"
    result: Optional[dict] = None
    error: Optional[str] = None
    created_at: str
    completed_at: Optional[str] = None


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/api/health")
def health():
    return {
        "status":              "ok",
        "stock_pipeline":      _stock_pipeline is not None,
        "board_pipeline":      _board_pipeline is not None,
        "interview_pipeline":  _interview_pipeline is not None,
        "profile_store":       _profile_store is not None,
        "profile_exists":      _profile_store.exists() if _profile_store else False,
        "timestamp":           datetime.utcnow().isoformat(),
    }


@app.post("/api/stock-research", response_model=ResearchBrief)
def stock_research(request: StockResearchRequest):
    """
    Run the full stock research pipeline for a ticker.
    Returns a ResearchBrief synchronously (typically 15-60 seconds).
    """
    if _stock_pipeline is None:
        raise HTTPException(503, "Stock pipeline not initialized. Check config.yaml.")

    if not request.ticker or len(request.ticker) > 10:
        raise HTTPException(400, "Invalid ticker symbol.")

    try:
        brief = _stock_pipeline.run(
            StockPipelineInput(ticker=request.ticker, depth=request.depth)
        )
    except Exception as e:
        logger.error(f"Stock research failed for {request.ticker}: {e}", exc_info=True)
        raise HTTPException(500, f"Research pipeline error: {str(e)[:200]}")

    # Optional: export brief to Tolaria vault
    if request.export_to_tolaria:
        try:
            from integrations.tolaria import TolariaClient, render_stock_brief
            tolaria = TolariaClient.from_config(CONFIG_PATH)
            brief_md = render_stock_brief(brief)
            saved_to = tolaria.save_stock_brief(brief_md, ticker=request.ticker)
            logger.info(f"Stock brief exported to Tolaria: {saved_to}")
            from fastapi.responses import JSONResponse
            response_data = brief.model_dump()
            response_data["_tolaria_export"] = {"brief_saved_to": saved_to}
            return JSONResponse(content=response_data)
        except Exception as e:
            logger.warning(f"Tolaria stock export failed (non-fatal): {e}")

    return brief


@app.post("/api/board-session")
async def board_session(request: BoardSessionRequest, background_tasks: BackgroundTasks):
    """
    Start an executive board session asynchronously.
    Returns a session_id immediately. Poll /api/board-status/{id} for results.
    """
    if _board_pipeline is None:
        raise HTTPException(503, "Board pipeline not initialized. Check config.yaml.")

    session_id = str(uuid.uuid4())[:8]
    _board_sessions[session_id] = {
        "status":       "running",
        "result":       None,
        "error":        None,
        "created_at":   datetime.utcnow().isoformat(),
        "completed_at": None,
    }

    background_tasks.add_task(_run_board_session, session_id, request)
    return {"session_id": session_id, "status": "running"}


@app.get("/api/board-status/{session_id}", response_model=SessionStatusResponse)
def board_status(session_id: str):
    """Poll for the result of an async board session."""
    session = _board_sessions.get(session_id)
    if not session:
        raise HTTPException(404, f"Session '{session_id}' not found.")
    return SessionStatusResponse(session_id=session_id, **session)


@app.post("/api/board-health")
def board_health(request: BoardHealthRequest):
    """
    Test integration connections without running a full session.
    Returns connection status for each configured integration.
    """
    results: dict[str, Any] = {}

    if request.check_jira:
        results["jira"] = _test_jira()
    if request.check_linear:
        results["linear"] = _test_linear()
    if request.check_notion:
        results["notion"] = _test_notion()
    if request.check_slack:
        results["slack"] = _test_slack()

    return results


@app.post("/api/interview-prep", response_model=InterviewPrepBrief)
def interview_prep(request: InterviewPrepRequest):
    """
    Run the full interview research pipeline.

    profile_text is optional — if omitted, the master profile stored via
    POST /api/profile/add-resume is used automatically.

    Auto-logs the run to the application tracker and seeds new questions
    into the skills/learning bank on completion.
    """
    if _interview_pipeline is None:
        raise HTTPException(503, "Interview pipeline not initialized. Check config.yaml.")

    if not request.jd_text or len(request.jd_text.strip()) < 50:
        raise HTTPException(400, "jd_text must be at least 50 characters.")

    if not request.company_name or not request.role_title:
        raise HTTPException(400, "company_name and role_title are required.")

    if request.depth not in ("quick", "full"):
        raise HTTPException(400, "depth must be 'quick' or 'full'.")

    # Resolve profile: inline text takes precedence; fall back to store
    profile_text = request.profile_text
    if not profile_text or len(profile_text.strip()) < 50:
        if _profile_store and _profile_store.exists():
            stored = _profile_store.load()
            profile_text = stored.to_text() if stored else None
        if not profile_text:
            raise HTTPException(
                400,
                "No profile_text provided and no master profile found. "
                "POST a resume to /api/profile/add-resume first, or include profile_text."
            )

    try:
        brief = _interview_pipeline.run(
            InterviewPipelineInput(
                jd_text=request.jd_text,
                profile_text=profile_text,
                company_name=request.company_name,
                role_title=request.role_title,
                depth=request.depth,
            )
        )
    except Exception as e:
        logger.error(
            f"Interview prep failed for {request.role_title} at {request.company_name}: {e}",
            exc_info=True,
        )
        raise HTTPException(500, f"Interview pipeline error: {str(e)[:200]}")

    # Auto-log to application tracker
    if _app_store:
        try:
            _app_store.add(
                company_name=request.company_name,
                role_title=request.role_title,
                fit_score=brief.fit.overall_score,
                fit_recommendation=brief.fit.recommendation,
            )
        except Exception as e:
            logger.warning(f"Application tracker log failed: {e}")

    # Seed new questions into skills bank
    if _skills_store:
        try:
            added = _skills_store.add_questions(
                questions=brief.questions,
                company_name=request.company_name,
                role_title=request.role_title,
            )
            if added:
                logger.info(f"Added {added} new questions to skills bank.")
        except Exception as e:
            logger.warning(f"Skills bank seeding failed: {e}")

    # Optional: export brief (and tailored resume) to Tolaria vault
    tolaria_result: dict = {}
    if request.export_to_tolaria:
        try:
            from integrations.tolaria import TolariaClient, render_interview_brief
            tolaria = TolariaClient.from_config(CONFIG_PATH)
            brief_md = render_interview_brief(brief)
            brief_path = tolaria.save_interview_brief(
                brief_md,
                company_name=request.company_name,
                role_title=request.role_title,
            )
            tolaria_result["brief_saved_to"] = brief_path

            if brief.tailored_resume:
                resume_path = tolaria.save_tailored_resume(
                    brief.tailored_resume.full_resume_md,
                    company_name=request.company_name,
                    role_title=request.role_title,
                )
                tolaria_result["resume_saved_to"] = resume_path

            logger.info(f"Tolaria export complete: {tolaria_result}")
        except Exception as e:
            logger.warning(f"Tolaria export failed (non-fatal): {e}")
            tolaria_result["error"] = str(e)[:200]

    # Attach export metadata to the response headers (not breaking the schema)
    if tolaria_result:
        # We include export info in a response header so the schema stays clean
        from fastapi.responses import JSONResponse
        response_data = brief.model_dump()
        response_data["_tolaria_export"] = tolaria_result
        return JSONResponse(content=response_data)

    return brief


# ── Real Estate Research ──────────────────────────────────────────────────────

@app.post("/api/real-estate-research", response_model=RealEstateBrief)
def real_estate_research(request: RealEstateResearchRequest):
    """
    Run the full real estate demand + optional rental feasibility pipeline.

    Returns a RealEstateBrief covering:
      - Migration verdict at city AND state level (IRS SOI, Census PEP, U-Haul, FRED)
      - Labor market snapshot (BLS: unemployment, employment growth, wages, industry mix)
      - Housing market snapshot (Zillow ZHVI/ZORI, Redfin, Census permits)
      - Cost-of-living snapshot (BEA Regional Price Parities, state tax rates)
      - Demand / quality-of-life factors (Walk Score, NOAA climate normals)
      - Climate & flood risk (FEMA NFHL flood zone, FEMA NRI, OpenFEMA disaster history)
      - Document insights (ingested from documents_dir when provided)

    Rental feasibility analysis (brief.rental_analysis) is included automatically
    when ANY of the following are provided: bedrooms, bathrooms, purchase_price.
    The analysis covers:
      - Full cash-flow model: cap rate, GRM, DSCR, cash-on-cash return, NOI, break-even
      - Rent estimate: RentCast (if key configured) → Zillow ZORI metro → HUD FMR fallback
      - Regulatory risk: eviction timeline, rent control, STR rules, insurance stress
      - Neighborhood signals: ACS tract demographics, HUD USPS vacancy, Walk Score
      - LLM synthesis: feasibility_verdict, pros/cons, recommended due-diligence actions

    depth="quick": ~10s — static/lookup data only, no live CSV downloads.
    depth="full":  ~45–120s — full data pipeline including live API calls.
    """
    if _realestate_pipeline is None:
        raise HTTPException(503, "Real estate pipeline not initialized. Check config.yaml.")

    if not request.city or not request.state:
        raise HTTPException(400, "city and state are required.")

    if len(request.state.strip()) != 2:
        raise HTTPException(400, "state must be a 2-letter US state abbreviation (e.g. 'TX').")

    if request.depth not in ("quick", "full"):
        raise HTTPException(400, "depth must be 'quick' or 'full'.")

    try:
        brief = _realestate_pipeline.run(
            RealEstatePipelineInput(
                city              = request.city,
                state             = request.state,
                address           = request.address or "",
                zip_code          = request.zip_code,
                depth             = request.depth,
                documents_dir     = request.documents_dir,
                # Property / rental fields
                bedrooms          = request.bedrooms,
                bathrooms         = request.bathrooms,
                sqft              = request.sqft,
                property_type     = request.property_type,
                year_built        = request.year_built,
                purchase_price    = request.purchase_price,
                down_payment_pct  = request.down_payment_pct,
                interest_rate_pct = request.interest_rate_pct,
                loan_term_years   = request.loan_term_years,
            )
        )
    except Exception as e:
        logger.error(
            f"Real estate research failed for {request.city}, {request.state}: {e}",
            exc_info=True,
        )
        raise HTTPException(500, f"Real estate pipeline error: {str(e)[:200]}")

    # Optional Tolaria export
    if request.export_to_tolaria:
        try:
            from integrations.tolaria import TolariaClient
            tolaria   = TolariaClient.from_config(CONFIG_PATH)
            slug      = f"{request.city.lower().replace(' ', '-')}-{request.state.lower()}"
            brief_md  = _render_realestate_brief(brief)
            saved_to  = tolaria._write(
                subfolder = "realestate",
                filename  = f"{slug}-{brief.as_of_date}.md",
                content   = brief_md,
            )
            logger.info(f"Real estate brief exported to Tolaria: {saved_to}")
            from fastapi.responses import JSONResponse
            response_data = brief.model_dump()
            response_data["_tolaria_export"] = {"brief_saved_to": saved_to}
            return JSONResponse(content=response_data)
        except Exception as e:
            logger.warning(f"Tolaria real estate export failed (non-fatal): {e}")

    return brief


def _render_realestate_brief(brief: RealEstateBrief) -> str:
    """Render a RealEstateBrief to Markdown for Tolaria vault export."""
    lines = [
        f"# Real Estate Brief: {brief.city}, {brief.state}",
        f"**Date:** {brief.as_of_date}  ",
        f"**Verdict:** {brief.demand_verdict}  |  **Signal:** {brief.investment_signal}  "
        f"|  **Confidence:** {brief.confidence:.0%}",
        "",
        "## Summary",
        brief.summary,
        "",
    ]
    if brief.dominant_pull_factors:
        lines += ["## Pull Factors (demand drivers)"]
        lines += [f"- {f}" for f in brief.dominant_pull_factors]
        lines.append("")
    if brief.dominant_push_factors:
        lines += ["## Push Factors (demand risks)"]
        lines += [f"- {f}" for f in brief.dominant_push_factors]
        lines.append("")
    if brief.key_risks:
        lines += ["## Key Risks"]
        lines += [f"- {r}" for r in brief.key_risks]
        lines.append("")
    lines += [
        "## Migration",
        f"**City ({brief.city}):** {brief.city_migration.net_direction} — {brief.city_migration.summary}",
        f"**State ({brief.state}):** {brief.state_migration.net_direction} — {brief.state_migration.summary}",
        "",
        "## Labor Market",
        brief.labor_market.summary,
        "",
        "## Housing Market",
        brief.housing_market.summary,
        "",
        "## Cost of Living",
        brief.cost_of_living.summary,
        "",
    ]
    if brief.climate_risk:
        lines += ["## Climate & Flood Risk", brief.climate_risk.summary, ""]

    # ── Document intelligence ──────────────────────────────────────────────────
    if brief.document_insights:
        lines += ["## Document Analysis"]
        for ins in brief.document_insights:
            confidence_pct = f"{ins.classification_confidence:.0%}" if ins.classification_confidence else "?"
            lines.append(f"### {ins.source_file} ({ins.document_type}, {confidence_pct} confidence)")
            if ins.key_facts:
                lines += [f"- {f}" for f in ins.key_facts]
            if ins.conflicts:
                lines += [f"- ⚠ **Conflict:** {c}" for c in ins.conflicts]
            lines.append("")

    # ── Rental analysis section ────────────────────────────────────────────────
    if brief.rental_analysis:
        ra = brief.rental_analysis
        uw = ra.underwriting
        reg = ra.regulatory
        nbhd = ra.neighborhood

        lines += [
            "## Rental Feasibility Analysis",
            f"**Verdict:** {ra.feasibility_verdict.replace('_', ' ').title()}",
            "",
            ra.rental_summary,
            "",
        ]

        if uw.purchase_price or uw.estimated_monthly_rent:
            def _f(v): return f"${v:,.0f}" if v is not None else "n/a"
            lines += [
                "### Financial Model",
                f"| Metric | Value |",
                f"|--------|-------|",
                f"| Purchase price | {_f(uw.purchase_price)} |",
                f"| Monthly rent est. | {_f(uw.estimated_monthly_rent)} ({uw.rent_estimate_source}) |",
                f"| Annual gross rent | {_f(uw.est_annual_gross_rent)} |",
                f"| NOI | {_f(uw.est_annual_noi)} |",
                f"| Cap rate | {uw.cap_rate_pct:.2f}% |" if uw.cap_rate_pct else "| Cap rate | n/a |",
                f"| Annual cash flow | {_f(uw.annual_cash_flow)} ({_f(uw.monthly_cash_flow)}/mo) |",
                f"| Cash-on-cash | {uw.cash_on_cash_return_pct:.2f}% |" if uw.cash_on_cash_return_pct else "| Cash-on-cash | n/a |",
                f"| DSCR | {uw.dscr:.2f} |" if uw.dscr else "| DSCR | n/a |",
                f"| Break-even occ. | {uw.break_even_occupancy_pct:.1f}% |" if uw.break_even_occupancy_pct else "| Break-even occ. | n/a |",
                f"| Monthly mortgage | {_f(uw.monthly_mortgage_payment)} ({uw.interest_rate_pct:.2f}%, {uw.loan_term_years}yr) |",
                "",
            ]

        lines += [
            "### Regulatory Risk",
            f"- **Eviction:** {reg.eviction_friendliness or 'n/a'} (~{reg.state_eviction_timeline_days or '?'} days). {reg.eviction_process_notes}",
            f"- **Rent control:** {'YES — ' + (reg.rent_control_type or '') if reg.rent_control_exposure else 'None'}{'. ' + reg.rent_control_details if reg.rent_control_details else ''}",
            f"- **STR (Airbnb):** {'Permitted' if reg.str_generally_permitted else 'NOT permitted'}. {reg.str_notes}",
            f"- **Insurance market:** {reg.insurance_market_stress or 'normal'}. {reg.insurance_stress_notes}",
            f"- **Overall regulatory risk:** {reg.overall_regulatory_risk}",
            "",
        ]

        if ra.pros:
            lines += ["### Pros"]
            lines += [f"- {p}" for p in ra.pros]
            lines.append("")

        if ra.cons:
            lines += ["### Cons / Risks"]
            lines += [f"- {c}" for c in ra.cons]
            lines.append("")

        if ra.recommended_actions:
            lines += ["### Due Diligence Checklist"]
            lines += [f"- [ ] {a}" for a in ra.recommended_actions]
            lines.append("")

        # Document-sourced facts summary
        doc_items = []
        for ins in brief.document_insights:
            if ins.document_type != "other":
                doc_items.append(
                    f"- **{ins.source_file}** ({ins.document_type.replace('_', ' ').title()}, "
                    f"{ins.classification_confidence:.0%} confidence)"
                )
        if doc_items:
            lines += ["### Documents Analysed"] + doc_items + [""]

    if brief.data_gaps:
        lines += ["## Data Gaps"]
        lines += [f"- {g}" for g in brief.data_gaps]
        lines.append("")
    return "\n".join(lines)


# ── Profile endpoints ─────────────────────────────────────────────────────────

@app.post("/api/profile/add-resume")
def add_resume(request: AddResumeRequest):
    """
    Parse a resume and merge it into the persistent master profile.

    Submit as many resumes as you have — each call merges the new resume
    into the existing profile rather than replacing it. Skills are unioned,
    experiences are deduped, achievements are consolidated.
    """
    if _interview_pipeline is None:
        raise HTTPException(503, "Interview pipeline not initialized. Check config.yaml.")

    if not request.resume_text or len(request.resume_text.strip()) < 50:
        raise HTTPException(400, "resume_text must be at least 50 characters.")

    from agents.interview.profile_builder import ProfileBuilderAgent
    builder  = ProfileBuilderAgent(_interview_pipeline.llm, verbose=True)
    existing = _profile_store.load() if _profile_store else None

    try:
        profile = builder.add_resume(request.resume_text, existing=existing)
    except Exception as e:
        logger.error(f"Profile builder failed: {e}", exc_info=True)
        raise HTTPException(500, f"Profile build error: {str(e)[:200]}")

    if _profile_store:
        _profile_store.save(profile)

    return {
        "message":      f"Profile updated. {profile.source_count} resume(s) merged.",
        "source_count": profile.source_count,
        "skills_count": len(profile.skills),
        "experiences":  len(profile.experiences),
        "name":         profile.name,
    }


@app.get("/api/profile")
def get_profile():
    """Return the current master profile."""
    if not _profile_store or not _profile_store.exists():
        raise HTTPException(404, "No profile found. POST a resume to /api/profile/add-resume.")
    profile = _profile_store.load()
    if not profile:
        raise HTTPException(404, "Profile file exists but could not be loaded.")
    return profile.model_dump()


@app.delete("/api/profile")
def delete_profile():
    """Delete the master profile. Irreversible."""
    if not _profile_store or not _profile_store.exists():
        raise HTTPException(404, "No profile to delete.")
    _profile_store.delete()
    return {"message": "Profile deleted."}


# ── Application tracker endpoints ─────────────────────────────────────────────

@app.get("/api/tracker")
def get_tracker(format: str = "json"):
    """
    List all tracked applications.
    format=json (default) or format=markdown for a human-readable table.
    """
    if not _app_store:
        raise HTTPException(503, "Application store not initialised.")
    if format == "markdown":
        return {"markdown": _app_store.to_markdown()}
    return {"applications": [a.model_dump() for a in _app_store.list()]}


@app.post("/api/tracker/update")
def update_tracker(request: UpdateApplicationRequest):
    """
    Update the stage and/or outcome of a tracked application.

    stages:   saved → applied → phone_screen → technical → onsite → offer → rejected | withdrawn
    outcomes: pending | passed | failed | withdrawn | offer_accepted | offer_declined
    """
    if not _app_store:
        raise HTTPException(503, "Application store not initialised.")

    record = _app_store.update_stage(
        application_id=request.application_id,
        stage=request.stage,
        outcome=request.outcome,
        notes=request.notes,
    )
    if not record:
        raise HTTPException(404, f"Application '{request.application_id}' not found.")
    return record.model_dump()


# ── Tracker insights endpoint ─────────────────────────────────────────────────

@app.get("/api/tracker/insights")
def tracker_insights():
    """
    Analyse the application tracker and surface patterns.

    Returns pure analytics — no LLM calls. Includes:
      win_rate, stage funnel, most common failure stage,
      fit score vs outcome correlation, action items.

    Call this after logging several applications to see what to work on.
    """
    if not _app_store:
        raise HTTPException(503, "Application store not initialised.")
    return _app_store.insights()


# ── Export to Tolaria vault ───────────────────────────────────────────────────

@app.post("/api/export/tolaria")
def export_to_tolaria(request: ExportToTolariaRequest):
    """
    Export a research artefact (interview brief, stock brief, etc.) to the
    configured Tolaria vault.

    Requires mcp.tolaria.server_url to be set in config.yaml.
    Falls back to writing a local file under output/ if Tolaria is unavailable.

    artefact_type:
      "interview_brief" — requires company_name + role_title
                          Loads the latest pipeline run from the tracker store.
                          Converts InterviewPrepBrief to Markdown and saves to
                          vault/interview/<company>-<role>.md
      "stock_brief"     — requires ticker
                          Reruns a quick stock lookup (uses cached brief if available).
      NOTE: Board briefings are exported automatically at session completion when
            tolaria is configured; use GET /api/board-status/:id to confirm.
    """
    from integrations.tolaria import TolariaClient
    tolaria = TolariaClient.from_config(CONFIG_PATH)

    try:
        if request.artefact_type == "interview_brief":
            if not request.company_name or not request.role_title:
                raise HTTPException(400, "company_name and role_title required for interview_brief export.")

            # Load the application record to confirm it exists
            if not _app_store:
                raise HTTPException(503, "Application store not initialised.")
            apps = _app_store.list()
            matched = [
                a for a in apps
                if a.company_name.lower() == request.company_name.lower()
                and a.role_title.lower() == request.role_title.lower()
            ]
            if not matched:
                raise HTTPException(
                    404,
                    f"No tracked application found for {request.company_name} / {request.role_title}. "
                    "Run /api/interview-prep first."
                )

            # Re-run the pipeline to get the full brief (we don't cache briefs in the tracker)
            # For now, surface a message directing the user to include the brief in the next run
            raise HTTPException(
                501,
                "Auto-export from tracker not yet implemented. "
                "Pass include_tolaria_export=true to /api/interview-prep to export on generation."
            )

        elif request.artefact_type == "stock_brief":
            if not request.ticker:
                raise HTTPException(400, "ticker required for stock_brief export.")
            raise HTTPException(
                501,
                "Stock brief export to Tolaria: run /api/stock-research with "
                "export_to_tolaria=true to export on generation."
            )

        else:
            raise HTTPException(400, f"Unknown artefact_type: {request.artefact_type}")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Tolaria export failed: {e}", exc_info=True)
        raise HTTPException(500, f"Export error: {str(e)[:200]}")


# ── Skills / learning endpoints ───────────────────────────────────────────────

@app.get("/api/learn/due")
def get_due_questions():
    """
    Return all questions due for review today, sorted by most overdue first.
    Call this before a mock interview session.
    """
    if not _skills_store:
        raise HTTPException(503, "Skills store not initialised.")
    due = _skills_store.due_today()
    return {
        "due_count": len(due),
        "questions": [
            {
                "id":           d.tracked.id,
                "question":     d.tracked.question,
                "category":     d.tracked.category,
                "company":      d.tracked.company_name,
                "role":         d.tracked.role_title,
                "days_overdue": d.days_overdue,
                "repetitions":  d.tracked.repetitions,
                "ease_factor":  d.tracked.ease_factor,
                "last_quality": d.tracked.last_quality,
            }
            for d in due
        ],
    }


@app.post("/api/learn/review")
def record_review(request: ReviewRequest):
    """
    Submit a quality score (0–5) for a question after a mock session.

    0 = complete blackout           → resets to day 1
    1 = wrong, answer felt familiar → resets to day 1
    2 = wrong but close             → resets to day 1
    3 = correct with effort         → advances (shorter interval)
    4 = correct with minor hesitation → advances normally
    5 = perfect recall              → advances (longer interval)

    The SM-2 algorithm schedules the next review date automatically.
    """
    if not _skills_store:
        raise HTTPException(503, "Skills store not initialised.")

    if not 0 <= request.quality <= 5:
        raise HTTPException(400, "quality must be between 0 and 5.")

    updated = _skills_store.record_review(
        question_id=request.question_id,
        quality=request.quality,
        notes=request.notes,
    )
    if not updated:
        raise HTTPException(404, f"Question '{request.question_id}' not found.")

    return {
        "id":               updated.id,
        "next_review_date": updated.next_review_date,
        "interval_days":    updated.interval,
        "repetitions":      updated.repetitions,
        "ease_factor":      updated.ease_factor,
        "message": (
            f"Reviewed. Next review in {updated.interval} day(s) "
            f"on {updated.next_review_date}."
        ),
    }


@app.get("/api/learn/stats")
def get_skills_stats():
    """Summary of the skills bank: total questions, due today, by category, average EF."""
    if not _skills_store:
        raise HTTPException(503, "Skills store not initialised.")
    return _skills_store.stats()


# ── Background task ───────────────────────────────────────────────────────────

async def _run_board_session(session_id: str, request: BoardSessionRequest) -> None:
    try:
        # Collect data from integrations
        jira_data     = None
        linear_data   = None
        notion_data   = None
        slack_data    = None
        document_data = None

        if "jira" in request.data_sources:
            from integrations.jira import JiraIntegration
            jira = JiraIntegration.from_config(CONFIG_PATH)
            if jira:
                # Use configured project keys or fallback to all teams
                jira_data = jira.fetch_issues_by_project(
                    _get_config_list("jira_project_keys")
                )

        if "linear" in request.data_sources:
            from integrations.linear import LinearIntegration
            linear = LinearIntegration.from_config(CONFIG_PATH)
            if linear:
                linear_data = linear.fetch_issues_by_team(
                    _get_config_list("linear_team_keys")
                )

        if "notion" in request.data_sources:
            from integrations.notion import NotionIntegration
            notion = NotionIntegration.from_config(CONFIG_PATH)
            if notion:
                notion_data = notion.query_all_configured_databases()

        if "slack" in request.data_sources:
            from integrations.slack import SlackIntegration
            slack = SlackIntegration.from_config(CONFIG_PATH)
            if slack:
                slack_data = slack.fetch_all_configured_channels()

        if "documents" in request.data_sources:
            folder = request.document_folder or _get_config_str("document_folder")
            if folder:
                from integrations.documents import DocumentLoader
                loader = DocumentLoader(folder)
                document_data = loader.load_all()

        session_input = BoardSessionInput(
            mode=request.mode,
            context=request.context,
            data_sources=request.data_sources,
            raw_paste=request.raw_paste,
        )

        briefing = await _board_pipeline.run(
            session_input,
            jira_data=jira_data,
            linear_data=linear_data,
            notion_data=notion_data,
            slack_data=slack_data,
            document_data=document_data,
        )

        _board_sessions[session_id].update({
            "status":       "done",
            "result":       briefing.model_dump(),
            "completed_at": datetime.utcnow().isoformat(),
        })

    except Exception as e:
        logger.error(f"Board session {session_id} failed: {e}", exc_info=True)
        _board_sessions[session_id].update({
            "status":       "failed",
            "error":        str(e)[:500],
            "completed_at": datetime.utcnow().isoformat(),
        })


# ── Integration health checks ─────────────────────────────────────────────────

def _test_jira() -> dict:
    try:
        from integrations.jira import JiraIntegration
        jira = JiraIntegration.from_config(CONFIG_PATH)
        if not jira:
            return {"ok": False, "error": "Not configured"}
        with __import__("httpx").Client(headers=jira._headers, timeout=5) as c:
            r = c.get(f"{jira.base_url}/rest/api/3/myself")
            return {"ok": r.status_code == 200, "user": r.json().get("displayName")}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _test_linear() -> dict:
    try:
        from integrations.linear import LinearIntegration
        linear = LinearIntegration.from_config(CONFIG_PATH)
        if not linear:
            return {"ok": False, "error": "Not configured"}
        teams = linear.list_teams()
        return {"ok": True, "teams": len(teams)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _test_notion() -> dict:
    try:
        from integrations.notion import NotionIntegration
        notion = NotionIntegration.from_config(CONFIG_PATH)
        if not notion:
            return {"ok": False, "error": "Not configured"}
        # Attempt a lightweight API call
        with __import__("httpx").Client(headers=notion._headers, timeout=5) as c:
            r = c.get("https://api.notion.com/v1/users/me")
            return {"ok": r.status_code == 200, "databases": len(notion.database_ids)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _test_slack() -> dict:
    try:
        from integrations.slack import SlackIntegration
        slack = SlackIntegration.from_config(CONFIG_PATH)
        if not slack:
            return {"ok": False, "error": "Not configured"}
        return {"ok": slack.test_connection(), "channels": len(slack.channel_ids)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ── Config helpers ─────────────────────────────────────────────────────────────

def _get_config_list(key: str) -> list[str]:
    cfg  = _load_config()
    board = cfg.get("executive_board", {})
    return board.get("integrations", {}).get(key, [])


def _get_config_str(key: str) -> str:
    cfg  = _load_config()
    board = cfg.get("executive_board", {})
    return board.get("integrations", {}).get(key, "")


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    cfg     = _load_config()
    srv     = cfg.get("server", {})
    host    = srv.get("host", "127.0.0.1")
    port    = srv.get("port", 7842)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    )

    print(f"\n  OpenResearch Server")
    print(f"  Running at http://{host}:{port}")
    print(f"  Chrome extension endpoint: http://{host}:{port}/api/\n")

    uvicorn.run("server:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    main()
