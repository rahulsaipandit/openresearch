# Design Document: AI Research & Executive Intelligence Platform

**Date:** 2026-05-17
**Status:** Implemented (Phases 1–4 complete + Phase 4 extensions)
**Scope:** Stock Research Tool + Executive Board System

---

## 1. Chosen Foundation: OpenResearch

**Repo:** `https://github.com/charanvadhyar/openresearch`

### Why OpenResearch over the alternatives

| Criterion                   | OpenResearch                          | moedesux/autoresearch-opencode | rootcause + autofix  |
|-----------------------------|---------------------------------------|--------------------------------|----------------------|
| Report/synthesis pipeline   | Built-in (Paper Writer agent)         | None                           | None                 |
| Maturity                    | Full Python stack, well-structured    | New (May 2026), empty dirs     | Stable but narrow    |
| Adaptability to new domains | High — swap agents per domain         | Low — code-optimization only   | Low — debug/fix only |
| Multi-agent orchestration   | LangGraph (production-grade)          | Single-loop skill              | Two-skill pipeline   |
| Claude API support          | Native (Anthropic SDK)                | Via OpenCode                   | Claude Code CLI only |
| Local LLM support           | OpenAI-compat endpoint in config.yaml | Via OpenCode                   | None                 |
| State & memory              | Redis + ChromaDB                      | JSONL files                    | None                 |

**Decision:** OpenResearch's LangGraph pipeline, multi-provider LLM abstraction, and synthesizer-agent pattern map directly onto both the Stock Research Tool and Executive Board. The other projects are either too narrow in scope or too immature.

### What was kept vs replaced

| OpenResearch Component                      | Action                                  | Outcome                                                                                         |
|---------------------------------------------|-----------------------------------------|-------------------------------------------------------------------------------------------------|
| LangGraph orchestration layer               | **Kept**                                | Used as pattern basis; pipelines are plain async Python following the same state-flow model     |
| LLM provider abstraction (`api_utils.py`)   | **Extended**                            | Added `openai_compatible` provider for local LLMs; added `LLMClient.from_config()`              |
| Pydantic schemas                            | **Kept + Extended**                     | Two new schema files: `schemas/stock.py`, `schemas/board.py`                                    |
| Redis + ChromaDB                            | **Kept in deps**                        | Available; session state currently uses in-memory dict in `server.py`                           |
| Report generation (Jinja2 → Markdown)       | **Not yet ported**                      | Scheduled for Phase 4                                                                           |
| Kaggle kernel executor                      | **Removed**                             | `agents/executor_agent.py`, `tools/kaggle_client.py` left in place but not imported by new code |
| ML-specific agents (EDA, Method Formulator) | **Left in place**                       | Not imported by new pipelines; can be deleted once legacy path is confirmed unused              |
| Paper Writer agent                          | **Pattern reused → `cos_synthesis.py`** | Same multi-section synthesis pattern, new output schema                                         |

---

## 2. System Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                    Chrome Extension (existing)               │
│  StockResearch.tsx     ExecutiveBoard.tsx                    │
│  (new component)       (new component)                       │
└──────────────────┬───────────────────┬───────────────────────┘
                   │  HTTP (localhost)  │
┌──────────────────▼───────────────────▼───────────────────────┐
│              Local FastAPI Server  server.py                 │
│   POST /api/stock-research     POST /api/board-session       │
│   POST /api/board-health       GET  /api/board-status/:id    │
│   GET  /api/health                                           │
└──────────────────┬───────────────────┬───────────────────────┘
                   │                   │
     ┌─────────────▼─────┐   ┌─────────▼───────────────────┐
     │  StockResearch    │   │  ExecutiveBoard Pipeline    │
     │  Pipeline         │   │                             │
     │  (5 nodes)        │   │  (4 stages, parallel fan)   │
     └─────────────┬─────┘   └─────────────────────────────┘
                   │
     ┌─────────────▼───────────────────────────────────────┐
     │  LLM Provider (config.yaml → LLMClient.from_config) │
     │  Anthropic Claude  |  OpenAI  |  openai_compatible  │
     │  (LM Studio / Ollama / any OpenAI-compat endpoint)  │
     └─────────────────────────────────────────────────────┘
```

### Local API Server

`server.py` — FastAPI at `localhost:7842`. Initialized at startup via `lifespan()` which builds both pipeline singletons from `config.yaml`.

```
GET  /api/health                      # liveness + pipeline status
POST /api/stock-research              # { ticker, depth, provider } → ResearchBrief (sync)
POST /api/board-session               # { mode, context, data_sources, raw_paste } → { session_id }
GET  /api/board-status/:id            # { status, result, error, created_at, completed_at }
POST /api/board-health                # { check_jira, check_linear, check_notion, check_slack }
```

Board sessions run as FastAPI `BackgroundTask`. The caller gets a `session_id` immediately and polls `/api/board-status/:id` until `status == "done"`.

---

## 3. Feature 1: Stock Research Tool

### Goal

Given a stock ticker, produce a structured research brief covering fundamentals, news sentiment, and a synthesized analyst-style view with bull/bear framing.

### Pipeline (implemented in `pipelines/stock_pipeline.py`)

```
StockPipelineInput(ticker, depth)
    ↓
[Node 1] DataFetcherAgent             agents/stock/data_fetcher.py
    - yfinance: price, P/E, EPS, margins, 52w range, beta, analyst target
    - Alpha Vantage (if key): income statement, balance sheet
    - Polygon.io (if key): earnings calendar
    ↓
[Node 2] NewsAggregatorAgent          agents/stock/news_aggregator.py
    - NewsAPI (if key): last 30 days headlines
    - SEC EDGAR (free): recent 8-K, 10-Q, 10-K filings via CIK lookup
    ↓
[Node 3] FundamentalsAnalystAgent     agents/stock/fundamentals_analyst.py
    persona: "You are a buy-side fundamental analyst..."
    output: ValuationSummary
    ↓
[Node 4] SentimentAnalystAgent        agents/stock/sentiment_analyst.py
    persona: "You are a news-driven equity researcher..."
    output: SentimentSummary
    ↓
[Node 5] ResearchSynthesizerAgent     agents/stock/research_synthesizer.py
    persona: "You are a senior equity strategist writing a one-page brief..."
    output: ResearchBrief
    ↓
ResearchBrief → FastAPI response
```

`depth="quick"` skips Alpha Vantage, Polygon.io, and SEC EDGAR. Useful for fast tests or when only API keys for NewsAPI and Yahoo Finance are configured.

Each LLM agent returns structured JSON parsed directly into the Pydantic schema. On parse failure, a deterministic fallback is returned rather than raising — the pipeline always completes.

### Output Schema (`schemas/stock.py`)

```python
class ValuationSummary(BaseModel):
    fair_value_low: float
    fair_value_high: float
    current_price: float | None
    pe_ratio: float | None
    forward_pe: float | None
    eps: float | None
    revenue_growth_yoy: float | None
    profit_margin: float | None
    debt_to_equity: float | None
    market_cap: float | None
    moat_assessment: str
    key_metrics: dict[str, str]

class SentimentSummary(BaseModel):
    tone: Literal["bullish", "neutral", "bearish"]
    catalysts: list[str]
    risks: list[str]
    analyst_consensus: str | None
    recent_headlines: list[str]
    sec_filings_summary: str | None

class ResearchBrief(BaseModel):
    ticker: str
    company_name: str
    as_of_date: str
    verdict: Literal["Strong Buy", "Buy", "Hold", "Sell", "Strong Sell"]
    price_target_low: float
    price_target_high: float
    current_price: float | None
    summary: str
    bull_case: list[str]
    bear_case: list[str]
    key_risks: list[str]
    upcoming_catalysts: list[str]
    fundamentals: ValuationSummary
    sentiment: SentimentSummary
    sources: list[str]
```

### Data Sources & Keys

| Source                   | Auth    | Free Tier   | Implemented                |
|--------------------------|---------|-------------|----------------------------|
| Yahoo Finance (yfinance) | None    | Unlimited   | Yes                        |
| Alpha Vantage            | API key | 25 req/day  | Yes                        |
| Polygon.io               | API key | 5 req/min   | Yes (earnings + news)      |
| NewsAPI                  | API key | 100 req/day | Yes                        |
| SEC EDGAR                | None    | Unlimited   | Yes (CIK lookup + filings) |

Keys stored in `config.yaml` under `stock_research.data_sources`.

---

## 4. Feature 2: Executive Board

### Goal

A simulated boardroom of AI agents — each with a distinct executive lens — that collectively analyzes org health across 10 VPs / 200 people, debates decisions, produces weekly briefings, and surfaces cross-team conflicts.

### Board Members

| Agent ID         | Role           | Class                | Analytical Lens                                                                            |
|------------------|----------------|----------------------|--------------------------------------------------------------------------------------------|
| `chief_of_staff` | Chief of Staff | `ChiefOfStaffAgent`  | Org health, CEO-level narrative, cross-cutting blockers; Precision Questioning methodology |
| `vp_engineering` | VP Engineering | `VPEngineeringAgent` | Sprint velocity, technical debt, delivery risk, capacity                                   |
| `vp_product`     | VP Product     | `VPProductAgent`     | Roadmap alignment, OKR progress, feature prioritization                                    |
| `vp_people`      | VP People / HR | `VPPeopleAgent`      | Team morale signals, hiring gaps, attrition risk                                           |
| `cto`            | CTO            | `CTOAgent`           | Technical strategy, platform risks, architecture decisions                                 |
| `cfo_proxy`      | Finance Proxy  | `CFOProxyAgent`      | Budget burn rate, project ROI, resource allocation                                         |

All six inherit from `agents/board/_base.py` (`BoardMemberBase`). Subclasses only define `AGENT_ID`, `ROLE`, and `SYSTEM_PROMPT`. The shared base handles prompt construction from `OrgSnapshot` and JSON parsing into `BoardMemberView`.

### Chief of Staff — Precision Questioning Methodology

`ChiefOfStaffAgent` (`agents/board/chief_of_staff.py`) is the most analytically rigorous board member. It overrides both the system prompt and the prompt builder to apply two complementary frameworks sourced from Amazon's internal "Consumer's Guide to Communicating with Precision" document.

#### Precision Questioning Framework

Every question the CoS surfaces must satisfy these principles:

| Principle                        | Rule                                                                                                           |
|----------------------------------|----------------------------------------------------------------------------------------------------------------|
| **Start with Why**               | Each question states what decision or action it unblocks — not just what is being asked                        |
| **Communicate with Concision**   | Fewest words that leave no ambiguity; every word is intentional                                                |
| **Support with Data**            | If a finding has no number, the question must ask for one — never accept vague signals                         |
| **Who/What/When with Specifics** | "Who" = a person's name; "When" = a calendar date; "How many" = a number                                       |
| **Anticipate the Next Question** | Close follow-up loops in the same question (root cause + recovery date; owner + committed date)                |
| **Assume Zero Context**          | Phrase questions so a cold reader can understand the situation, the gap, and what a complete answer looks like |
| **Avoid Hyperbole**              | Replace vague intensifiers ("significant", "substantial", "ongoing") with literal counts and dates             |

Nine explicit **never-do pitfalls** are embedded in the system prompt:
asking about the topic without defining what a complete answer looks like; accepting "we're working on it" without a date; faking certainty when data is missing; answering the expected question instead of the needed one; failing to think through downstream scenarios; making statements without numbers; over/under sharing context; using jargon or vague adjectives; substituting adjectives and adverbs for real data.

The CoS's `questions_for_ceo` output is guaranteed: each question names the missing data point, owner, or date; anticipates the follow-up; and is ≤ 3 sentences so the CEO can act in a 15-minute brief.

#### Pareto / 80-20 Principle

The CoS applies the 80/20 rule to combat decision fatigue and focus CEO attention:

| Application                | How                                                                                                                                                              |
|----------------------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| **Prioritizing findings**  | Identifies the ~20% of issues driving ~80% of org risk, delay, or morale impact. Items in this bucket are prefixed `[80/20]` in `key_findings`.                  |
| **Prioritizing questions** | Surfaces only 2–3 questions whose answers would unlock the most downstream clarity. A question that unblocks 5 others is worth more than 5 individual questions. |
| **Risk triage**            | Identifies the 1–2 risks that, if unaddressed, would cascade into the others — recommends CEO attention there first.                                             |
| **Resource allocation**    | Identifies the 20% of work items blocking 80% of progress; asks whether deferring low-leverage items would free disproportionate capacity.                       |
| **Conflict resolution**    | Identifies the root conflict that, if resolved, would dissolve the others.                                                                                       |

**Guard-rails on Pareto application:**
- Do not use 80/20 to dismiss a low-severity issue that is 3 days from becoming critical.
- Do not aggregate to the point of losing actionability — the CEO needs specific owners and dates, not a "cluster of issues".
- Recommendations explicitly call out: *"Resolving X would unblock Y and Z simultaneously."*

#### Implementation Details

`ChiefOfStaffAgent` overrides `analyze()` with a higher token budget (`max_tokens=2500` vs. `1500` for other board members) and calls a custom `_build_cos_prompt()` method that:
- Shows `NOT PROVIDED` for every missing metric (not silence)
- Lists all at-risk projects with owner, due date, and blockers
- Lists all open risks with mitigation status (or explicit "no mitigation recorded")
- Issues 7 explicit instructions to the LLM including Pareto marking rules

### Pipeline (implemented in `pipelines/board_pipeline.py`)

```
BoardSessionInput(mode, context, data_sources, raw_paste)
    ↓
[Stage 1] OrgNormalizerAgent          agents/board/org_normalizer.py
    - Accepts: Jira dict, Linear dict, Notion dict, Slack dict,
               document text, manual paste
    - Structured API data mapped directly (no LLM)
    - Unstructured text normalized via LLM with schema prompt
    - Output: OrgSnapshot
    ↓
[Stage 2] Board Member Agents (parallel fan-out)
    asyncio.gather() over thread pool — each agent receives OrgSnapshot + session_mode
    Output: list[BoardMemberView]
    ↓
[Stage 3] ConflictDetectorAgent       agents/board/conflict_detector.py
    - Reads all BoardMemberView outputs
    - Finds disagreements, resource contention, timeline clashes
    - Output: ConflictReport
    ↓
[Stage 4] CoSSynthesisAgent           agents/board/cos_synthesis.py
    - Reads BoardMemberView list + ConflictReport
    - Produces the final BoardBriefing
    ↓
BoardBriefing → stored in session dict → polled via /api/board-status/:id
```

`parallel_execution: true` in config uses `asyncio.gather` + thread pool executor for the board member fan-out. Set to `false` for sequential execution (useful for debugging or low-memory environments).

### Session Modes

**`weekly_review`** — digest all project/team data, produce briefing + action items
**`decision_advisory`** — user poses a proposal in `context`; each board member responds from their lens; CoS synthesizes the debate into a recommendation
**`health_scan`** — focused conflict + risk detection pass; faster (skips full briefing detail)

### Core Schemas (`schemas/board.py`)

```python
class OrgSnapshot(BaseModel):
    snapshot_date: str
    teams: list[TeamStatus]
    org_metrics: OrgMetrics
    active_initiatives: list[Initiative]
    open_risks: list[Risk]
    decisions_pending: list[Decision]
    raw_input: str | None

class TeamStatus(BaseModel):
    vp_name: str
    team_name: str
    headcount: int
    active_projects: list[Project]
    blockers: list[str]
    morale_signal: Literal["green", "yellow", "red"] | None
    budget_status: Literal["on_track", "at_risk", "over"] | None
    notes: str | None

class BoardMemberView(BaseModel):
    agent_id: str
    role: str
    key_findings: list[str]
    risks: list[Risk]
    recommendations: list[str]
    questions_for_ceo: list[str]
    confidence: float

class ConflictReport(BaseModel):
    conflicts: list[Conflict]
    resource_contentions: list[str]
    timeline_clashes: list[str]
    summary: str

class BoardBriefing(BaseModel):
    session_date: str
    mode: Literal["weekly_review", "decision_advisory", "health_scan"]
    executive_summary: str
    org_health_score: float          # 0-10
    red_flags: list[str]
    cross_team_conflicts: list[Conflict]
    top_priorities: list[str]
    action_items: list[ActionItem]   # owner, due_date, priority, description
    board_member_views: list[BoardMemberView]
    decisions_recommended: list[Decision]
```

### Data Integrations

#### Jira (`integrations/jira.py`)

```python
# Fetch open issues grouped by project key
jira.fetch_issues_by_project(["ENG", "PRODUCT", "INFRA"])
# Fetch grouped by label (for team-based grouping)
jira.fetch_issues_by_label(["team-engineering", "team-product"])
# Fetch sprint data from an agile board
jira.fetch_board_sprints(board_id=123)
```

Authentication: Basic auth (email + API token). Read-only — only GET requests.
Configured under `executive_board.integrations.jira` + `jira_project_keys` list.

#### Linear (`integrations/linear.py`)

```python
# List all teams
linear.list_teams()
# Fetch open issues + cycle (sprint) data by team key
linear.fetch_issues_by_team(["engineering", "product", "platform"])
```

Uses GraphQL. Returns issues and active cycle velocity metrics.
Configured under `executive_board.integrations.linear` + `linear_team_keys` list.

#### Notion (`integrations/notion.py`)

```python
# Query a specific database (paginates automatically)
notion.query_database(database_id, filter_body=None, max_pages=50)
# Query all databases configured in config.yaml
notion.query_all_configured_databases()
# Property extractors
notion.get_page_title(page)
notion.get_property_text(page, "Status")
```

Read-only. Supports: title, rich_text, select, multi_select, date, checkbox, number, url, email, people property types.
Configured under `executive_board.integrations.notion.database_ids`.

#### Slack (`integrations/slack.py`)

```python
# Fetch recent messages from a channel
slack.fetch_recent_messages(channel_id, days_back=7, max_messages=100)
# Fetch all configured channels
slack.fetch_all_configured_channels(days_back=7)
# Verify token
slack.test_connection()
```

**Read-only guardrail:** A `_ALLOWED_METHODS` frozenset (`conversations.history`, `conversations.list`, `conversations.info`, `users.info`, `auth.test`) is checked before every API call. Any method not in this set raises `PermissionError` before the HTTP request is made — it is impossible to accidentally write, post, or modify through this client.

Bot token scopes required: `channels:history`, `channels:read`. Bot must be invited to each channel explicitly.
Configured under `executive_board.integrations.slack`.

#### Documents (`integrations/documents.py`)

```python
# Load all supported files in a folder
loader = DocumentLoader(folder_path="/path/to/docs")
text = loader.load_all()           # returns concatenated plain text
# Load a single file
text = loader.load_file("/path/to/file.docx")
```

Supported formats: `.docx` (requires `python-docx`), `.pdf` (requires `PyMuPDF` or `pypdf`), `.txt`, `.md`.

**Three-stage PDF extraction strategy:**
1. **PyMuPDF text extraction** — fast, handles complex layouts; preferred when available.
2. **pypdf fallback** — used if PyMuPDF is not installed.
3. **Scanned PDF OCR** — if the extracted text is sparse (average < 50 chars/page), the page is treated as image-based and routed through `ScannedPDFOCR` if an OCR engine is configured (see [Scanned PDF OCR](#scanned-pdf-ocr) below).

**Read-only guardrails:**
- Only extensions in `ALLOWED_EXTS = {".docx", ".pdf", ".txt", ".md"}` are accepted. Attempting to load other types raises `ValueError`.
- Files over `max_file_mb` (default 10 MB) are silently skipped with a log message.
- Total text is capped at `MAX_TOTAL_CHARS = 50,000` characters regardless of file count.
- Images are rendered in memory during OCR — nothing is written to disk.

Configured under `executive_board.integrations.documents`.

#### Scanned PDF OCR (`integrations/ocr.py`)

`ScannedPDFOCR` handles PDFs where pages contain images of text rather than embedded text (e.g., scanned physical documents).

**How it works:**
1. PyMuPDF renders each sparse page to a PNG image in memory (default: 200 DPI).
2. The PNG is base64-encoded and sent to Claude Haiku via the vision API.
3. Claude extracts all text preserving headings, bullets, numbered lists, and table structure.
4. The extracted text is returned as plain string; the source PDF is never modified.

**Why Claude vision instead of Tesseract:**
- No system binary install required — works on Windows, Mac, and Linux without PATH changes.
- Handles mixed layouts (tables, two-column, handwriting) more accurately than Tesseract for typical business documents.
- Uses `claude-haiku-4-5-20251001` (fast + cheap) — not the primary reasoning model.

```python
ocr = ScannedPDFOCR.from_config("config.yaml")
text = ocr.extract(Path("scan.pdf"))   # per-page: standard extraction first, OCR if sparse
is_scanned = ScannedPDFOCR.is_scanned(pdf_path)   # static, no API call
```

**API key reuse:** `ScannedPDFOCR.from_config()` reuses the Anthropic key already configured in `llm.provider_chain` — no additional key is required for users already using Claude. An explicit override key can be set at `ocr.api_key`.

**Config:**
```yaml
ocr:
  enabled: true
  model: claude-haiku-4-5-20251001    # vision model for OCR
  dpi: 200                             # page render resolution
  api_key: ""                          # leave blank to reuse llm.provider_chain anthropic key
```

**Sparse detection threshold:** A page is treated as scanned if it yields < `MIN_CHARS_PER_PAGE = 50` characters from standard extraction. For whole-file detection in `DocumentLoader`, an estimated page count (based on file size) is used to compute an average.

**Guardrails:**
- Read-only: never writes, modifies, or deletes files.
- In-memory only: page images exist only during the API call; nothing is persisted to disk.
- Graceful fallback: if PyMuPDF is not installed, returns `is_scanned = False`. If no API key is configured, logs a warning and returns the sparse text as-is.

All five integrations are optional. If none are configured, the ingestion step accepts a `raw_paste` string as fallback.

---

## 5. LLM Configuration

Both pipelines share a single `config.yaml` and a single `LLMClient` instance built via `LLMClient.from_config()`.

### config.yaml format (implemented)

```yaml
llm:
  provider_chain:
    - provider: anthropic
      model: claude-sonnet-4-6
      api_key: ""

    # Optional local LLM fallback:
    - provider: openai_compatible
      base_url: http://localhost:1234/v1
      model: qwen3-27b
      api_key: lm-studio

ocr:
  enabled: true
  model: claude-haiku-4-5-20251001    # vision model for scanned PDF OCR
  dpi: 200                             # page render resolution (higher = more accurate, slower)
  api_key: ""                          # leave blank to reuse llm.provider_chain anthropic key
```

### Supported provider values

| `provider`          | Backend                      | Notes                                                |
|---------------------|------------------------------|------------------------------------------------------|
| `anthropic`         | Anthropic Claude API         | Requires `api_key`                                   |
| `openai`            | OpenAI API                   | Requires `api_key`                                   |
| `minimax`           | MiniMax API                  | Requires `api_key`; uses `https://api.minimax.io/v1` |
| `openai_compatible` | Any OpenAI-compatible server | Requires `base_url`; `api_key` is a placeholder      |

`openai_compatible` supports LM Studio (default port 1234), Ollama (port 11434), vLLM, llama.cpp server, and any other server implementing the OpenAI `/v1/chat/completions` endpoint.

Providers are tried left-to-right. On rate limit, the client waits with exponential back-off up to `MAX_RETRIES=4` times, then falls back to the next provider in the chain.

### LLMClient internals (`agents/api_utils.py`)

```python
# Build from new config format
llm = LLMClient.from_config("config.yaml")

# Build manually (backwards-compatible)
llm = LLMClient([
    ("anthropic", "sk-ant-...", "claude-sonnet-4-6"),
    ("openai_compatible", "local", "qwen3-27b"),   # base_url via _Backend kwarg
])

# Single provider
llm = LLMClient.single("anthropic", api_key, model)

# Call
text = llm.create(system="...", messages=[...], max_tokens=1500)
```

`_Backend` (private) wraps one provider+model pair. `LLMClient` holds an ordered list of `_Backend` instances and tries them in sequence on rate-limit exhaustion.

---

## 6. File Structure (as implemented)

```
openresearch/
├── server.py                        FastAPI server at localhost:7842
├── config.yaml                      All configuration (LLM, data sources, integrations)
├── pyproject.toml                   Dependencies (fastapi, uvicorn, yfinance, httpx, ...)
│
├── agents/
│   ├── api_utils.py                 LLMClient + _Backend + PromptBudget
│   ├── stock/
│   │   ├── __init__.py
│   │   ├── data_fetcher.py          Yahoo Finance, Alpha Vantage, Polygon.io
│   │   ├── news_aggregator.py       NewsAPI, SEC EDGAR (CIK lookup + filings)
│   │   ├── fundamentals_analyst.py  LLM: ValuationSummary
│   │   ├── sentiment_analyst.py     LLM: SentimentSummary
│   │   └── research_synthesizer.py  LLM: ResearchBrief
│   └── board/
│       ├── __init__.py
│       ├── _base.py                 BoardMemberBase (shared prompt builder + JSON parser)
│       ├── org_normalizer.py        Structured + LLM normalization → OrgSnapshot
│       ├── chief_of_staff.py
│       ├── vp_engineering.py
│       ├── vp_product.py
│       ├── vp_people.py
│       ├── cto.py
│       ├── cfo_proxy.py
│       ├── conflict_detector.py     LLM: ConflictReport
│       └── cos_synthesis.py         LLM: BoardBriefing
│
├── pipelines/
│   ├── __init__.py
│   ├── stock_pipeline.py            StockResearchPipeline.run(StockPipelineInput)
│   └── board_pipeline.py            ExecutiveBoardPipeline.run(BoardSessionInput)
│
├── integrations/
│   ├── __init__.py
│   ├── jira.py                      Read-only Jira REST client
│   ├── linear.py                    Read-only Linear GraphQL client
│   ├── notion.py                    Read-only Notion database client
│   ├── slack.py                     Read-only Slack client (method whitelist guard)
│   ├── documents.py                 .docx / .pdf / .txt / .md text extractor (3-stage PDF strategy)
│   └── ocr.py                       Scanned PDF OCR via Claude Haiku vision API
│
├── schemas/
│   ├── __init__.py                  Exports all schemas (stock + board + legacy ML)
│   ├── stock.py                     ResearchBrief, ValuationSummary, SentimentSummary
│   ├── board.py                     OrgSnapshot, BoardBriefing, BoardMemberView, ...
│   └── [legacy ML schemas]          Kept for backwards compatibility
│
├── docs/
│   ├── README.md                    Architecture, schemas, API reference
│   ├── SETUP.md                     Step-by-step setup guide
│   ├── design.md                    This document
│   └── conversation.md              Original design session transcript
│
└── [legacy ML code]                 agents/eda_agent.py, agents/executor_agent.py, etc.
                                     Not imported by new code; can be removed
```

---

## 7. Build Sequence

### Phase 1 — Foundation ✅ Complete

- Extended `agents/api_utils.py` with `openai_compatible` provider and `LLMClient.from_config()`
- New `config.yaml` format with `llm.provider_chain` list
- Updated `pyproject.toml`: removed Kaggle/ML deps, added FastAPI/yfinance/httpx
- Created `schemas/stock.py` and `schemas/board.py`
- Created `server.py` (FastAPI at localhost:7842) with lifespan pipeline init
- Async board sessions with background task + polling endpoint

### Phase 2 — Stock Research ✅ Complete

- `agents/stock/data_fetcher.py` — yfinance + Alpha Vantage + Polygon.io
- `agents/stock/news_aggregator.py` — NewsAPI + SEC EDGAR (CIK lookup)
- `agents/stock/fundamentals_analyst.py` — LLM with fallback on parse error
- `agents/stock/sentiment_analyst.py` — LLM with headline/filing context
- `agents/stock/research_synthesizer.py` — LLM final synthesis
- `pipelines/stock_pipeline.py` — `StockResearchPipeline.from_config()`
- `StockResearch.tsx` Chrome extension component — **pending**

### Phase 3 — Executive Board Core ✅ Complete

- `agents/board/_base.py` — shared `BoardMemberBase` with prompt builder and JSON fallback
- All 6 board member agents with persona system prompts
- `agents/board/org_normalizer.py` — handles structured + unstructured input; LLM fallback for paste/docs
- `agents/board/conflict_detector.py` and `agents/board/cos_synthesis.py`
- `pipelines/board_pipeline.py` — `ExecutiveBoardPipeline.from_config()` with parallel fan-out
- `ExecutiveBoard.tsx` Chrome extension component — **pending**

### Phase 4 — Integrations ✅ Complete (ahead of schedule)

- `integrations/jira.py` — fetch by project key, label, or board sprint
- `integrations/linear.py` — GraphQL issues + cycle velocity
- `integrations/notion.py` — database query with pagination; property type helpers
- `integrations/slack.py` — read-only with `_ALLOWED_METHODS` hard guard *(added beyond original scope)*
- `integrations/documents.py` — .docx/.pdf/.txt/.md extraction with size and type guards *(added beyond original scope)*
- Settings UI in Chrome extension — **pending**

### Phase 4 Extensions ✅ Complete

- **`integrations/ocr.py`** — `ScannedPDFOCR` class: PyMuPDF page rendering + Claude Haiku vision OCR for image-based PDFs; in-memory only, no disk writes; reuses `llm.provider_chain` Anthropic key automatically
- **`integrations/documents.py`** — upgraded to 3-stage PDF strategy: PyMuPDF text → pypdf fallback → sparse detection → OCR via `ScannedPDFOCR`; `from_config()` auto-initializes OCR engine when `ocr.enabled: true`
- **`config.yaml`** — new `ocr:` section with `enabled`, `model`, `dpi`, `api_key` fields
- **`agents/board/chief_of_staff.py`** — completely rewritten with Amazon Precision Questioning framework (7 principles + 9 pitfalls) and Pareto/80-20 principle; custom `_build_cos_prompt()` that surfaces all data gaps explicitly; overrides `analyze()` with 2500-token budget

### Phase 5 — Chrome Extension *(pending)*

- `StockResearch.tsx` — ticker input, depth selector, pipeline progress, ResearchBrief renderer
- `ExecutiveBoard.tsx` — data tab, session tab, board progress view, briefing tab
- Settings panel — API keys, Notion DB IDs, Slack channel IDs, document folder path
- Result caching in Chrome storage (4-hour TTL for stock research)

---

## 8. Open Questions — Status

| # | Question                                                     | Status                                                                                                                                                                                           |
|---|--------------------------------------------------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| 1 | **Org mapping**: How are VP teams identified in Jira/Linear? | **Resolved** — by project key (`jira_project_keys`) or team key (`linear_team_keys`) configured in `config.yaml`. The `OrgNormalizerAgent` uses these to group issues by team.                   |
| 2 | **Board member personas**: Generic roles or actual VP names? | **Resolved as generic** — personas use role titles (Chief of Staff, VP Engineering, etc.). Actual names can be injected via `raw_paste` or `context` if needed.                                  |
| 3 | **Stock research depth**: Should "Quick" mode skip EDGAR?    | **Resolved** — `depth="quick"` skips Alpha Vantage, Polygon.io, and SEC EDGAR. Only yfinance + NewsAPI run.                                                                                      |
| 4 | **Decision Advisory debate**: Sequential or parallel?        | **Resolved as parallel** — all board members respond to the proposal simultaneously from their lens. CoS then synthesizes the debate. Sequential mode available via `parallel_execution: false`. |
| 5 | **FastAPI server access model**: Always-on or on-demand?     | **Open** — currently launched manually with `python server.py`. Always-on service setup (Windows nssm / macOS launchd) documented in SETUP.md but not automated.                                 |
