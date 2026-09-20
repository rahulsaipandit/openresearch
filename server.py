"""
OpenResearch FastAPI Server

Runs at localhost:7842 (configurable in config.yaml).
The Chrome extension calls this server directly.

Endpoints:
  POST /api/stock-research      Run stock research pipeline (ticker required)
  POST /api/query               Natural-language front door — extracts ticker(s)/intent, dispatches
  POST /api/stock-compare        Side-by-side comparison of two tickers
  GET  /api/stock-trend/{ticker} Five-year trend + previous-year summary
  GET  /api/watchlist           List watchlist (up to 20 tickers)
  POST /api/watchlist           Add a ticker to the watchlist
  DELETE /api/watchlist/{ticker} Remove a ticker from the watchlist
  GET  /api/watchlist/quotes    Live price snapshot for every watchlist ticker
  GET  /api/alerts              List price alerts
  POST /api/alerts              Create a price alert (ticker, condition, target_price)
  DELETE /api/alerts/{id}       Remove a price alert
  GET  /api/portfolio           List portfolio holdings
  POST /api/portfolio           Add/update a holding (ticker, shares, cost basis)
  DELETE /api/portfolio/{ticker} Remove a holding
  POST /api/portfolio-optimize  Single-period rebalance optimization over current holdings
  POST /api/board-session       Run executive board pipeline
  POST /api/board-health        Test integration connections
  GET  /api/board-status/{id}   Poll async board session status
  POST /api/interview-prep      Run interview research pipeline
  GET  /api/health              Server liveness check

  Interview cognitive memory (Pluely live-coaching integration — see
  docs/openresearch-integration-requirements.md):
  POST   /v1/interview/answer                              Live, retrieval-grounded answer (SSE)
  GET/PUT /v1/interview/profile/{candidate_id}              Résumé/JD/instructions
  GET/POST /v1/interview/answer-bank/{candidate_id}         List/create answer-bank entries
  PUT/DELETE /v1/interview/answer-bank/{candidate_id}/{id}  Update/delete an entry
  GET/POST /v1/interview/documents/{candidate_id}           List/upload ingested documents (RAG)
  DELETE /v1/interview/documents/{candidate_id}/{doc_id}    Delete an ingested document
  GET  /v1/interview/skills                                 List registered skills
  POST /v1/interview/skills/{skill_name}/apply              Apply a skill (e.g. pre_interview_drill)

  Domain answer endpoints (single-tenant, no candidate_id — see §10):
  POST /v1/stock/answer                                     Stock research Q&A (SSE)
  POST /v1/realestate/answer                                Real estate market Q&A (SSE)
"""

import asyncio
import json
import logging
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, Optional

import uvicorn
import yaml
from fastapi import FastAPI, HTTPException, BackgroundTasks, File, Form, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from starlette.background import BackgroundTask

from agents.api_utils import LLMClient
from agents.stock.query_router import QueryRouterAgent
from agents.stock.comparison_analyst import ComparisonAnalystAgent
from agents.stock.trend_analyst import TrendAnalystAgent
from agents.stock.sec_ingest import SECIngestAgent
from agents.stock.sec_qa import SECQAAgent
from agents.stock.document_insights import DocumentInsightsAgent
from agents.stock.xbrl_fallback import XBRLFallbackAgent
from agents.stock.portfolio_optimizer import PortfolioOptimizerAgent
from agents.stock.quote_fetcher import get_quotes
from pipelines.stock_pipeline import StockResearchPipeline
from pipelines.primer_pipeline import ResearchPrimerPipeline
from pipelines.board_pipeline import ExecutiveBoardPipeline
from pipelines.interview_pipeline import InterviewPipeline
from pipelines.realestate_pipeline import RealEstatePipeline
from schemas.stock import StockPipelineInput, ResearchBrief, TrendData
from schemas.query import QueryRouterResult
from schemas.comparison import ComparisonBrief
from schemas.watchlist import WatchlistItem
from schemas.alert import PriceAlert
from schemas.portfolio import PortfolioOptimizeRequest, PortfolioOptimizationResult
from schemas.primer import PrimerPipelineInput, ResearchPrimer
from schemas.sec_insights import SECAnswer
from schemas.document_insights import DocumentInsightAnswer
from store.sec_vector_store import SECVectorStore
from schemas.board import BoardSessionInput, BoardBriefing
from schemas.interview import InterviewPipelineInput, InterviewPrepBrief
from schemas.tracker import ApplicationStage, ApplicationOutcome
from schemas.realestate import RealEstatePipelineInput, RealEstateBrief
from store.profile_store import ProfileStore
from store.application_store import ApplicationStore
from store.skills_store import SkillsStore
from store.watchlist_store import WatchlistStore
from store.alert_store import AlertStore
from store.portfolio_store import PortfolioStore
from agents.interview.memory_judge_agent import MemoryJudgeAgent
from agents.interview.skills.base import get_skill, list_skills, register_skill
from agents.interview.skills.live_interview_coach import LiveInterviewCoachSkill
from agents.interview.skills.pre_interview_drill import PreInterviewDrillSkill
from memory.interview_memory import InterviewMemoryStore
from memory.interview_vector_store import InterviewVectorStore
from schemas.interview_memory import (
    AnswerBankEntry,
    AnswerBankEntryCreate,
    AnswerRequest,
    DocumentType,
    DocumentUploadResult,
    InterviewProfile,
    SkillApplyRequest,
)
from memory.document_ingestion import UnsupportedDocumentError
from agents.stock.stock_answer_skill import StockAnswerSkill
from agents.realestate.realestate_answer_skill import RealEstateAnswerSkill
from schemas.domain_answer import DomainAnswerRequest

logger = logging.getLogger(__name__)

CONFIG_PATH = "config.yaml"

# ── In-memory session store (board sessions are async) ────────────────────────
# Maps session_id → {"status": "running|done|failed", "result": BoardBriefing | None, "error": str | None}
_board_sessions: dict[str, dict[str, Any]] = {}

# ── Pipeline singletons (initialized at startup) ──────────────────────────────
_stock_pipeline:      Optional[StockResearchPipeline] = None
_primer_pipeline:     Optional[ResearchPrimerPipeline] = None
_board_pipeline:      Optional[ExecutiveBoardPipeline] = None
_interview_pipeline:  Optional[InterviewPipeline] = None
_realestate_pipeline: Optional[RealEstatePipeline] = None

# ── Stock-vertical helper agents (initialized at startup) ─────────────────────
_query_router:        Optional[QueryRouterAgent] = None
_comparison_analyst:  Optional[ComparisonAnalystAgent] = None
_trend_analyst:       Optional[TrendAnalystAgent] = None
_sec_qa_agent:        Optional[SECQAAgent] = None
_document_insights:   Optional[DocumentInsightsAgent] = None
_portfolio_optimizer: Optional[PortfolioOptimizerAgent] = None

# ── Persistent stores (initialized at startup) ────────────────────────────────
_profile_store:     Optional[ProfileStore] = None
_app_store:         Optional[ApplicationStore] = None
_skills_store:      Optional[SkillsStore] = None
_watchlist_store:   Optional[WatchlistStore] = None
_portfolio_store:   Optional[PortfolioStore] = None
_alert_store:       Optional[AlertStore] = None

# ── Price-alert background poller ──────────────────────────────────────────────
# Adapted from OpenStock's Inngest cron (docs/researchStockSolutions.md) —
# every 5 minutes, fetch live quotes for tickers with active alerts and flip
# any that have crossed their threshold. A plain asyncio loop rather than a
# job-scheduling framework since it's the only scheduled job in the app.
_ALERT_POLL_INTERVAL_SECONDS = 300
_alert_poll_task: Optional[asyncio.Task] = None

# ── Interview cognitive memory (Pluely live-coaching integration) ─────────────
# Separate from the pipeline/stores above — see docs/openresearch-integration-
# requirements.md §6.1. One InterviewMemoryStore per candidate_id, cached here;
# the vector store and skills are shared singletons the per-candidate stores use.
_interview_vector_store: Optional[InterviewVectorStore] = None
_interview_memory_stores: dict[str, InterviewMemoryStore] = {}
_live_interview_coach: Optional[LiveInterviewCoachSkill] = None
_pre_interview_drill: Optional[PreInterviewDrillSkill] = None

# ── Domain "answer a question" skills (Stock, Real Estate — §10) ──────────────
# Single-tenant, no candidate_id, unlike interview memory above — see
# docs/openresearch-integration-requirements.md §10 for why these stay
# separate from the cognitive-memory system rather than being generalized
# into it. (Finance has no dedicated pipeline yet — deliberately not built.)
_stock_answer_skill:      Optional[StockAnswerSkill] = None
_realestate_answer_skill: Optional[RealEstateAnswerSkill] = None


def _get_interview_memory(candidate_id: str) -> InterviewMemoryStore:
    if candidate_id not in _interview_memory_stores:
        cfg = _load_config()
        data_dir = cfg.get("interview_memory", {}).get("data_dir", "data")
        _interview_memory_stores[candidate_id] = InterviewMemoryStore(
            candidate_id, Path(data_dir) / "interview_memory", _interview_vector_store
        )
    return _interview_memory_stores[candidate_id]


def _load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize pipelines and stores on startup, clean up on shutdown."""
    global _stock_pipeline, _primer_pipeline, _board_pipeline, _interview_pipeline
    global _query_router, _comparison_analyst, _trend_analyst, _sec_qa_agent, _document_insights
    global _profile_store, _app_store, _skills_store, _watchlist_store
    global _portfolio_store, _portfolio_optimizer
    global _alert_store, _alert_poll_task
    global _interview_vector_store, _live_interview_coach, _pre_interview_drill
    global _stock_answer_skill, _realestate_answer_skill

    logger.info("Initializing pipelines...")
    try:
        _stock_pipeline = StockResearchPipeline.from_config(CONFIG_PATH)
        logger.info("Stock Research pipeline ready.")
    except Exception as e:
        logger.warning(f"Stock pipeline init failed (check config.yaml): {e}")

    try:
        _primer_pipeline = ResearchPrimerPipeline.from_config(CONFIG_PATH)
        logger.info("Research Primer pipeline ready.")
    except Exception as e:
        logger.warning(f"Primer pipeline init failed (check config.yaml): {e}")

    try:
        _stock_llm          = LLMClient.from_config(CONFIG_PATH)
        _query_router        = QueryRouterAgent(_stock_llm)
        _comparison_analyst  = ComparisonAnalystAgent(_stock_llm)
        _trend_analyst       = TrendAnalystAgent()
        logger.info("Query router, comparison analyst, and trend analyst ready.")
    except Exception as e:
        logger.warning(f"Query router / comparison / trend init failed: {e}")

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

    try:
        _watchlist_store = WatchlistStore.from_config(CONFIG_PATH)
        logger.info("Watchlist store ready.")
    except Exception as e:
        logger.warning(f"Watchlist store init failed: {e}")

    try:
        _alert_store = AlertStore.from_config(CONFIG_PATH)
        _alert_poll_task = asyncio.create_task(_alert_poll_loop())
        logger.info(f"Alert store ready — polling every {_ALERT_POLL_INTERVAL_SECONDS}s.")
    except Exception as e:
        logger.warning(f"Alert store/poller init failed: {e}")

    try:
        _portfolio_store = PortfolioStore.from_config(CONFIG_PATH)
        _portfolio_optimizer = PortfolioOptimizerAgent()
        logger.info("Portfolio store and optimizer ready.")
    except Exception as e:
        logger.warning(f"Portfolio store/optimizer init failed: {e}")

    try:
        sec_llm = LLMClient.from_config(CONFIG_PATH)
        _sec_qa_agent = SECQAAgent(
            llm=sec_llm,
            vector_store=SECVectorStore.from_config(CONFIG_PATH),
            ingest=SECIngestAgent(),
        )
        logger.info("SEC Insights (SECQAAgent) ready.")
    except Exception as e:
        logger.warning(f"SEC Insights init failed: {e}")

    try:
        _interview_vector_store = InterviewVectorStore.from_config(CONFIG_PATH)
        judge_agent = MemoryJudgeAgent(LLMClient.from_config(CONFIG_PATH))
        _live_interview_coach = LiveInterviewCoachSkill(LLMClient.from_config(CONFIG_PATH), judge_agent)
        _pre_interview_drill = PreInterviewDrillSkill()
        register_skill(_live_interview_coach)
        register_skill(_pre_interview_drill)
        logger.info("Interview cognitive memory ready (live_interview_coach, pre_interview_drill).")
    except Exception as e:
        logger.warning(f"Interview cognitive memory init failed (check config.yaml llm.provider_chain): {e}")

    try:
        if _query_router and _stock_pipeline:
            _stock_answer_skill = StockAnswerSkill(
                LLMClient.from_config(CONFIG_PATH), _query_router, _stock_pipeline, _watchlist_store
            )
            logger.info("Stock answer skill ready (POST /v1/stock/answer).")
        else:
            logger.warning("Stock answer skill not initialized — query router or stock pipeline unavailable.")
    except Exception as e:
        logger.warning(f"Stock answer skill init failed: {e}")

    try:
        if _realestate_pipeline:
            _realestate_answer_skill = RealEstateAnswerSkill(LLMClient.from_config(CONFIG_PATH), _realestate_pipeline)
            logger.info("Real estate answer skill ready (POST /v1/realestate/answer).")
        else:
            logger.warning("Real estate answer skill not initialized — real estate pipeline unavailable.")
    except Exception as e:
        logger.warning(f"Real estate answer skill init failed: {e}")

    try:
        _document_insights = DocumentInsightsAgent(
            LLMClient.from_config(CONFIG_PATH), xbrl_fallback=XBRLFallbackAgent()
        )
        from integrations import liteparse
        if liteparse.is_available():
            logger.info("Document Insights (LiteParse) ready.")
        else:
            logger.warning("Document Insights agent ready, but LiteParse CLI not found — "
                            "run `npm install` in tools/liteparse/.")
    except Exception as e:
        logger.warning(f"Document Insights init failed: {e}")

    yield
    logger.info("Server shutting down.")
    if _alert_poll_task is not None:
        _alert_poll_task.cancel()


async def _alert_poll_loop():
    """Runs for the lifetime of the app: every _ALERT_POLL_INTERVAL_SECONDS,
    check active price alerts against live quotes."""
    while True:
        try:
            await asyncio.sleep(_ALERT_POLL_INTERVAL_SECONDS)
            await _check_price_alerts()
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Alert poll loop error: {e}", exc_info=True)


async def _check_price_alerts():
    if _alert_store is None:
        return
    alerts = _alert_store.active_alerts()
    if not alerts:
        return

    tickers = list({a.ticker for a in alerts})
    quotes = await asyncio.to_thread(get_quotes, tickers)
    price_by_ticker = {q["ticker"]: q["price"] for q in quotes if q.get("price") is not None}

    for alert in alerts:
        price = price_by_ticker.get(alert.ticker)
        if price is None:
            continue
        crossed = (
            (alert.condition == "ABOVE" and price >= alert.target_price)
            or (alert.condition == "BELOW" and price <= alert.target_price)
        )
        if crossed:
            logger.info(
                f"Price alert triggered: {alert.ticker} {alert.condition} "
                f"{alert.target_price} (now {price})"
            )
            _alert_store.mark_triggered(alert.id, price)


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
    # PUT/DELETE added for the interview cognitive-memory endpoints
    # (profile replace, answer-bank update/delete) — a browser-based caller
    # (Chrome extension, or Pluely if it calls via webview fetch() rather
    # than its Rust backend) would otherwise have those blocked by the
    # CORS preflight, since only GET/POST were previously allowed.
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
)


# ── Request / Response models ─────────────────────────────────────────────────

class StockResearchRequest(BaseModel):
    ticker: str
    depth: str = "full"         # "quick" | "full"
    provider: Optional[str] = None
    export_to_tolaria: bool = False  # auto-save brief to Tolaria vault


class StockPrimerRequest(BaseModel):
    ticker: str
    depth: Literal["quick", "full"] = "full"


class SECInsightsRequest(BaseModel):
    ticker: str
    question: str
    force_refresh: bool = False   # re-ingest filings even if already cached


class StockQueryRequest(BaseModel):
    """Natural-language front door — see QueryRouterAgent."""
    query: str
    depth: Optional[str] = None  # override the router's guessed depth if provided


class StockCompareRequest(BaseModel):
    ticker_a: str
    ticker_b: str
    depth: str = "full"


class WatchlistAddRequest(BaseModel):
    ticker: str
    notes: Optional[str] = None


class AlertCreateRequest(BaseModel):
    ticker: str
    condition: Literal["ABOVE", "BELOW"]
    target_price: float


class PortfolioHoldingRequest(BaseModel):
    ticker: str
    shares: float
    cost_basis: Optional[float] = None


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


@app.post("/api/stock-primer", response_model=ResearchPrimer)
def stock_primer(request: StockPrimerRequest):
    """
    Research Primer — a richer, multi-section document (business foundation,
    driver tree, debate map, adversarial bear-case review, underwriting
    summary) built on top of the existing stock research pipeline. See
    requirements.md for the "middle ground" scoping decision.
    """
    if _primer_pipeline is None:
        raise HTTPException(503, "Primer pipeline not initialized. Check config.yaml.")
    if not request.ticker or len(request.ticker) > 15:
        raise HTTPException(400, "Invalid ticker symbol.")

    try:
        return _primer_pipeline.run(PrimerPipelineInput(ticker=request.ticker, depth=request.depth))
    except Exception as e:
        logger.error(f"Primer pipeline failed for {request.ticker}: {e}", exc_info=True)
        raise HTTPException(500, f"Primer pipeline error: {str(e)[:200]}")


@app.post("/api/stock-document-insights", response_model=DocumentInsightAnswer)
async def stock_document_insights(ticker: str = Form(...), file: UploadFile = File(...)):
    """
    Document Insights — upload a PDF (earnings-call transcript, analyst
    report, filing excerpt) for a ticker; LiteParse extracts text + bounding
    boxes locally, then an LLM summarizes it with page-level citations.
    Fills requirement #5 (earnings-call summarization) — see requirements.md.
    """
    if _document_insights is None:
        raise HTTPException(503, "Document Insights not initialized.")
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Only PDF files are supported.")

    import os
    import tempfile
    from integrations.file_type_check import verify_extension

    contents = await file.read()
    ok, detected = verify_extension(contents, ".pdf")
    if not ok:
        raise HTTPException(
            400, f"File content does not match a PDF (detected: {detected})."
        )
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(contents)
        tmp_path = tmp.name

    try:
        return _document_insights.summarize(ticker, tmp_path, document_name=file.filename)
    except Exception as e:
        logger.error(f"Document insights failed for {ticker}: {e}", exc_info=True)
        raise HTTPException(500, f"Document insights error: {str(e)[:200]}")
    finally:
        os.unlink(tmp_path)


@app.post("/api/sec-insights", response_model=SECAnswer)
def sec_insights(request: SECInsightsRequest):
    """
    SEC Insights — answer a question about a ticker's SEC filings using local
    semantic search over ingested 10-K/10-Q sections (chromadb + EdgarTools),
    with an LLM answer citing which excerpts it used. First call for a ticker
    triggers ingestion (may take a few seconds); subsequent calls reuse the
    local cache unless force_refresh=true.
    """
    if _sec_qa_agent is None:
        raise HTTPException(503, "SEC Insights not initialized. Check chromadb/edgartools install.")
    if not request.ticker or len(request.ticker) > 15:
        raise HTTPException(400, "Invalid ticker symbol.")
    if not request.question.strip():
        raise HTTPException(400, "Question cannot be empty.")

    try:
        return _sec_qa_agent.answer(request.ticker, request.question, force_refresh=request.force_refresh)
    except Exception as e:
        logger.error(f"SEC Insights failed for {request.ticker}: {e}", exc_info=True)
        raise HTTPException(500, f"SEC Insights error: {str(e)[:200]}")


def _run_comparison(ticker_a: str, ticker_b: str, depth: str) -> ComparisonBrief:
    if _stock_pipeline is None:
        raise HTTPException(503, "Stock pipeline not initialized. Check config.yaml.")
    if _comparison_analyst is None:
        raise HTTPException(503, "Comparison analyst not initialized. Check config.yaml.")

    try:
        brief_a = _stock_pipeline.run(StockPipelineInput(ticker=ticker_a, depth=depth))
        brief_b = _stock_pipeline.run(StockPipelineInput(ticker=ticker_b, depth=depth))
        return _comparison_analyst.compare(brief_a, brief_b)
    except Exception as e:
        logger.error(f"Stock comparison failed for {ticker_a} vs {ticker_b}: {e}", exc_info=True)
        raise HTTPException(500, f"Comparison pipeline error: {str(e)[:200]}")


@app.post("/api/stock-compare", response_model=ComparisonBrief)
def stock_compare(request: StockCompareRequest):
    """
    Requirement #3 — side-by-side comparison of two stocks.
    Runs the full stock research pipeline for both tickers, then an LLM
    comparison pass over the two resulting briefs (no re-fetching of data).
    """
    return _run_comparison(
        request.ticker_a.upper().strip(),
        request.ticker_b.upper().strip(),
        request.depth,
    )


@app.get("/api/stock-trend/{ticker}", response_model=TrendData)
def stock_trend(ticker: str):
    """
    Requirement #7 — five-year price + annual financial trend, plus a
    deterministically-computed previous-year summary.
    """
    if _trend_analyst is None:
        raise HTTPException(503, "Trend analyst not initialized.")
    if not ticker or len(ticker) > 15:
        raise HTTPException(400, "Invalid ticker symbol.")
    return _trend_analyst.fetch(ticker)


@app.get("/api/watchlist")
def get_watchlist():
    """Requirement #4 — list the watchlist (up to 20 tickers)."""
    if _watchlist_store is None:
        raise HTTPException(503, "Watchlist store not initialized.")
    return {"watchlist": [i.model_dump() for i in _watchlist_store.load()]}


@app.post("/api/watchlist")
def add_to_watchlist(request: WatchlistAddRequest):
    if _watchlist_store is None:
        raise HTTPException(503, "Watchlist store not initialized.")
    try:
        items = _watchlist_store.add(request.ticker, notes=request.notes)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"watchlist": [i.model_dump() for i in items]}


@app.delete("/api/watchlist/{ticker}")
def remove_from_watchlist(ticker: str):
    if _watchlist_store is None:
        raise HTTPException(503, "Watchlist store not initialized.")
    items = _watchlist_store.remove(ticker)
    return {"watchlist": [i.model_dump() for i in items]}


@app.get("/api/watchlist/quotes")
def get_watchlist_quotes():
    """Live price snapshot for every watchlist ticker — a cheap yfinance
    fast_info fetch (see agents/stock/quote_fetcher.py), not the full
    research pipeline. Adapted from OpenStock's getQuote()/getWatchlistData()
    pattern (docs/researchStockSolutions.md)."""
    if _watchlist_store is None:
        raise HTTPException(503, "Watchlist store not initialized.")
    tickers = [i.ticker for i in _watchlist_store.load()]
    return {"quotes": get_quotes(tickers)}


@app.get("/api/alerts")
def get_alerts():
    if _alert_store is None:
        raise HTTPException(503, "Alert store not initialized.")
    return {"alerts": [a.model_dump() for a in _alert_store.load()]}


@app.post("/api/alerts")
def create_alert(request: AlertCreateRequest):
    if _alert_store is None:
        raise HTTPException(503, "Alert store not initialized.")
    items = _alert_store.add(request.ticker, request.condition, request.target_price)
    return {"alerts": [a.model_dump() for a in items]}


@app.delete("/api/alerts/{alert_id}")
def delete_alert(alert_id: str):
    if _alert_store is None:
        raise HTTPException(503, "Alert store not initialized.")
    items = _alert_store.remove(alert_id)
    return {"alerts": [a.model_dump() for a in items]}


@app.get("/api/portfolio")
def get_portfolio():
    if _portfolio_store is None:
        raise HTTPException(503, "Portfolio store not initialized.")
    return {"portfolio": [i.model_dump() for i in _portfolio_store.load()]}


@app.post("/api/portfolio")
def upsert_portfolio_holding(request: PortfolioHoldingRequest):
    if _portfolio_store is None:
        raise HTTPException(503, "Portfolio store not initialized.")
    if request.shares <= 0:
        raise HTTPException(400, "Shares must be positive.")
    items = _portfolio_store.upsert(request.ticker, request.shares, request.cost_basis)
    return {"portfolio": [i.model_dump() for i in items]}


@app.delete("/api/portfolio/{ticker}")
def remove_portfolio_holding(ticker: str):
    if _portfolio_store is None:
        raise HTTPException(503, "Portfolio store not initialized.")
    items = _portfolio_store.remove(ticker)
    return {"portfolio": [i.model_dump() for i in items]}


@app.post("/api/portfolio-optimize", response_model=PortfolioOptimizationResult)
def optimize_portfolio(request: PortfolioOptimizeRequest):
    if _portfolio_store is None or _portfolio_optimizer is None:
        raise HTTPException(503, "Portfolio store/optimizer not initialized.")
    holdings = _portfolio_store.load()
    if not holdings:
        raise HTTPException(400, "Portfolio is empty — add holdings before optimizing.")
    try:
        return _portfolio_optimizer.optimize(holdings, request)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/query")
def stock_query(request: StockQueryRequest):
    """
    Natural-language front door (see QueryRouterAgent). Accepts a free-text
    question, extracts intent + ticker(s) — verified against yfinance, never
    trusting an LLM ticker guess blindly — then dispatches to the appropriate
    existing pipeline. If the router can't confidently resolve a ticker, it
    returns a clarification question instead of guessing.
    """
    if _query_router is None:
        raise HTTPException(503, "Query router not initialized. Check config.yaml.")
    if _stock_pipeline is None:
        raise HTTPException(503, "Stock pipeline not initialized. Check config.yaml.")

    # /api/query can return one of four structurally different shapes
    # (clarification / research brief / comparison brief / watchlist), and
    # the frontend used to tell them apart by duck-typing on which fields
    # happened to be present (e.g. "has a string `ticker` and `verdict`").
    # That's fragile — a future field rename/addition could produce a false
    # match. Every branch now carries an explicit `result_type` string the
    # frontend switches on instead (see desktop/src/types.ts's QueryResponse).
    result: QueryRouterResult = _query_router.route(request.query)

    if result.clarification_needed:
        return {
            "result_type": "clarification",
            "clarification_needed": True,
            "message": result.clarification_question,
        }

    depth = request.depth or result.depth

    if result.intent == "comparison" and len(result.resolved) >= 2:
        comparison = _run_comparison(result.resolved[0].ticker, result.resolved[1].ticker, depth)
        return {**comparison.model_dump(), "result_type": "comparison_brief"}

    if result.intent == "watchlist_add" and result.resolved:
        if _watchlist_store is None:
            raise HTTPException(503, "Watchlist store not initialized.")
        try:
            items = _watchlist_store.add(result.resolved[0].ticker)
        except ValueError as e:
            raise HTTPException(400, str(e))
        return {"result_type": "watchlist", "watchlist": [i.model_dump() for i in items]}

    if not result.resolved:
        return {
            "result_type": "clarification",
            "clarification_needed": True,
            "message": "I couldn't resolve a ticker to analyze — could you name the company or ticker directly?",
        }

    ticker = result.resolved[0].ticker
    try:
        brief = _stock_pipeline.run(StockPipelineInput(ticker=ticker, depth=depth))
    except Exception as e:
        logger.error(f"Query-routed stock research failed for {ticker}: {e}", exc_info=True)
        raise HTTPException(500, f"Research pipeline error: {str(e)[:200]}")
    return {**brief.model_dump(), "result_type": "research_brief"}


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


# ── Interview cognitive memory (Pluely live-coaching integration) ─────────────
# See docs/openresearch-integration-requirements.md §2/§3/§6. Separate from
# /api/interview-prep and /api/learn/* above (pre-interview JD/resume research
# and the single-user SM-2 tracker) — this is the candidate_id-scoped memory
# behind live, in-interview answer generation.

def _chunk_answer_text(text: str, chunk_size: int = 60):
    """Pseudo-streams a fully-generated answer as SSE chunks.

    NOTE: agents/api_utils.LLMClient.create() is a blocking, non-streaming
    call — there is no token-level streaming from the LLM in this codebase
    yet. This chunks the complete response after generation so the wire
    contract (§2: incremental `answer_chunk` frames, final `done: true`)
    is satisfied, but it does not yet achieve true first-token latency —
    the full answer is generated before the first chunk is sent. Wiring
    real provider-level streaming into LLMClient is a follow-up, not done here.
    """
    for i in range(0, len(text), chunk_size):
        yield text[i : i + chunk_size]


async def _run_judge_and_record(candidate_id: str, question_record_id: str) -> None:
    """Background task — runs after the answer has already been streamed back,
    per §6's latency-budget open item (judge scoring must not block the next answer)."""
    if _live_interview_coach is None or not question_record_id:
        return
    try:
        memory = _get_interview_memory(candidate_id)
        _live_interview_coach.judge_and_record(memory, question_record_id)
    except Exception as e:
        logger.error(f"judge_and_record failed for question {question_record_id!r}: {e}")


@app.post("/v1/interview/answer")
def interview_answer(request: AnswerRequest):
    """
    Real-time, retrieval-grounded answer generation for a live interview
    question (requirements doc §2). Streams SSE frames; judge scoring of the
    answer just sent runs afterward as a background task, not before this
    responds.
    """
    if _live_interview_coach is None:
        raise HTTPException(503, "Interview cognitive memory not initialized. Check config.yaml llm.provider_chain.")
    if not request.question.strip():
        raise HTTPException(400, "question must not be empty.")

    memory = _get_interview_memory(request.candidate_id)
    try:
        result = _live_interview_coach.apply(
            memory,
            question=request.question,
            session_id=request.session_id,
            conversation_history=request.conversation_history,
            answer_style=request.answer_style,
            images=request.images,
            document_ids=request.document_ids,
        )
    except Exception as e:
        logger.error(f"live_interview_coach.apply failed: {e}")
        raise HTTPException(502, f"Answer generation failed: {e}")

    def event_stream():
        for chunk in _chunk_answer_text(result.answer_text):
            yield f"data: {json.dumps({'answer_chunk': chunk, 'done': False})}\n\n"
        final = {
            "answer_chunk": "",
            "done": True,
            "metadata": {
                "matched_sources": [m.model_dump() for m in result.matched_sources],
                # true if the candidate sent an image but the configured LLM
                # couldn't use it (§2.1) — Pluely should tell the candidate
                # their screenshot was dropped rather than silently ignore it.
                "images_ignored": result.images_ignored,
                # per-document, per-page traceability for grounded claims —
                # see docs/designInterviewTool.md "Full Plan: Per-Document
                # Selection + Source Traceability".
                "citations": [c.model_dump() for c in result.citations],
            },
        }
        yield f"data: {json.dumps(final)}\n\n"

    background = BackgroundTask(_run_judge_and_record, request.candidate_id, result.question_record_id)
    return StreamingResponse(event_stream(), media_type="text/event-stream", background=background)


@app.get("/v1/interview/profile/{candidate_id}", response_model=InterviewProfile)
def get_interview_profile(candidate_id: str):
    return _get_interview_memory(candidate_id).get_profile()


@app.put("/v1/interview/profile/{candidate_id}", response_model=InterviewProfile)
def put_interview_profile(candidate_id: str, profile: InterviewProfile):
    memory = _get_interview_memory(candidate_id)
    profile.candidate_id = candidate_id
    memory.set_profile(profile)
    return memory.get_profile()


@app.get("/v1/interview/answer-bank/{candidate_id}")
def list_interview_answer_bank(candidate_id: str):
    return {"entries": _get_interview_memory(candidate_id).list_answer_bank()}


@app.post("/v1/interview/answer-bank/{candidate_id}", response_model=AnswerBankEntry)
def create_interview_answer_bank_entry(candidate_id: str, entry: AnswerBankEntryCreate):
    memory = _get_interview_memory(candidate_id)
    duplicate_id = memory.find_near_duplicate_answer_bank_entry(entry.content)
    if duplicate_id:
        raise HTTPException(409, f"Near-duplicate of existing entry '{duplicate_id}'.")
    full_entry = AnswerBankEntry(
        id=str(uuid.uuid4())[:12], candidate_id=candidate_id, **entry.model_dump()
    )
    return memory.add_answer_bank_entry(full_entry)


@app.put("/v1/interview/answer-bank/{candidate_id}/{entry_id}", response_model=AnswerBankEntry)
def update_interview_answer_bank_entry(candidate_id: str, entry_id: str, entry: AnswerBankEntryCreate):
    memory = _get_interview_memory(candidate_id)
    if not memory.get_answer_bank_entry(entry_id):
        raise HTTPException(404, f"Answer-bank entry '{entry_id}' not found.")
    full_entry = AnswerBankEntry(id=entry_id, candidate_id=candidate_id, **entry.model_dump())
    return memory.add_answer_bank_entry(full_entry)


@app.delete("/v1/interview/answer-bank/{candidate_id}/{entry_id}")
def delete_interview_answer_bank_entry(candidate_id: str, entry_id: str):
    memory = _get_interview_memory(candidate_id)
    if not memory.delete_answer_bank_entry(entry_id):
        raise HTTPException(404, f"Answer-bank entry '{entry_id}' not found.")
    return {"deleted": entry_id}


@app.get("/v1/interview/documents/{candidate_id}")
def list_interview_documents(candidate_id: str):
    """Backs the desktop document-library panel — includes each document's
    derived `stale` flag (content changed since last indexed)."""
    memory = _get_interview_memory(candidate_id)
    return {"documents": [d.model_dump() | {"stale": d.stale} for d in memory.list_documents()]}


@app.post("/v1/interview/documents/{candidate_id}", response_model=DocumentUploadResult)
async def upload_interview_document(
    candidate_id: str,
    file: UploadFile = File(...),
    doc_type: DocumentType = Form("candidate_document"),
):
    """Ingest one document into the candidate's RAG corpus (resume, project
    write-up, incident postmortem, seed question, ...) — per-page parsed and
    chunked, magika-verified against its extension before parsing. Uploading
    the same filename again re-embeds only if its content actually changed
    (see InterviewMemoryStore.add_document / DocumentRecord staleness)."""
    memory = _get_interview_memory(candidate_id)
    content = await file.read()
    try:
        return memory.add_document(file.filename, doc_type, content)
    except UnsupportedDocumentError as e:
        raise HTTPException(400, str(e))


@app.delete("/v1/interview/documents/{candidate_id}/{doc_id}")
def delete_interview_document(candidate_id: str, doc_id: str):
    memory = _get_interview_memory(candidate_id)
    if not memory.delete_document(doc_id):
        raise HTTPException(404, f"Document '{doc_id}' not found.")
    return {"deleted": doc_id}


@app.get("/v1/interview/questions/{candidate_id}")
def list_interview_questions(candidate_id: str):
    return {"questions": _get_interview_memory(candidate_id).list_questions()}


@app.delete("/v1/interview/questions/{candidate_id}/{question_id}")
def delete_interview_question(candidate_id: str, question_id: str):
    memory = _get_interview_memory(candidate_id)
    if not memory.delete_question(question_id):
        raise HTTPException(404, f"Question '{question_id}' not found.")
    return {"deleted": question_id}


@app.get("/v1/interview/skills")
def list_interview_skills():
    """Skills registered against the interview cognitive memory (e.g.
    live_interview_coach, pre_interview_drill) — apply one via
    POST /v1/interview/skills/{skill_name}/apply."""
    return {"skills": list_skills()}


@app.post("/v1/interview/skills/{skill_name}/apply")
def apply_interview_skill(skill_name: str, request: SkillApplyRequest):
    """
    Generic skill dispatcher over a candidate's memory. E.g. for
    pre_interview_drill: {"candidate_id": "...", "args": {"action": "due_today"}}
    or {"args": {"action": "record_review", "question_id": "...", "quality": 4}}.
    """
    try:
        skill = get_skill(skill_name)
    except KeyError as e:
        raise HTTPException(404, str(e))

    memory = _get_interview_memory(request.candidate_id)
    try:
        result = skill.apply(memory, **request.args)
    except (KeyError, ValueError) as e:
        raise HTTPException(400, str(e))
    return {"result": result}


# ── Domain "answer a question" endpoints (Stock, Real Estate — §10) ───────────
# No candidate_id — these stay single-tenant, unlike /v1/interview/answer.
# Domain is never inferred from the question text: it's whichever endpoint the
# client calls. See docs/openresearch-integration-requirements.md §10.
# (No /v1/finance/answer — there's no dedicated finance pipeline yet; adding
# one here would mean fabricating behavior nothing backs.)

@app.post("/v1/stock/answer")
def stock_answer(request: DomainAnswerRequest):
    if _stock_answer_skill is None:
        raise HTTPException(503, "Stock answer skill not initialized. Check config.yaml.")
    if not request.question.strip():
        raise HTTPException(400, "question must not be empty.")

    try:
        result = _stock_answer_skill.apply(
            question=request.question,
            session_id=request.session_id,
            conversation_history=request.conversation_history,
            answer_style=request.answer_style,
            images=request.images,
        )
    except Exception as e:
        logger.error(f"stock_answer_skill.apply failed: {e}")
        raise HTTPException(502, f"Answer generation failed: {e}")

    def event_stream():
        for chunk in _chunk_answer_text(result.answer_text):
            yield f"data: {json.dumps({'answer_chunk': chunk, 'done': False})}\n\n"
        final = {
            "answer_chunk": "",
            "done": True,
            "metadata": {
                "matched_sources": [m.model_dump() for m in result.matched_sources],
                "images_ignored": result.images_ignored,
            },
        }
        yield f"data: {json.dumps(final)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.post("/v1/realestate/answer")
def realestate_answer(request: DomainAnswerRequest):
    if _realestate_answer_skill is None:
        raise HTTPException(503, "Real estate answer skill not initialized. Check config.yaml.")
    if not request.question.strip():
        raise HTTPException(400, "question must not be empty.")

    try:
        result = _realestate_answer_skill.apply(
            question=request.question,
            session_id=request.session_id,
            conversation_history=request.conversation_history,
            answer_style=request.answer_style,
            images=request.images,
        )
    except Exception as e:
        logger.error(f"realestate_answer_skill.apply failed: {e}")
        raise HTTPException(502, f"Answer generation failed: {e}")

    def event_stream():
        for chunk in _chunk_answer_text(result.answer_text):
            yield f"data: {json.dumps({'answer_chunk': chunk, 'done': False})}\n\n"
        final = {
            "answer_chunk": "",
            "done": True,
            "metadata": {
                "matched_sources": [m.model_dump() for m in result.matched_sources],
                "images_ignored": result.images_ignored,
            },
        }
        yield f"data: {json.dumps(final)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


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
