"""
OpenResearch FastAPI Server

Runs at localhost:7842 (configurable in config.yaml).
The Chrome extension calls this server directly.

Endpoints:
  POST /api/stock-research      Run stock research pipeline
  POST /api/board-session       Run executive board pipeline
  POST /api/board-health        Test integration connections
  GET  /api/board-status/{id}   Poll async board session status
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
from schemas.stock import StockPipelineInput, ResearchBrief
from schemas.board import BoardSessionInput, BoardBriefing

logger = logging.getLogger(__name__)

CONFIG_PATH = "config.yaml"

# ── In-memory session store (board sessions are async) ────────────────────────
# Maps session_id → {"status": "running|done|failed", "result": BoardBriefing | None, "error": str | None}
_board_sessions: dict[str, dict[str, Any]] = {}

# ── Pipeline singletons (initialized at startup) ──────────────────────────────
_stock_pipeline: Optional[StockResearchPipeline] = None
_board_pipeline: Optional[ExecutiveBoardPipeline] = None


def _load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize pipelines on startup, clean up on shutdown."""
    global _stock_pipeline, _board_pipeline

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

    yield
    logger.info("Server shutting down.")


# ── App ───────────────────────────────────────────────────────────────────────

cfg = _load_config()
server_cfg = cfg.get("server", {})
cors_origins = server_cfg.get("cors_origins", ["chrome-extension://*", "http://localhost:*"])

app = FastAPI(
    title="OpenResearch API",
    description="AI Research & Executive Intelligence Platform",
    version="0.2.0",
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
        "status":           "ok",
        "stock_pipeline":   _stock_pipeline is not None,
        "board_pipeline":   _board_pipeline is not None,
        "timestamp":        datetime.utcnow().isoformat(),
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
        return brief
    except Exception as e:
        logger.error(f"Stock research failed for {request.ticker}: {e}", exc_info=True)
        raise HTTPException(500, f"Research pipeline error: {str(e)[:200]}")


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
