"""
OpenResearch MCP Server — Phase 7

Exposes all four research pipelines as native MCP tools so that Claude Code,
Claude Desktop, or any other MCP client can invoke them without going through
the HTTP API.

Transport: stdio (spawned as a subprocess by the MCP client)

Registered tools:
  run_stock_research      — ticker → ResearchBrief JSON
  run_board_session       — org data → BoardBriefing JSON
  run_interview_prep      — JD + profile → InterviewPrepBrief JSON
  run_real_estate_research — city + state → RealEstateBrief JSON

Usage (from Claude Code / Claude Desktop):
  Configure .mcp.json with:
    "openresearch": { "command": "python", "args": ["mcp_server.py"], "cwd": "." }

  Then call tools directly:
    run_stock_research(ticker="NVDA")
    run_interview_prep(jd_text="...", company_name="Stripe", role_title="Staff Eng")

Lazy init:
  Pipelines are built on first call to each tool (not at import time) so the
  process starts instantly even if config.yaml is absent or LLM keys are not set.
  A missing/invalid config returns a JSON error rather than crashing the server.

All tool calls are synchronous from the MCP perspective. Async pipeline methods
(board session) are bridged with asyncio.run().
"""

import asyncio
import json
import logging
import sys
from typing import Any

# MCP SDK — install via: pip install mcp
try:
    import mcp.server.stdio
    import mcp.types as types
    from mcp.server import Server
    _MCP_AVAILABLE = True
except ImportError:
    _MCP_AVAILABLE = False

logger = logging.getLogger(__name__)

CONFIG_PATH = "config.yaml"

# ── Lazy pipeline singletons ──────────────────────────────────────────────────
# Built on first call; None until then. Building at module level would slow
# startup and require all dependencies installed before any tool is called.

_stock_pipeline     = None
_board_pipeline     = None
_interview_pipeline = None
_realestate_pipeline = None
_profile_store      = None


def _get_stock():
    global _stock_pipeline
    if _stock_pipeline is None:
        from pipelines.stock_pipeline import StockResearchPipeline
        _stock_pipeline = StockResearchPipeline.from_config(CONFIG_PATH)
    return _stock_pipeline


def _get_board():
    global _board_pipeline
    if _board_pipeline is None:
        from pipelines.board_pipeline import ExecutiveBoardPipeline
        _board_pipeline = ExecutiveBoardPipeline.from_config(CONFIG_PATH)
    return _board_pipeline


def _get_interview():
    global _interview_pipeline, _profile_store
    if _interview_pipeline is None:
        from pipelines.interview_pipeline import InterviewPipeline
        from store.profile_store import ProfileStore
        _interview_pipeline = InterviewPipeline.from_config(CONFIG_PATH)
        _profile_store      = ProfileStore.from_config(CONFIG_PATH)
    return _interview_pipeline


def _get_realestate():
    global _realestate_pipeline
    if _realestate_pipeline is None:
        from pipelines.realestate_pipeline import RealEstatePipeline
        _realestate_pipeline = RealEstatePipeline.from_config(CONFIG_PATH)
    return _realestate_pipeline


# ── Tool implementations ──────────────────────────────────────────────────────

def _run_stock(ticker: str, depth: str = "full") -> dict:
    from schemas.stock import StockPipelineInput
    pipeline = _get_stock()
    brief = pipeline.run(StockPipelineInput(ticker=ticker, depth=depth))
    return brief.model_dump()


def _run_board(
    mode: str = "weekly_review",
    context: str | None = None,
    raw_paste: str | None = None,
) -> dict:
    from schemas.board import BoardSessionInput
    pipeline = _get_board()
    session_input = BoardSessionInput(
        mode=mode,
        context=context,
        data_sources=[],
        raw_paste=raw_paste,
    )
    # Board pipeline is async — bridge with asyncio.run()
    briefing = asyncio.run(pipeline.run(session_input))
    return briefing.model_dump()


def _run_interview(
    jd_text: str,
    company_name: str,
    role_title: str,
    profile_text: str | None = None,
    depth: str = "full",
) -> dict:
    from schemas.interview import InterviewPipelineInput
    pipeline = _get_interview()

    # If no inline profile text, load from stored master profile
    if not profile_text and _profile_store and _profile_store.exists():
        stored = _profile_store.load()
        profile_text = stored.to_text() if stored else None

    if not profile_text:
        return {"error": "No profile_text provided and no stored master profile found. "
                         "Call POST /api/profile/add-resume first, or supply profile_text."}

    brief = pipeline.run(InterviewPipelineInput(
        jd_text=jd_text,
        profile_text=profile_text,
        company_name=company_name,
        role_title=role_title,
        depth=depth,
    ))
    return brief.model_dump()


def _run_realestate(
    city: str,
    state: str,
    address: str = "",
    zip_code: str | None = None,
    depth: str = "full",
    bedrooms: int | None = None,
    bathrooms: float | None = None,
    sqft: int | None = None,
    purchase_price: float | None = None,
) -> dict:
    from schemas.realestate import RealEstatePipelineInput
    pipeline = _get_realestate()
    brief = pipeline.run(RealEstatePipelineInput(
        city=city,
        state=state,
        address=address,
        zip_code=zip_code,
        depth=depth,
        bedrooms=bedrooms,
        bathrooms=bathrooms,
        sqft=sqft,
        purchase_price=purchase_price,
    ))
    return brief.model_dump()


# ── MCP server definition ─────────────────────────────────────────────────────

def _build_server() -> "Server":
    server = Server("openresearch")

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        return [
            types.Tool(
                name="run_stock_research",
                description=(
                    "Run the full stock research pipeline for a ticker symbol. "
                    "Returns a ResearchBrief with verdict, price target, bull/bear cases, "
                    "key risks, upcoming catalysts, fundamentals, sentiment, and — when "
                    "Equibles is running — institutional ownership, short interest, insider "
                    "trades, and technical indicators."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "ticker": {
                            "type": "string",
                            "description": "Stock ticker symbol, e.g. 'AAPL', 'NVDA', 'TSLA'",
                        },
                        "depth": {
                            "type": "string",
                            "enum": ["quick", "full"],
                            "default": "full",
                            "description": (
                                "'full' runs all data sources including Alpha Vantage, "
                                "Polygon, SEC EDGAR, and Equibles. "
                                "'quick' uses yfinance + NewsAPI only (faster)."
                            ),
                        },
                    },
                    "required": ["ticker"],
                },
            ),
            types.Tool(
                name="run_board_session",
                description=(
                    "Run an executive board simulation with 6 AI board members "
                    "(Chief of Staff, VP Engineering, VP Product, VP People, CTO, CFO Proxy). "
                    "Provide org data as raw text and get a structured BoardBriefing with "
                    "executive summary, health score, red flags, conflicts, action items, "
                    "and individual board member views."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "mode": {
                            "type": "string",
                            "enum": ["weekly_review", "decision_advisory", "health_scan"],
                            "default": "weekly_review",
                            "description": (
                                "'weekly_review' = full org digest; "
                                "'decision_advisory' = board debate on a proposal in context; "
                                "'health_scan' = fast conflict + risk detection pass."
                            ),
                        },
                        "context": {
                            "type": "string",
                            "description": (
                                "For decision_advisory: the proposal or question to debate. "
                                "For other modes: optional additional context for the board."
                            ),
                        },
                        "raw_paste": {
                            "type": "string",
                            "description": (
                                "Paste of org data as plain text: sprint notes, Slack exports, "
                                "project status docs, hiring updates, etc. "
                                "The OrgNormalizerAgent will structure this automatically."
                            ),
                        },
                    },
                    "required": [],
                },
            ),
            types.Tool(
                name="run_interview_prep",
                description=(
                    "Run the full interview preparation pipeline for a specific job. "
                    "Returns a brief with fit analysis (0–10 score + gaps + deal-breakers), "
                    "company interview culture, 15 tailored questions, STAR answers from "
                    "your profile, top 3 prep priorities, and a tailored resume (depth=full)."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "jd_text": {
                            "type": "string",
                            "description": "Full job description text (paste the complete JD).",
                        },
                        "company_name": {
                            "type": "string",
                            "description": "Company name, e.g. 'Stripe', 'Google', 'Acme Corp'.",
                        },
                        "role_title": {
                            "type": "string",
                            "description": "Job title, e.g. 'Staff Software Engineer', 'Senior PM'.",
                        },
                        "profile_text": {
                            "type": "string",
                            "description": (
                                "Candidate's profile / resume as plain text. "
                                "Optional — if omitted, the stored master profile is used "
                                "(POST /api/profile/add-resume to build one)."
                            ),
                        },
                        "depth": {
                            "type": "string",
                            "enum": ["quick", "full"],
                            "default": "full",
                            "description": (
                                "'full' runs all 5 nodes including live company research "
                                "(when brave_search_key is set) and the resume writer. "
                                "'quick' skips company research and resume writing."
                            ),
                        },
                    },
                    "required": ["jd_text", "company_name", "role_title"],
                },
            ),
            types.Tool(
                name="run_real_estate_research",
                description=(
                    "Run the full real estate demand + investment analysis pipeline for a city. "
                    "Covers migration trends (IRS SOI, U-Haul, Census), labor market (BLS), "
                    "housing market (Zillow, Redfin, Census permits), cost of living (BEA RPP, "
                    "tax rates), demand factors (crime, air quality, walkability), and climate "
                    "risk (FEMA flood zones, wildfire). Optionally runs full rental feasibility "
                    "analysis (cap rate, cash-on-cash return, DSCR) when property details are "
                    "provided."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "city": {
                            "type": "string",
                            "description": "City name, e.g. 'Austin', 'Nashville', 'Phoenix'.",
                        },
                        "state": {
                            "type": "string",
                            "description": "2-letter state abbreviation, e.g. 'TX', 'TN', 'AZ'.",
                        },
                        "address": {
                            "type": "string",
                            "description": (
                                "Full property address — enables property-level FEMA flood "
                                "zone lookup. Optional."
                            ),
                        },
                        "zip_code": {
                            "type": "string",
                            "description": "ZIP code — improves Census tract resolution. Optional.",
                        },
                        "depth": {
                            "type": "string",
                            "enum": ["quick", "full"],
                            "default": "full",
                            "description": (
                                "'full' downloads live Zillow/Redfin CSVs if cache is stale "
                                "and calls all APIs. "
                                "'quick' uses static / cached data only."
                            ),
                        },
                        "bedrooms": {
                            "type": "integer",
                            "description": "Number of bedrooms — triggers rental feasibility analysis.",
                        },
                        "bathrooms": {
                            "type": "number",
                            "description": "Number of bathrooms, e.g. 2 or 2.5.",
                        },
                        "sqft": {
                            "type": "integer",
                            "description": "Interior living area in square feet.",
                        },
                        "purchase_price": {
                            "type": "number",
                            "description": "Asking or offer price in USD — used for cap rate + CoC return.",
                        },
                    },
                    "required": ["city", "state"],
                },
            ),
        ]

    @server.call_tool()
    async def call_tool(
        name: str, arguments: dict
    ) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
        try:
            if name == "run_stock_research":
                result = _run_stock(
                    ticker=arguments["ticker"],
                    depth=arguments.get("depth", "full"),
                )

            elif name == "run_board_session":
                result = _run_board(
                    mode=arguments.get("mode", "weekly_review"),
                    context=arguments.get("context"),
                    raw_paste=arguments.get("raw_paste"),
                )

            elif name == "run_interview_prep":
                result = _run_interview(
                    jd_text=arguments["jd_text"],
                    company_name=arguments["company_name"],
                    role_title=arguments["role_title"],
                    profile_text=arguments.get("profile_text"),
                    depth=arguments.get("depth", "full"),
                )

            elif name == "run_real_estate_research":
                result = _run_realestate(
                    city=arguments["city"],
                    state=arguments["state"],
                    address=arguments.get("address", ""),
                    zip_code=arguments.get("zip_code"),
                    depth=arguments.get("depth", "full"),
                    bedrooms=arguments.get("bedrooms"),
                    bathrooms=arguments.get("bathrooms"),
                    sqft=arguments.get("sqft"),
                    purchase_price=arguments.get("purchase_price"),
                )

            else:
                result = {"error": f"Unknown tool: {name}"}

        except Exception as e:
            logger.exception(f"Tool '{name}' failed")
            result = {"error": str(e), "tool": name}

        return [types.TextContent(type="text", text=json.dumps(result, default=str))]

    return server


# ── Entry point ───────────────────────────────────────────────────────────────

async def _main():
    if not _MCP_AVAILABLE:
        print(
            "ERROR: 'mcp' package not installed.\n"
            "Install it with: pip install mcp\n"
            "Or: pip install -e '.[mcp]' from the openresearch repo root.",
            file=sys.stderr,
        )
        sys.exit(1)

    logging.basicConfig(
        level=logging.WARNING,     # keep stdout clean for MCP stdio transport
        format="%(levelname)s %(name)s %(message)s",
        stream=sys.stderr,         # MCP reads stdout — all logs must go to stderr
    )

    server = _build_server()

    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


if __name__ == "__main__":
    asyncio.run(_main())
