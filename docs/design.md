# Design Document: OpenResearch — Autonomous ML Research Assistant

**Date:** 2026-05-17
**Updated:** 2026-05-23
**Status:** Phases 1–8 complete; Chrome Extension (Phase 5) pending
**Scope:** Domain-agnostic research pipeline platform — Stock Research ✅, Executive Board ✅, Interview Prep ✅, Real Estate ✅, MCP Server ✅, Tolaria ✅, Equibles ✅, Equibles financial data ✅, Real Estate Research 🔲 (Phase 8)

---

## 0. What OpenResearch Is

OpenResearch is an **autonomous ML research assistant**. Given a research goal, it combines a set of agents, skills, MCP tools, and data sources to produce:

- Tested baselines
- Clear comparisons across approaches
- A structured starter pack you can build on

Each **research area** is a self-contained domain under `agents/`. The platform's pipeline architecture, LLM abstraction, and schema patterns are shared infrastructure — new research areas are added by defining new agents and a pipeline, not by modifying core code.

### Research Area Structure

Every research area follows this layout:

```
agents/{area}/
├── README.md              # Goal, scope, target user, domain — the "what and why"
├── config.yaml (ref)      # Which agents/skills apply; area-specific LLM overrides
├── data/
│   ├── sources.yaml       # Data source definitions (connectors, API refs)
│   ├── raw/               # Downloaded / ingested data
│   └── processed/         # Cleaned, featurized, ready-for-use
├── experiments/
│   └── run_NNN/           # Config snapshot + results per run
├── baselines/             # Baseline implementations and their results
├── evaluation/            # Metrics definitions, comparison tables
└── output/
    ├── report.md          # Human-readable findings
    └── starter_pack/      # The "build on this" artifact — code, templates, runbooks
```

Agents and skills shared across research areas live at the repo level (`agents/api_utils.py`, future `skills/`). A per-area `config.yaml` reference selects which agents and skills apply to that area.

### Currently Implemented Research Areas

| Area            | Folder                 | Status        |
|-----------------|------------------------|---------------|
| Stock Research  | `agents/stock/`        | ✅ Complete   |
| Executive Board | `agents/board/`        | ✅ Complete   |
| Interview Prep  | `agents/interview/`    | ✅ Complete   |
| Real Estate     | `agents/realestate/`   | ✅ Complete   |

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

The architecture has two layers: **shared infrastructure** (LLM client, FastAPI server, schemas) and **research domains** (agents + pipeline per area). Adding a new research area does not touch the infrastructure layer.

```
┌───────────────────────────────────────────────────────────────────────────────┐
│                          Chrome Extension (existing)                          │
│  StockResearch.tsx  ExecutiveBoard.tsx  InterviewPrep.tsx  RealEstate.tsx(p8) │
└──────────┬──────────────────┬─────────────────┬──────────────┬────────────────┘
           │                  │                 │              │  HTTP (localhost)
┌──────────▼──────────────────▼─────────────────▼──────────────▼────────────────┐
│                     Local FastAPI Server  server.py  v0.4.0                   │
│  /api/stock-research        /api/board-session       /api/health              │
│  /api/board-status/:id      /api/board-health                                 │
│  /api/interview-prep        /api/profile/add-resume                           │
│  /api/profile               /api/tracker             /api/tracker/update      │
│  /api/tracker/insights      /api/export/tolaria                               │
│  /api/learn/due             /api/learn/review        /api/learn/stats         │
│  /api/real-estate-research                                                    │
└──────────┬──────────────────┬─────────────────┬──────────────┬────────────────┘
           │                  │                 │              │
  ┌────────▼──────┐  ┌────────▼──────┐  ┌──────▼──────┐  ┌───▼──────────────┐
  │ StockResearch │  │ ExecutiveBoard│  │  Interview  │  │  RealEstate      │
  │ Pipeline      │  │ Pipeline      │  │  Research   │  │  Pipeline        │
  │ (5 nodes)     │  │ (4 stages)    │  │  Pipeline   │  │  (5 nodes)       │
  │               │  │               │  │  (5 nodes)  │  │                  │
  └────────┬──────┘  └────────┬──────┘  └──────┬──────┘  └───┬─────────────┘
           └──────────────────┴────────────────┴─────────────┘
                                       │                  ┌─────────────────────┐
                    ┌──────────────────▼──────────────┐   │  Persistent Stores  │
                    │  LLMClient (from_config)         │   │  data/profile.json  │
                    │  Anthropic | OpenAI | local LLM │   │  data/applications  │
                    └──────────────────────────────────┘   │  data/skills.json   │
                                                           └─────────────────────┘
```

### Pattern: Adding a new research domain

1. Create `agents/{area}/` with a `_base.py` (if agents share structure), individual agent files, and a `README.md`
2. Create `schemas/{area}.py` with input and output Pydantic models
3. Create `pipelines/{area}_pipeline.py` with a `{Area}Pipeline.from_config()` class
4. Register two endpoints in `server.py`: one to submit a job, one to poll results (async pattern) or a single sync endpoint for fast pipelines
5. Add area-specific config block to `config.yaml`

### Local API Server

`server.py` — FastAPI at `localhost:7842`. Initialized at startup via `lifespan()` which builds both pipeline singletons from `config.yaml`.

```
# Core
GET  /api/health                        # liveness + pipeline status + profile_exists flag
POST /api/stock-research                # { ticker, depth } → ResearchBrief (sync)
POST /api/board-session                 # { mode, context, data_sources, raw_paste } → { session_id }
GET  /api/board-status/:id              # { status, result, error, created_at, completed_at }
POST /api/board-health                  # { check_jira, check_linear, check_notion, check_slack }

# Interview Research (Phase 6 — complete)
POST /api/interview-prep                # { jd_text, profile_text?, company_name, role_title, depth, export_to_tolaria? } → InterviewPrepBrief + TailoredResume

# Profile store
POST /api/profile/add-resume            # { resume_text } → merge into master profile
GET  /api/profile                       # current MasterProfile
DELETE /api/profile                     # clear profile

# Application tracker
GET  /api/tracker                       # list applications (?format=markdown for table)
POST /api/tracker/update                # { application_id, stage, outcome?, notes? }
GET  /api/tracker/insights              # pattern analysis: win rate, funnel, failure stage, action items

# Skills / SM-2 learning
GET  /api/learn/due                     # questions due today, sorted most-overdue first
POST /api/learn/review                  # { question_id, quality (0–5), notes? } → next review date
GET  /api/learn/stats                   # total, due_today, by_category, average_ef

# Real Estate Research (Phase 8)
POST /api/real-estate-research          # { address, city, state, zip?, depth, documents_dir?, export_to_tolaria? } → RealEstateBrief

# Tolaria vault export
POST /api/stock-research                # add export_to_tolaria=true to save brief to vault
POST /api/interview-prep                # add export_to_tolaria=true to save brief + resume to vault
POST /api/real-estate-research          # add export_to_tolaria=true to save brief to vault
```

Board sessions run as FastAPI `BackgroundTask`. The caller gets a `session_id` immediately and polls `/api/board-status/:id` until `status == "done"`.

Interview prep runs synchronously (~25–45s). It auto-logs to the application tracker and seeds new questions into the skills bank on completion. If `profile_text` is omitted, the stored master profile is used automatically.

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
    - Equibles (if running, depth=full): 13F institutional holdings,
        FINRA short volume + SEC fails-to-deliver, computed technical indicators
        (RSI, MACD, Bollinger Bands, SMAs), congressional trading disclosures
    ↓
[Node 2] NewsAggregatorAgent          agents/stock/news_aggregator.py
    - NewsAPI (if key): last 30 days headlines
    - SEC EDGAR (free): recent 8-K, 10-Q, 10-K filings via CIK lookup
    - Equibles (if running, depth=full): SEC full-text search — excerpts from
        risk factors, revenue guidance, MD&A sections (not just filing metadata);
        SEC Form 3/4 insider transactions (last 90 days)
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
    - Equibles data (institutional, market_structure, technicals) injected into
      prompt when available — brief cites real ownership changes, short pressure,
      insider activity, and technical signals
    output: ResearchBrief (includes optional Equibles sub-schemas)
    ↓
ResearchBrief → FastAPI response
```

`depth="quick"` skips Alpha Vantage, Polygon.io, SEC EDGAR, and all Equibles calls. Useful for fast tests or when only API keys for NewsAPI and Yahoo Finance are configured.

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

# ── Equibles-sourced schemas (present when Equibles is running + depth="full") ──

class InstitutionalHolder(BaseModel):
    institution: str
    shares_held: int | None
    value_usd: float | None
    pct_of_shares_outstanding: float | None
    change_pct: float | None                             # QoQ change
    change_direction: Literal["increased","decreased","new","unchanged"] | None

class InstitutionalSnapshot(BaseModel):                 # 13F data
    total_institutional_ownership_pct: float | None
    top_holders: list[InstitutionalHolder]
    recent_changes_summary: str
    as_of_quarter: str | None

class InsiderTransaction(BaseModel):                    # Form 3/4
    insider_name: str
    title: str | None
    transaction_type: str | None                        # "Buy", "Sell", "Exercise"
    shares: int | None
    price_per_share: float | None
    total_value: float | None
    transaction_date: str | None
    form_type: str | None

class MarketStructureData(BaseModel):                   # FINRA + Form 3/4 + congressional
    short_volume_pct: float | None
    short_interest_ratio: float | None                  # days-to-cover
    fails_to_deliver: int | None
    short_interest_trend: str | None
    recent_insider_transactions: list[InsiderTransaction]
    insider_net_activity: Literal["net_buyer","net_seller","neutral"] | None
    insider_summary: str
    congressional_trades: list[str]

class TechnicalIndicators(BaseModel):                   # RSI, MACD, Bollinger, SMAs
    rsi_14: float | None
    macd: float | None
    macd_signal: float | None
    macd_histogram: float | None
    bb_upper: float | None
    bb_lower: float | None
    sma_50: float | None
    sma_200: float | None
    volume_avg_30d: float | None
    price_vs_sma50: str | None                          # "above", "below", "at"
    price_vs_sma200: str | None
    trend_signal: str | None                            # plain-English summary

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
    institutional: InstitutionalSnapshot | None         # None when Equibles not running
    market_structure: MarketStructureData | None        # None when Equibles not running
    technicals: TechnicalIndicators | None              # None when Equibles not running
    sources: list[str]
```

### Data Sources & Keys

| Source                   | Auth         | Free Tier       | Implemented                                   |
|--------------------------|--------------|-----------------|-----------------------------------------------|
| Yahoo Finance (yfinance) | None         | Unlimited       | Yes                                           |
| Alpha Vantage            | API key      | 25 req/day      | Yes                                           |
| Polygon.io               | API key      | 5 req/min       | Yes (earnings calendar)                       |
| NewsAPI                  | API key      | 100 req/day     | Yes                                           |
| SEC EDGAR                | None         | Unlimited       | Yes (CIK lookup + filing index)               |
| **Equibles** (self-hosted) | Docker only | Unlimited (local) | Yes — 13F, Form 3/4, FINRA short, FTD, FRED, CFTC, CBOE, full-text SEC, technical indicators |

API keys stored in `config.yaml` under `stock_research.data_sources`.

#### Equibles Setup

Equibles is a self-hosted Docker service — no cloud dependency, no rate limits, no API keys required (FINRA + FRED keys are optional free additions).

```bash
git clone https://github.com/daniel3303/Equibles
cd Equibles
docker compose up -d          # web portal: localhost:8080 | MCP server: localhost:8081
```

Then set `mcp.equibles.enabled: true` in `config.yaml`. On first run, Equibles begins scraping SEC/FINRA/FRED in the background; initial sync may take several minutes.

Optional free keys (provide additional data depth):
- **FINRA key**: https://gateway.finra.org/ — FINRA short volume data
- **FRED key**: https://fred.stlouisfed.org/ — Federal Reserve economic indicators

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

## 6. MCP Support

MCP (Model Context Protocol) is the standard protocol for connecting AI agents to external tools and data sources. OpenResearch supports MCP in two directions:

- **Client** — agents consume MCP servers as tool providers during a research run
- **Server** — OpenResearch exposes its own pipelines as MCP tools so Claude Code and other MCP clients can invoke them directly

### 6.1 MCP as Client (consuming external MCP servers)

Each research area can declare a set of MCP servers it needs. These are registered in `.mcp.json` at the repo root and referenced per-area in `config.yaml`.

#### `.mcp.json` (repo root)

```json
{
  "mcpServers": {
    "brave-search": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-brave-search"],
      "env": { "BRAVE_API_KEY": "" }
    },
    "fetch": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-fetch"]
    },
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "./research_areas"]
    },
    "github": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "env": { "GITHUB_PERSONAL_ACCESS_TOKEN": "" }
    },
    "equibles": {
      "type": "sse",
      "url": "http://localhost:8081/sse"
    }
  }
}
```

#### Per-area MCP config in `config.yaml`

```yaml
mcp:
  enabled: true
  servers:
    stock_research:
      - brave-search      # company news + macro research
      - fetch             # SEC EDGAR, investor relations pages
    interview:
      - brave-search      # company intel, interview culture research
      - fetch             # job posting pages, Glassdoor, LinkedIn
    board:
      - filesystem        # read local documents dropped into research_areas/
```

#### How agents use MCP tools

Agents that need web access or file access receive an `mcp_client` handle alongside the `LLMClient`. Tool calls are routed through the MCP client rather than direct HTTP:

```python
class CompanyResearcherAgent:
    def __init__(self, llm: LLMClient, mcp: MCPClient | None = None):
        self.llm = llm
        self.mcp = mcp

    async def research(self, company_name: str) -> CompanyProfile:
        # MCP tool call — falls back to direct fetch if mcp is None
        raw = await self.mcp.call("brave-search", {"query": f"{company_name} interview culture"})
        ...
```

`MCPClient` (`agents/mcp_client.py`) calls tools and returns plain text results. Current implementation uses direct HTTP to the Brave Search API and `httpx` for URL fetch — the same behaviour as the MCP server wrappers but without requiring a Node.js process. It degrades gracefully: if no key is configured for a tool, `is_available()` returns `False` and the agent falls back to LLM-only inference. Phase 7 will replace the direct HTTP calls with a proper MCP stdio/SSE transport; the agent-facing `call_sync()` API stays identical.

### 6.2 MCP as Server (exposing OpenResearch pipelines)

OpenResearch can expose its research pipelines as MCP tools so that Claude Code, Claude Desktop, or any other MCP client can invoke them without going through the HTTP API.

#### Exposed tools

| MCP Tool             | Maps to                  | Input                                     | Output                      |
|----------------------|--------------------------|-------------------------------------------|-----------------------------|
| `run_stock_research` | `StockResearchPipeline`  | `ticker`, `depth`                         | `ResearchBrief` (JSON)      |
| `run_board_session`  | `ExecutiveBoardPipeline` | `mode`, `context`, `raw_paste`            | `BoardBriefing` (JSON)      |
| `run_interview_prep` | `InterviewPipeline`      | `jd_text`, `profile_text`, `company_name` | `InterviewPrepBrief` (JSON) |

#### MCP server entry point (`mcp_server.py`) ✅ Built

```python
from mcp.server import MCPServer
from pipelines.stock_pipeline import StockResearchPipeline
from pipelines.board_pipeline import ExecutiveBoardPipeline
from pipelines.interview_pipeline import InterviewPipeline

server = MCPServer("openresearch")

@server.tool("run_stock_research")
async def run_stock_research(ticker: str, depth: str = "standard") -> dict:
    pipeline = StockResearchPipeline.from_config("config.yaml")
    result = await pipeline.run(StockPipelineInput(ticker=ticker, depth=depth))
    return result.model_dump()

# ... board and interview tools follow the same pattern
```

Register in `.mcp.json` so Claude Code can pick it up:

```json
{
  "mcpServers": {
    "openresearch": {
      "command": "python",
      "args": ["mcp_server.py"],
      "cwd": "."
    }
  }
}
```

Once registered, a Claude Code session can call `run_stock_research(ticker="NVDA")` as a native tool — no HTTP required.

### 6.3 MCP per Research Area

| Research Area   | Consumes                        | Status   | Benefit                                                                                                                                       |
|-----------------|---------------------------------|----------|-----------------------------------------------------------------------------------------------------------------------------------------------|
| Stock Research  | `equibles`                      | ✅ Done  | 13F institutional holders, FINRA short interest + FTD, Form 3/4 insider trades, congressional disclosures, technical indicators, SEC full-text search — all local, no keys, no rate limits |
| Stock Research  | `brave-search`, `fetch`         | Phase 9  | Live web search supplements yfinance + NewsAPI; fetch investor relations pages directly                                                       |
| Executive Board | `filesystem`                    | Phase 9  | Drop org documents into `research_areas/board/data/raw/` and the pipeline reads them via MCP filesystem rather than the documents integration |
| Interview Prep  | `brave-search`, `fetch`         | ✅ Done  | `CompanyResearcherAgent` runs 3 Brave Search queries → injects live Glassdoor/blog intel before LLM call; falls back gracefully              |

### 6.5 Tolaria Vault Integration ✅ Complete

Tolaria is an Obsidian-compatible personal knowledge base that exposes an MCP endpoint. OpenResearch writes research artefacts to it automatically when `export_to_tolaria=true` is passed to any pipeline endpoint.

#### How it works

`integrations/tolaria.py` — `TolariaClient` uses the [Obsidian Local REST API](https://github.com/coddingtonbear/obsidian-local-rest-api) protocol:

```
PUT /vault/<vault_folder>/<subfolder>/<slug>.md
Content-Type: text/markdown
Authorization: Bearer <api_key>   (if auth enabled)
Body: rendered Markdown
```

A 200/201/204 response means the note appeared in the vault immediately.

#### Vault folder layout

```
<vault_folder>/         (default: "OpenResearch")
├── interview/
│   └── <company>-<role>.md          # InterviewPrepBrief (fit + questions + STAR answers + top 3 priorities)
├── resumes/
│   └── <company>-<role>-resume.md   # TailoredResume.full_resume_md
├── stock/
│   └── <TICKER>-<date>.md           # ResearchBrief (verdict, bull/bear, fundamentals)
└── board/
    └── board-briefing-<date>.md     # BoardBriefing (exported when export_to_tolaria=true)
```

#### Config

```yaml
mcp:
  brave_search_key: ""        # Brave Search API key — api.search.brave.com
  tolaria:
    enabled: false            # set true once Tolaria/Obsidian Local REST API is running
    server_url: "http://localhost:27123"
    api_key: ""               # blank = no auth (default for local use)
    vault_folder: "OpenResearch"
    local_fallback_dir: "output"   # writes here if vault is unreachable
```

#### Fallback behaviour

If `server_url` is not set or the vault is unreachable, `TolariaClient` writes the same Markdown to `output/<subfolder>/<slug>.md` locally. The pipeline always completes — the destination is just a local file rather than the vault.

### 6.4 Build Plan

| Step | Deliverable                                                                                  | Phase   | Status |
|------|----------------------------------------------------------------------------------------------|---------|--------|
| 1    | `config.yaml` `mcp:` section — `brave_search_key`, Tolaria config                           | Phase 6 | ✅ Done |
| 2    | `agents/mcp_client.py` — `MCPClient` (Brave Search HTTP + fetch); graceful fallback          | Phase 6 | ✅ Done |
| 3    | Wire `MCPClient` into `CompanyResearcherAgent` (interview)                                   | Phase 6 | ✅ Done |
| 4    | `integrations/tolaria.py` — vault write via Obsidian Local REST API; Markdown renderers      | Phase 6 | ✅ Done |
| 5    | Wire `export_to_tolaria` flag into `/api/interview-prep` and `/api/stock-research`           | Phase 6 | ✅ Done |
| 6    | Equibles SSE entry in `.mcp.json`; `mcp.equibles` config block                              | Phase 6 ext | ✅ Done |
| 7    | `MCPClient` extended with Equibles JSON-RPC transport + 6 helper methods                     | Phase 6 ext | ✅ Done |
| 8    | `DataFetcherAgent` + `NewsAggregatorAgent` extended with Equibles calls                      | Phase 6 ext | ✅ Done |
| 9    | `schemas/stock.py` — `InstitutionalSnapshot`, `MarketStructureData`, `TechnicalIndicators`  | Phase 6 ext | ✅ Done |
| 10   | `ResearchSynthesizerAgent` extended — Equibles data in prompt + typed schema attachment      | Phase 6 ext | ✅ Done |
| 11   | `StockResearchPipeline` — `MCPClient` wired end-to-end through all nodes                    | Phase 6 ext | ✅ Done |
| 12   | Upgrade `MCPClient` to full MCP stdio/SSE transport (replace direct HTTP calls)              | Phase 7 | ✅ Done (via `mcp_server.py` stdio transport) |
| 13   | `mcp_server.py` — expose all four pipelines as MCP tools                                     | Phase 7 | ✅ Done |
| 14   | Register `openresearch` server in `.mcp.json` for Claude Code / Claude Desktop               | Phase 7 | ✅ Done |

---

## 7. File Structure (as implemented)

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
│   ├── mcp_client.py                MCPClient: brave-search (direct HTTP) + fetch + Equibles (MCP JSON-RPC); fallback-safe
│   └── interview/
│       ├── __init__.py
│       ├── job_fit_analyzer.py      LLM: experience vs JD gap analysis → FitVerdict
│       ├── company_researcher.py    live Brave Search → LLM synthesis → CompanyProfile
│       ├── question_generator.py    LLM: gap-weighted question set → QuestionSet
│       ├── answer_generator.py      LLM: STAR answers from profile (PromptBudget) → AnswerSet
│       ├── resume_writer.py         LLM: JD-targeted resume rewrite → TailoredResume (Node 5)
│       └── profile_builder.py       LLM: parse resume OR merge into MasterProfile
│   └── realestate/                  (Phase 8)
│       ├── __init__.py
│       ├── document_ingestion.py    wraps DocumentLoader + ScannedPDFOCR → list[DocumentInsight]
│       ├── migration_analyst.py     IRS SOI, Census ACS, U-Haul, FRED → MigrationSnapshot (city+state)
│       ├── economic_analyst.py      BLS, FRED, BEA, tax tables → LaborMarketSnapshot + CostOfLivingSnapshot
│       ├── housing_analyst.py       Zillow, Redfin, Census permits, HUD, FBI, EPA, FEMA → HousingMarketSnapshot + DemandFactorsSnapshot
│       └── synthesizer.py           LLM: all snapshots + documents → RealEstateBrief
│
├── pipelines/
│   ├── __init__.py
│   ├── stock_pipeline.py            StockResearchPipeline.run(StockPipelineInput)
│   ├── board_pipeline.py            ExecutiveBoardPipeline.run(BoardSessionInput)
│   ├── interview_pipeline.py        InterviewPipeline.run(InterviewPipelineInput)
│   └── realestate_pipeline.py       RealEstatePipeline.run(RealEstatePipelineInput)  (Phase 8)
│
├── store/
│   ├── __init__.py
│   ├── profile_store.py             ProfileStore — atomic R/W of data/profile.json
│   ├── application_store.py         ApplicationStore — R/W applications.json + .md; dedup by company+role
│   └── skills_store.py              SkillsStore — SM-2 tracker; R/W data/skills.json
│
├── integrations/
│   ├── __init__.py
│   ├── jira.py                      Read-only Jira REST client
│   ├── linear.py                    Read-only Linear GraphQL client
│   ├── notion.py                    Read-only Notion database client
│   ├── slack.py                     Read-only Slack client (method whitelist guard)
│   ├── documents.py                 .docx / .pdf / .txt / .md extractor (3-stage PDF strategy)
│   ├── ocr.py                       Scanned PDF OCR via Claude Haiku vision API
│   └── tolaria.py                   TolariaClient: vault notes via Obsidian Local REST API + Markdown renderers
│
├── schemas/
│   ├── __init__.py                  Exports all schemas
│   ├── stock.py                     ResearchBrief, ValuationSummary, SentimentSummary
│   ├── board.py                     OrgSnapshot, BoardBriefing, BoardMemberView, ...
│   ├── interview.py                 InterviewPipelineInput, FitVerdict, CompanyProfile,
│   │                                QuestionSet, STARAnswer, AnswerSet, InterviewPrepBrief
│   ├── profile.py                   MasterProfile, Experience, Education
│   ├── tracker.py                   ApplicationRecord, ApplicationTracker
│   ├── skills.py                    TrackedQuestion, ReviewResult, DueQuestion, SkillsBank
│   ├── realestate.py                RealEstateBrief, MigrationSnapshot, LaborMarketSnapshot,
│   │                                HousingMarketSnapshot, CostOfLivingSnapshot, DemandFactorsSnapshot,
│   │                                DocumentInsight, MigrationSignal  (Phase 8)
│   └── [legacy ML schemas]          Kept for backwards compatibility
│
├── data/                            Local persistent state (git-ignored)
│   ├── profile.json                 Master candidate profile (built from N resumes)
│   ├── applications.json            Application tracker records
│   ├── applications.md              Human-readable tracker table (auto-generated)
│   └── skills.json                  SM-2 question bank with review state
│
├── docs/
│   ├── README.md                    Architecture, schemas, API reference
│   ├── SETUP.md                     Step-by-step setup guide
│   ├── design.md                    This document
│   └── conversation.md              Original design session transcript
│
├── mcp_server.py                    MCP stdio server — 4 tools; lazy pipeline init; logs to stderr
│
└── [legacy ML code]                 agents/eda_agent.py, agents/executor_agent.py, etc.
                                     Not imported by new code; can be removed
```

---

## 8. Feature 3: Interview Research ✅ Complete (Phase 6 full)

### Goal

Given a job description and a candidate profile (resume, LinkedIn export, or plain text), produce a structured interview preparation brief covering fit assessment, company intelligence, tailored questions, and STAR-format answers drawn from the candidate's real experience.

### Source

Inspired by [mirrorwork](https://github.com/grandimam/mirrorwork). Core loop: profile → fit → company intel → tailored questions → STAR answers → track → learn. Maps cleanly onto the existing agent + pipeline pattern.

### Pipeline (`pipelines/interview_pipeline.py`)

```
InterviewPipelineInput(jd_text, profile_text?, company_name, role_title, depth)
    ↓  profile_text=None → loaded automatically from ProfileStore
[Node 1] JobFitAnalyzerAgent           agents/interview/job_fit_analyzer.py
    - 80/20: identifies the 20% of gaps causing 80% of rejections
    - Output: FitVerdict (overall_score, match_strengths, gaps, deal_breakers, recommendation)
    ↓
[Node 2] CompanyResearcherAgent        agents/interview/company_researcher.py
    - depth=quick: returns generic profile (no LLM call)
    - depth=full + brave_search_key: 3 Brave Search queries → live Glassdoor/blog intel injected
    - depth=full + no key: LLM training knowledge only (fallback)
    - Output: CompanyProfile (culture_summary, interview_style, known_values, prep_priorities)
    ↓
[Node 3] QuestionGeneratorAgent        agents/interview/question_generator.py
    - 5 behavioural (gap-weighted) + 5 technical (JD-derived) + 3 culture-fit + 2 curveball
    - Output: QuestionSet
    ↓
[Node 4] AnswerGeneratorAgent          agents/interview/answer_generator.py
    - STAR answers for behavioural + culture-fit questions (technical = knowledge, not stories)
    - Uses PromptBudget to handle large profiles without overflow
    - Results must include specific numbers/dates (enforced in prompt + tailoring_note flag)
    - Output: AnswerSet
    ↓  (depth=full only)
[Node 5] ResumeWriterAgent             agents/interview/resume_writer.py
    - Rewrites master profile as JD-targeted resume — reframe, reorder, never fabricate
    - Emphasises FitVerdict.match_strengths; treats gaps honestly (not hidden)
    - Output: TailoredResume (summary, highlighted_skills, experience_bullets,
               cover_letter_opener, full_resume_md, tailoring_notes)
    ↓
InterviewPrepBrief → auto-logged to ApplicationStore + questions seeded to SkillsStore
    → optional: export brief + resume to Tolaria vault (export_to_tolaria=true)
    → response
```

### Output Schema (`schemas/interview.py`)

```python
class FitVerdict(BaseModel):
    overall_score: float                    # 0–10
    match_strengths: list[str]
    gaps: list[str]
    deal_breakers: list[str]
    recommendation: Literal["strong_fit", "worth_pursuing", "stretch", "not_recommended"]
    summary: str                            # 2–3 sentences: biggest strength + risk

class CompanyProfile(BaseModel):
    culture_summary: str
    interview_style: str                    # e.g. "behavioural-heavy", "case + system design"
    known_values: list[str]
    prep_priorities: list[str]
    red_flags: list[str]

class QuestionSet(BaseModel):
    behavioural: list[str]
    technical: list[str]
    culture_fit: list[str]
    curveball: list[str]

class STARAnswer(BaseModel):
    question: str
    situation: str
    task: str
    action: str
    result: str
    tailoring_note: str                     # how this answer lands for this specific company

class AnswerSet(BaseModel):
    answers: list[STARAnswer]

class TailoredResume(BaseModel):            # new — Node 5 output (depth=full only)
    target_role: str
    target_company: str
    summary: str                            # rewritten professional summary for this JD
    highlighted_skills: list[str]           # skills filtered + ordered by JD relevance
    experience_bullets: list[str]           # top 5–7 achievement bullets reframed for this role
    cover_letter_opener: str                # opening paragraph of a strong cover letter
    full_resume_md: str                     # complete tailored resume in Markdown (submission-ready)
    tailoring_notes: list[str]              # transparency log: what was changed and why

class InterviewPrepBrief(BaseModel):
    role_title: str
    company_name: str
    as_of_date: str
    fit: FitVerdict
    company: CompanyProfile
    questions: QuestionSet
    answers: AnswerSet
    top_3_priorities: list[str]             # CoS-style: the 3 things to nail before the interview
    tailored_resume: TailoredResume | None  # present when depth="full"; None for quick mode
```

### API Endpoints

```
POST /api/interview-prep        { jd_text, profile_text?, company_name, role_title, depth, export_to_tolaria? }
                                → InterviewPrepBrief (includes TailoredResume when depth="full")
POST /api/profile/add-resume    { resume_text } — parse + merge into MasterProfile
GET  /api/profile               → MasterProfile
DELETE /api/profile             — clear stored profile
GET  /api/tracker               → list[ApplicationRecord] or markdown table (?format=markdown)
POST /api/tracker/update        { application_id, stage, outcome?, notes? }
GET  /api/tracker/insights      → pattern analytics: win rate, funnel, failure stage, fit correlation, action items
GET  /api/learn/due             → due questions sorted by most-overdue
POST /api/learn/review          { question_id, quality 0–5, notes? } → next_review_date
GET  /api/learn/stats           → { total, due_today, by_category, average_ef }
```

### Persistence Layer

Three local JSON files written to `data/` (path configured in `config.yaml` under `interview_research.data_dir`):

| Store               | File                                    | Class              | Key behaviour                                                        |
|---------------------|-----------------------------------------|--------------------|----------------------------------------------------------------------|
| Master profile      | `profile.json`                          | `ProfileStore`     | Atomic write; `MasterProfile.to_text()` renders for LLM context      |
| Application tracker | `applications.json` + `applications.md` | `ApplicationStore` | Deduplicates by company+role; re-runs increment `pipeline_run_count` |
| Skills bank         | `skills.json`                           | `SkillsStore`      | SM-2 per question; `add_questions()` skips existing IDs              |

#### ProfileBuilder (`agents/interview/profile_builder.py`)

Two operations:
- `_parse(resume_text)` — first resume; LLM extracts structured `MasterProfile`
- `_merge(existing, resume_text)` — subsequent resumes; LLM receives full existing profile JSON alongside the new resume to dedup experiences, union skills, and consolidate achievements intelligently

Fallback on parse failure: raw text is stored in `summary` so no data is lost.

#### SM-2 Algorithm (`store/skills_store.py`)

```
EF' = EF + (0.1 − (5−q) × (0.08 + (5−q) × 0.02))   EF' = max(1.3, EF')
quality < 3  → reps = 0, interval = 1 day   (failed — review tomorrow)
quality ≥ 3  → reps == 0: interval = 1
               reps == 1: interval = 6
               reps ≥ 2:  interval = round(prev × EF')
```

`add_questions()` is called automatically after every pipeline run — new questions are seeded with `next_review_date = today` (due immediately). Questions already in the bank are skipped, preserving their SM-2 state.

### Connection to Precision Questioning

The `AnswerGeneratorAgent`'s STAR structure enforces the same discipline as the Chief of Staff agent: every `result` must contain a specific number or date; the `tailoring_note` explains the framing for this company's values. A `"WEAK: strengthen with metrics"` flag is inserted when the candidate's profile lacks quantified outcomes.

---

## 9. Feature 4: Real Estate Research 🔲 Phase 8

### Goal

Given a target address (city, state, optional ZIP), produce a structured real estate demand brief by combining:

1. **Document intelligence** — ingest any PDF (text-based or scanned/OCR), Markdown, and plain-text files the user drops into a folder (property listings, appraisals, HOA docs, market reports). Uses the existing `ScannedPDFOCR` + `DocumentLoader` infrastructure.
2. **Migration analysis** — determine whether people are moving *into* or *out of* the target city and state, using a structured catalog of direct migration signals and push/pull demand indicators.
3. **Economic and housing fundamentals** — labor market conditions, housing supply/demand, cost of living, and quality-of-life factors that empirically drive residential migration decisions.

All indicators are computed at **two geographic levels**: the city/metro (via ZIP, county, or metro aggregation) and the state. Divergence between the two is itself informative.

---

### Pipeline (`pipelines/realestate_pipeline.py`)

```
RealEstatePipelineInput(address, city, state, zip?, depth, documents_dir?)
    ↓
[Node 1] DocumentIngestionAgent        agents/realestate/document_ingestion.py
    - Wraps DocumentLoader + ScannedPDFOCR (existing infrastructure, zero new code)
    - Accepts: .pdf (text or scanned/OCR), .md, .txt, .docx
    - Extracts: property facts, neighborhood mentions, market data, appraisal values
    - Output: list[DocumentInsight]
    ↓
[Node 2] MigrationAnalystAgent         agents/realestate/migration_analyst.py
    - Queries free data APIs: IRS SOI county migration, Census ACS flows,
      FRED population/migration series, Census Building Permits
    - Scrapes / parses public sources: U-Haul Growth Index (annual state/metro rankings)
    - Assembles city-level and state-level MigrationSnapshot
    - Computes net direction (inflow / outflow / neutral) with confidence score
    - Covers: direct COA-equivalent signals, IRS net migration, U-Haul in/out ratio,
      population growth rate, school enrollment trend, utility connection net
    - Output: MigrationSnapshot (city) + MigrationSnapshot (state)
    ↓
[Node 3] EconomicAnalystAgent          agents/realestate/economic_analyst.py
    - BLS API: unemployment rate + trend, employment growth, wage levels/growth,
      labor force participation, industry mix (NAICS-level job shares)
    - FRED: state/metro unemployment, wage series, remote-work indicators
    - Tax data: state income tax rate (static table), property tax rate (Census/STC)
    - Cost of living: BEA Regional Price Parities (metro/state)
    - Covers all Labor Market and Cost-of-Living factors from the demand catalog
    - Output: LaborMarketSnapshot + CostOfLivingSnapshot
    ↓
[Node 4] HousingMarketAgent            agents/realestate/housing_analyst.py
    - Zillow Research CSV (free download cache): ZHVI, ZORI, days on market, inventory
    - Redfin Data Center CSV: median sale price, list-to-sale ratio, market heat index
    - Census Building Permits: monthly permits by metro/county
    - HUD: vacancy rates, affordability indices
    - FBI UCR / NIBRS API: violent + property crime per 100k
    - EPA AQS API: air quality index (AQI) for the metro
    - FEMA National Flood Hazard Layer (static): flood zone designation
    - Output: HousingMarketSnapshot + DemandFactorsSnapshot
    ↓
[Node 5] RealEstateSynthesizerAgent    agents/realestate/synthesizer.py
    persona: "You are a real estate market analyst and migration economist..."
    - Receives all upstream snapshots + DocumentInsight list
    - Identifies the 3-5 dominant push/pull factors (Pareto-style)
    - Frames city vs state divergence explicitly when present
    - Flags data gaps (factors that could not be sourced)
    - Output: RealEstateBrief
    ↓
RealEstateBrief → FastAPI response (+ optional Tolaria vault export)
```

`depth="quick"` skips Zillow/Redfin CSV downloads, U-Haul scraping, EPA/FBI API calls,
and document ingestion. Returns a brief backed by FRED + BLS + Census only (~10s).

`depth="full"` runs all nodes including document ingestion and all data source queries (~45–90s).

---

### Migration Demand Catalog

The `MigrationAnalystAgent` and `EconomicAnalystAgent` jointly cover all eleven demand categories. The table below maps each category to the agent, data source, and geographic level.

#### Category 1 — Direct Migration Signals

| Signal | Source | Level | Agent |
|--------|--------|-------|-------|
| IRS net migration (inflows, outflows, net AGI) | IRS SOI Migration Data (free) | County → metro/city + state | Migration |
| USPS Change-of-Address net flows | Census/research proxies; USPS COA summary tables | ZIP → city + state | Migration |
| U-Haul Growth Index (one-way rental in/out ratio) | U-Haul annual public ranking (web) | Metro + state | Migration |
| Mobile OD flows (device home-location shift) | Placer.ai / public research aggregates | Metro | Migration |
| Census ACS "lived here 1 year ago" | Census Bureau API (free) | County → metro + state | Migration |

#### Category 2 — Labor Market

| Signal | Source | Level | Agent |
|--------|--------|-------|-------|
| Nonfarm employment growth | BLS CES API (free) | Metro + state | Economic |
| Unemployment rate + trend | BLS LAUS API (free) | Metro + state | Economic |
| Median wages + wage growth | BLS OES / QCEW API (free) | Metro + state | Economic |
| Industry mix (NAICS 2-digit job shares) | BLS QCEW API (free) | Metro + state | Economic |
| Major employer announcements / anchor employer presence | LLM synthesis + document ingestion | City | Synthesizer |
| Online job posting volume trend | BLS JOLTS + FRED (free) | State | Economic |

#### Category 3 — Housing Market

| Signal | Source | Level | Agent |
|--------|--------|-------|-------|
| Median home price + YoY appreciation | Zillow ZHVI / Redfin CSV (free) | Metro + state | Housing |
| Median asking rent + rent growth | Zillow ZORI / Redfin CSV (free) | Metro + state | Housing |
| Price-to-income ratio | ZHVI ÷ BLS median wage | Metro + state | Housing |
| Rental vacancy rate | Census HVS + HUD (free) | Metro + state | Housing |
| Residential building permits | Census Building Permits API (free) | Metro + state | Housing |
| Days on market + active inventory trend | Redfin Data Center CSV (free) | Metro | Housing |
| Supply elasticity proxy | Permit growth vs price growth divergence | Metro | Housing |

#### Category 4 — Cost of Living & Taxes

| Signal | Source | Level | Agent |
|--------|--------|-------|-------|
| Regional price parity (overall CoL index) | BEA RPP (free) | Metro + state | Economic |
| State income tax rate | Static table (Tax Foundation data) | State | Economic |
| Effective property tax rate | Census ACS / STC (free) | State + county | Housing |
| Rent-to-income ratio | ZORI ÷ BLS wage | Metro | Housing |

#### Category 5 — Amenities & Quality of Life

| Signal | Source | Level | Agent |
|--------|--------|-------|-------|
| Air quality index | EPA AQS API (free) | Metro | Housing |
| Walkability score | Walk Score API (free tier) | City | Housing |
| Broadband coverage % | FCC National Broadband Map (free) | County → city | Housing |
| Climate risk (flood zone, wildfire) | FEMA NFHL (free) | Address + metro | Housing |

#### Category 6 — Safety

| Signal | Source | Level | Agent |
|--------|--------|-------|-------|
| Violent crime rate per 100k | FBI NIBRS / UCR API (free) | City + state | Housing |
| Property crime rate per 100k | FBI NIBRS / UCR API (free) | City + state | Housing |

#### Categories 7–11 (Demographic, Infrastructure, Policy, Behavioral, High-Frequency)

These are synthesized from the above primary sources plus document ingestion, FRED auxiliary series (school enrollment proxies, business application counts), and LLM inference when direct data is unavailable. Data gaps are explicitly flagged in `RealEstateBrief.data_gaps`.

---

### Output Schema (`schemas/realestate.py`)

```python
class MigrationSignal(BaseModel):
    source: str                                      # "IRS_SOI", "USPS_COA", "UHaul", "Census_ACS", etc.
    level: Literal["city", "state"]
    direction: Literal["net_inflow", "net_outflow", "neutral", "unknown"]
    magnitude: Literal["strong", "moderate", "weak"] | None
    value: float | None                              # raw net migration count if available
    period: str | None                               # e.g. "2022–2023"
    notes: str

class MigrationSnapshot(BaseModel):
    location: str                                    # e.g. "Austin, TX" or "Texas (state)"
    level: Literal["city", "state"]
    net_direction: Literal["net_inflow", "net_outflow", "neutral", "mixed"]
    confidence: float                                # 0–1; lower when few sources available
    signals: list[MigrationSignal]
    irs_net_migration: int | None                    # IRS SOI net filers (county-level)
    uhaul_rank: int | None                           # U-Haul growth rank; lower = more inbound
    population_growth_pct_yoy: float | None
    summary: str                                     # 2–3 sentences on net verdict + caveats

class LaborMarketSnapshot(BaseModel):
    unemployment_rate: float | None
    unemployment_trend: Literal["rising", "falling", "stable"] | None
    employment_growth_pct_yoy: float | None
    top_industries: list[str]                        # by employment share
    major_employers: list[str]                       # notable anchor employers in area
    job_creation_trend: str | None
    wage_median_annual: float | None
    wage_growth_pct_yoy: float | None
    jolts_openings_rate: float | None                # job openings as % of employment
    summary: str

class HousingMarketSnapshot(BaseModel):
    median_home_price: float | None
    home_price_growth_yoy_pct: float | None
    median_rent_monthly: float | None
    rent_growth_yoy_pct: float | None
    price_to_income_ratio: float | None
    rent_to_income_ratio: float | None
    vacancy_rate_rental: float | None
    days_on_market_median: float | None
    active_listings_trend: Literal["rising", "falling", "stable"] | None
    building_permits_yoy_pct: float | None
    supply_elasticity: Literal["constrained", "moderate", "elastic"] | None
    summary: str

class CostOfLivingSnapshot(BaseModel):
    regional_price_parity: float | None              # BEA RPP; 100 = national average
    state_income_tax_rate: float | None              # top marginal rate
    effective_property_tax_rate: float | None        # % of home value
    overall_assessment: Literal["low", "below_avg", "avg", "above_avg", "high"] | None
    summary: str

class DemandFactorsSnapshot(BaseModel):
    # Safety
    violent_crime_per_100k: float | None
    property_crime_per_100k: float | None
    crime_trend: Literal["improving", "stable", "worsening"] | None

    # Quality of life
    air_quality_index: float | None
    walkability_score: float | None                  # Walk Score 0–100
    broadband_coverage_pct: float | None

    # Climate risk
    flood_zone_risk: Literal["minimal", "moderate", "high", "very_high"] | None
    wildfire_risk: Literal["minimal", "moderate", "high", "very_high"] | None

    summary: str

class DocumentInsight(BaseModel):
    source_file: str
    file_type: Literal["pdf_text", "pdf_ocr", "markdown", "txt", "docx"]
    key_facts: list[str]
    property_mentions: list[str]                     # specific property / address references
    market_mentions: list[str]                       # market conditions, comp sales, appraisals

class RealEstateBrief(BaseModel):
    address: str
    city: str
    state: str
    zip_code: str | None
    as_of_date: str

    # Top-line verdict
    demand_verdict: Literal["strong_inflow", "moderate_inflow", "neutral",
                             "moderate_outflow", "strong_outflow"]
    investment_signal: Literal["Strong Buy", "Buy", "Hold", "Sell", "Strong Sell"]
    confidence: float                                # 0–1

    # Migration: both geographic levels always present
    city_migration: MigrationSnapshot
    state_migration: MigrationSnapshot
    migration_divergence: str | None                 # populated when city vs state disagree

    # Economic fundamentals
    labor_market: LaborMarketSnapshot
    housing_market: HousingMarketSnapshot
    cost_of_living: CostOfLivingSnapshot
    demand_factors: DemandFactorsSnapshot

    # Document intelligence (empty list when documents_dir not provided)
    document_insights: list[DocumentInsight]

    # Synthesized analysis
    summary: str                                     # 3–4 sentences: verdict + top driver + risk
    dominant_pull_factors: list[str]                 # top 3–5 factors driving inflows (Pareto)
    dominant_push_factors: list[str]                 # top 3–5 factors driving outflows
    key_risks: list[str]
    upcoming_catalysts: list[str]                    # events likely to shift demand
    data_gaps: list[str]                             # factors that could not be sourced

    sources: list[str]
```

---

### Data Sources & Keys

| Source | Auth | Free Tier | Covers |
|--------|------|-----------|--------|
| IRS SOI Migration Data | None | Unlimited (annual bulk files) | County in/outflows, net AGI of movers |
| Census Bureau API (ACS, Building Permits, HVS) | Free API key | Unlimited | Migration, demographics, permits, vacancy |
| BLS API (CES, LAUS, OES, QCEW, JOLTS) | None | Unlimited | Employment, wages, industry, job openings |
| FRED (Federal Reserve Economic Data) | Free API key | Unlimited | 800k+ metro/state economic series |
| BEA API (Regional Price Parities) | Free API key | Unlimited | Cost-of-living index by metro and state |
| Zillow Research (ZHVI, ZORI, etc.) | None | Free CSV download | Home prices, rents, inventory, market metrics |
| Redfin Data Center | None | Free CSV download | Sale prices, list-to-sale, days on market |
| HUD API | None | Unlimited | Vacancy, affordability, FMR rents |
| FBI NIBRS / UCR | None | Free API | Violent + property crime rates |
| EPA AQS API | None (free key) | Unlimited | Air quality index by metro |
| FEMA NFHL | None | Unlimited | Flood zone designation by address |
| Walk Score API | Free key (1k/day) | 1000 req/day | Walkability, transit, bike scores |
| FCC National Broadband Map | None | Unlimited | Broadband availability by address/county |
| U-Haul Growth Index | Web scraping (public) | Annual state/metro rankings | One-way rental in/out ratio |
| FEMA NFHL (ArcGIS REST) | None | Unlimited | Property flood zone designation, BFE |
| First Street Foundation | Free API key (research) | Limited | Flood Factor + Fire Factor 1–10 scores, 30yr risk |
| FEMA OpenFEMA | None | Unlimited | Disaster declaration history by county + type |
| NOAA Storm Events / CDO | Free token | Unlimited | Historical storm counts, damage $, extreme weather |
| FEMA National Risk Index | None | Unlimited | County-level composite hazard risk: flood, wildfire, hurricane, wind |
| Census Geocoder | None | Unlimited | Address → lat/lon + FIPS county (required for all property-level queries) |

API keys stored in `config.yaml` under `real_estate_research.data_sources`. Most sources are fully free — the only optionally-paid addition is Placer.ai for mobile OD flows (has a public-data tier).

---

### Document Ingestion Details

`DocumentIngestionAgent` wraps the **existing** `DocumentLoader` and `ScannedPDFOCR` classes — no new OCR or extraction code is written:

```python
class DocumentIngestionAgent:
    def __init__(self, config_path: str = "config.yaml"):
        self.loader = DocumentLoader.from_config(config_path)    # existing
        self.ocr = ScannedPDFOCR.from_config(config_path)        # existing

    async def ingest(self, documents_dir: str) -> list[DocumentInsight]:
        raw_text = self.loader.load_all()    # handles pdf/docx/md/txt; OCR if sparse
        # LLM pass: extract structured DocumentInsight list from raw_text
        ...
```

Supported file types: `.pdf` (text-layer or scanned → OCR via Claude Haiku), `.docx`, `.md`, `.txt`.
Guardrails: file size cap 10 MB, total text cap 50 000 chars, read-only (no writes).

---

### API Endpoint

```
POST /api/real-estate-research
Body: {
  "address":       "123 Main St",          # optional — city+state is minimum
  "city":          "Austin",
  "state":         "TX",
  "zip":           "78701",                 # optional — improves ZIP-level lookups
  "depth":         "full",                  # "quick" | "full"
  "documents_dir": "data/realestate/docs/", # optional — folder of PDFs/MDs to ingest
  "export_to_tolaria": false
}
Response: RealEstateBrief
```

Response time: ~10s (quick), ~45–90s (full). Runs synchronously (same pattern as `/api/interview-prep`).

On `export_to_tolaria=true`, the brief is written to the Tolaria vault at:
`<vault_folder>/realestate/<city>-<state>-<date>.md`

---

### Migration Prediction Model — Tiered Feature Schema

The migration analyst uses a tiered feature architecture. Tier 1 features go into every run (quick and full). Tier 2 features require `depth="full"`. Tier 3 features are opportunistic — used when the specific data is available.

Empirically, wage and home price differentials dominate with taxes, climate, and amenities clearly secondary but still material. If you had to ship a minimal model, Tier 1 + lagged migration would already capture the majority of the signal.

#### Tier 1 — Core drivers (every run)

| Feature | Description | Source |
|---------|-------------|--------|
| `net_migration_rate` | (in-migrants − out-migrants) per 1,000 residents | IRS SOI county migration tables |
| `net_migration_rate_lag1/lag2` | 1- and 2-year lags; path dependence is strong | IRS SOI |
| `irs_net_exemptions` | Net change in tax exemptions filed — direct count of movers | IRS SOI |
| `uhaul_net_inbound_index` | Normalized one-way rental in-minus-out (state + metro) | U-Haul Growth Index (annual) |
| `employment_growth` | % change in total nonfarm employment YoY | BLS CES/QCEW by metro/state |
| `unemployment_rate` + `_change` | Annual average + YoY change | BLS LAUS |
| `avg_weekly_wage` + `real_wage` | Nominal and CPI-adjusted median weekly wage | BLS QCEW + BEA RPP |
| `wage_diff_dest_minus_origin` | Wage gap between destination and origin (OD model) | BLS |
| `median_home_price` + `_yoy` | Median sale price + annual appreciation | Zillow ZHVI / Redfin |
| `home_price_to_income` | Median price ÷ median household income | Zillow + ACS |
| `median_rent` + `_yoy` | Median contract rent + growth | Zillow ZORI / ACS |
| `rent_to_income` | Median rent ÷ median income | Zillow + ACS |
| `regional_price_parity` | Overall cost-of-living index (100 = national average) | BEA Regional Price Parities |
| `state_income_tax_top_rate` | Top marginal personal income tax | Tax Foundation static table |
| `avg_january_temp` | Average January temperature (°F) — strongest single climate predictor | NOAA GHCND |
| `population_growth_pct_yoy` | Annual population growth rate | Census PEP |

#### Tier 2 — Strong but context-dependent (depth=full)

| Feature | Description | Source |
|---------|-------------|--------|
| `rental_vacancy_rate` / `homeowner_vacancy_rate` | Housing tightness | Census HVS + HUD |
| `building_permits_per_capita` | Residential units permitted per 1k residents | Census Building Permits API |
| `housing_inventory_months_supply` | For-sale inventory tightness | Redfin Data Center |
| `state_sales_tax_rate` + `property_tax_rate_effective` | Combined tax burden | Tax Foundation |
| `violent_crime_rate` + `property_crime_rate` | Per 100k; crime enters negative in migration regressions | FBI NIBRS/UCR |
| `crime_trend_3yr` | 3-year trajectory — perception of worsening/improving | FBI NIBRS |
| `university_count` + `research_university_presence` | University presence drives young-adult in-migration | IPEDS |
| `k12_test_score_index` | School quality composite | NCES/state databases |
| `share_age_20_34` / `share_65_plus` | Age structure affects net migration direction | Census ACS |
| `share_college_educated` | Higher share → more mobile population + amenity creation | Census ACS |
| `pm25_level` + `ozone_days_unhealthy` | Air quality indicators | EPA AQS API |
| `walkability_score` + `transit_score` | Lifestyle desirability | Walk Score API |
| `broadband_coverage_pct` | Critical for remote workers post-2020 | FCC National Broadband Map |
| `governor_party` (state) | Party control correlates with migration patterns in cross-section studies | Manual / Ballotpedia |
| `avg_commute_time` | Long commutes are a push factor | Census ACS |

#### Tier 3 — Incremental / high-frequency (opportunistic)

| Feature | Description | Source |
|---------|-------------|--------|
| `usps_net_coa` | USPS Change-of-Address net (ZIP-level, monthly) | USPS COA summary |
| `school_enrollment_change` | YoY K-12 enrollment — sensitive early family out-migration signal | NCES / state DOE |
| `business_license_net_change` | Net small-business openings; follows population | Local gov data / IRS business apps |
| `utility_net_connections` | New vs closed electric/gas accounts | Utility companies / EIA |
| `natural_disaster_index` | FEMA disaster declarations per 5 years | OpenFEMA API |
| `zoning_restrictiveness_index` | Supply elasticity proxy; restrictive = prices up, population growth down | WRLURI / local |
| `major_employer_openings_count` | Anchor employer events (factory/HQ siting) | News / document ingestion |
| `mobile_device_net_home_change` | Device "home" location shifts (commercial provider) | Placer.ai / Safegraph |

---

### Climate & Flood Risk Analysis (Property-Level + Metro)

`HousingAnalystAgent` fetches climate and extreme-weather risk at **two scopes**:
1. **Property-level** (requires address + geocoding): precise flood zone, wildfire risk score
2. **Metro/county-level**: historical disaster frequency, air quality, storm event counts

#### Flood Risk Data Sources

| Source | Scope | Auth | What it provides |
|--------|-------|------|-----------------|
| FEMA NFHL (National Flood Hazard Layer) | Address → flood zone | None (ArcGIS REST) | Flood zone designation (A/AE/X/etc.), BFE, FIRM panel ID |
| First Street Foundation Flood Factor | Property | Free API key (research tier) | 1–10 flood risk score, 30-year risk projection, historical floods |
| FEMA OpenFEMA Disaster Declarations | County + state | None | Count of FEMA disaster declarations; type (flood, hurricane, wildfire) |
| NOAA Storm Events Database | County | None (CDO API) | Historical storm events: count, type, damage $ per county |
| NOAA Climate Data Online | Metro/station | Free API key | Temperature normals, precipitation, extreme event frequency |

#### Wildfire Risk

| Source | Scope | Auth | What it provides |
|--------|-------|------|-----------------|
| USDA Forest Service SILVIS Wildfire Risk | County | None (static download) | Wildfire hazard potential score |
| CAL FIRE / state fire agencies | State | None | Historical burn area, fire perimeters |
| First Street Foundation Fire Factor | Property | Free API key | 1–10 fire risk score |

#### Hurricane / Wind Risk

| Source | Scope | Auth | What it provides |
|--------|-------|------|-----------------|
| NOAA Historical Hurricane Tracks | County + state | None | Track proximity, category, frequency |
| FEMA National Risk Index | County | None (REST API) | Composite natural hazard risk scores: flood, wind, earthquake, wildfire |

#### Implementation Detail

```
Address → Census Geocoder → lat/lon + FIPS county
    ↓
[Flood Zone]    FEMA NFHL ArcGIS REST (lat/lon query) → zone designation + BFE
[Flood Score]   First Street API (if key set)          → 1-10 score + 30yr projection
[Disaster Hist] OpenFEMA API (county FIPS)             → declaration count by type, last 10 yrs
[Storm Events]  NOAA CDO API (county FIPS)             → storm count, damage $, types
[Wildfire]      FEMA National Risk Index (county FIPS) → wildfire risk score + expected annual loss
[Hurricane]     FEMA National Risk Index               → hurricane risk score
[Air Quality]   EPA AQS API (CBSA code)               → annual PM2.5, AQI median
```

Config additions for climate/flood:
```yaml
real_estate_research:
  data_sources:
    first_street_api_key: ""      # firststreet.org — free research tier
    noaa_cdo_token: ""            # ncdc.noaa.gov/cdo-web — free
    walk_score_api_key: ""        # walkscore.com — 1k req/day free
```

`ClimateRiskSnapshot` schema (added to `schemas/realestate.py`):

```python
class FloodRiskDetail(BaseModel):
    fema_flood_zone: str | None              # "X", "AE", "A", "VE", etc.
    fema_zone_description: str | None        # plain English
    base_flood_elevation_ft: float | None    # BFE in feet above NAVD88
    first_street_flood_factor: int | None    # 1–10; 10 = extreme
    first_street_30yr_risk_pct: float | None # probability of flooding in 30 years
    fema_disaster_flood_count: int | None    # # of FEMA flood declarations (last 10yr, county)

class ClimateRiskSnapshot(BaseModel):
    # Flood
    flood: FloodRiskDetail
    flood_risk_overall: Literal["minimal", "low", "moderate", "high", "very_high"]

    # Wildfire
    wildfire_risk_score: float | None        # FEMA NRI expected annual loss (normalized)
    wildfire_risk_label: Literal["minimal", "low", "moderate", "high", "very_high"] | None
    wildfire_burn_history_years: int | None  # years with fire within 50 miles

    # Hurricane / wind
    hurricane_risk_score: float | None       # FEMA NRI
    hurricane_risk_label: Literal["minimal", "low", "moderate", "high", "very_high"] | None

    # General extreme weather
    fema_total_disaster_declarations_10yr: int | None  # all types, county level
    noaa_storm_events_annual_avg: float | None          # avg storm events/year (county)
    noaa_storm_damage_annual_avg_usd: float | None      # avg annual property damage (county)

    # Climate
    avg_jan_temp_f: float | None
    avg_july_temp_f: float | None
    annual_precipitation_inches: float | None
    extreme_heat_days_per_year: float | None  # days > 95°F

    # Air quality
    pm25_annual_avg: float | None
    aqi_median: float | None

    summary: str   # 2–3 sentences: top risks + trend
```

---

### Connection to Existing Infrastructure

| Existing component | How Real Estate uses it |
|-------------------|------------------------|
| `DocumentLoader` + `ScannedPDFOCR` | Node 1 document ingestion — zero new OCR code |
| `LLMClient.from_config()` | Synthesizer LLM calls (Node 5); Document insight extraction (Node 1) |
| `TolariaClient` | Optional vault export of `RealEstateBrief` |
| `config.yaml` `ocr:` section | Already configured; `DocumentIngestionAgent` reads it directly |
| `PromptBudget` pattern | Used in synthesizer when document text is large |

---

## 10. Build Sequence

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

### Phase 6 — Interview Research ✅ Complete

**Pipeline + agents ✅**
- `schemas/interview.py` — `InterviewPipelineInput`, `FitVerdict`, `CompanyProfile`, `QuestionSet`, `STARAnswer`, `AnswerSet`, `TailoredResume`, `InterviewPrepBrief`
- `agents/interview/job_fit_analyzer.py` — LLM: 80/20 gap analysis → `FitVerdict`
- `agents/interview/company_researcher.py` — two-tier: live Brave Search (if key) → LLM synthesis; `MCPClient`-aware
- `agents/interview/question_generator.py` — LLM: gap-weighted question set
- `agents/interview/answer_generator.py` — LLM: STAR answers with `PromptBudget`
- `agents/interview/profile_builder.py` — LLM: parse + merge resumes into `MasterProfile`
- `agents/interview/resume_writer.py` — LLM: Node 5; rewrites profile as JD-targeted resume; never fabricates experience; transparency log via `tailoring_notes`
- `pipelines/interview_pipeline.py` — `InterviewPipeline.from_config()`, **5-node chain**, MCPClient-aware, auto-logs on completion

**Live web research ✅**
- `agents/mcp_client.py` — `MCPClient` wrapper; direct Brave Search API + HTTP fetch; graceful fallback when no key
- `config.yaml` `mcp:` section — `brave_search_key`, Tolaria config; upgrade path to MCP stdio transport in Phase 7

**Persistence layer ✅**
- `schemas/profile.py`, `schemas/tracker.py`, `schemas/skills.py`
- `store/profile_store.py` — atomic write, `from_config()`
- `store/application_store.py` — dedup by company+role, writes `.json` + `.md`; `insights()` method for pattern analytics
- `store/skills_store.py` — full SM-2 implementation with `add_questions()` / `record_review()`

**API endpoints ✅**
- `POST /api/interview-prep` — loads profile from store if omitted; exports to Tolaria if `export_to_tolaria=true`
- `POST /api/profile/add-resume`, `GET /api/profile`, `DELETE /api/profile`
- `GET /api/tracker`, `POST /api/tracker/update`
- `GET /api/tracker/insights` — pure analytics: win rate, funnel, failure stage, fit correlation, action items
- `GET /api/learn/due`, `POST /api/learn/review`, `GET /api/learn/stats`

**Tolaria vault integration ✅**
- `integrations/tolaria.py` — `TolariaClient` writes Markdown notes to Tolaria / Obsidian Local REST API vault
- `render_interview_brief()`, `render_stock_brief()` — Pydantic → Markdown renderers
- Auto-exports brief + tailored resume on `POST /api/interview-prep` when `export_to_tolaria=true`
- Auto-exports stock brief on `POST /api/stock-research` when `export_to_tolaria=true`
- Falls back to local `output/` directory if Tolaria is unavailable

**Pending (Phase 5 bundle)**
- `InterviewPrep.tsx` Chrome extension component — pending

### Phase 6 Extension — Equibles Financial Data Integration ✅ Complete

- `.mcp.json` — `equibles` SSE entry added (`localhost:8081/sse`)
- `config.yaml` — `mcp.equibles` section with `enabled`, `server_url`, and ticker-filter option
- `schemas/stock.py` — added `InstitutionalSnapshot`, `InstitutionalHolder`, `MarketStructureData`, `InsiderTransaction`, `TechnicalIndicators`; `ResearchBrief` gains three optional fields: `institutional`, `market_structure`, `technicals`
- `agents/mcp_client.py` — extended with `equibles_url` parameter; `_equibles_call()` MCP JSON-RPC transport; five named helper methods: `equibles_institutional_holders()`, `equibles_short_interest()`, `equibles_insider_transactions()`, `equibles_congressional_trades()`, `equibles_technical_indicators()`, `equibles_search_sec_filings()`
- `agents/stock/data_fetcher.py` — `mcp` parameter added; `fetch()` calls Equibles for institutional, market structure, and technical data at `depth=full` when Equibles is available
- `agents/stock/news_aggregator.py` — `mcp` parameter added; `fetch()` calls Equibles for SEC full-text excerpts (3 targeted queries: risk factors, guidance, MD&A) and Form 3/4 insider transactions
- `agents/stock/research_synthesizer.py` — `synthesize()` accepts `institutional_raw`, `market_structure_raw`, `technicals_raw`; injects all Equibles data into LLM prompt with structured formatting; parses raw dicts into typed schema objects via `_parse_institutional()`, `_parse_market_structure()`, `_parse_technicals()`
- `pipelines/stock_pipeline.py` — `MCPClient.from_config()` instantiated; passed to both `DataFetcherAgent` and `NewsAggregatorAgent`; Equibles data threaded from Node 1 through to Node 5

All Equibles calls are gated behind `mcp.is_available("equibles")` — the pipeline always completes without Equibles running.

### Phase 7 — MCP Server ✅ Complete

- `mcp_server.py` — stdio MCP server exposing all four pipelines as native tools:
  - `run_stock_research(ticker, depth?)` → `ResearchBrief` JSON
  - `run_board_session(mode?, context?, raw_paste?)` → `BoardBriefing` JSON
  - `run_interview_prep(jd_text, company_name, role_title, profile_text?, depth?)` → `InterviewPrepBrief` JSON
  - `run_real_estate_research(city, state, address?, depth?, bedrooms?, purchase_price?, ...)` → `RealEstateBrief` JSON
- Pipelines initialised lazily on first call — process starts instantly
- All logs routed to stderr; stdout reserved for MCP stdio transport
- `mcp>=1.0.0` added to `pyproject.toml`
- `.mcp.json` `openresearch` entry updated with full tool documentation
- Registered: Claude Code / Claude Desktop can call research pipelines as native tools without HTTP

### Phase 8 — Real Estate Research ✅ Complete

**Schemas ✅**
- `schemas/realestate.py` — `RealEstatePipelineInput`, `GeoResolution`, `MigrationSignal`, `MigrationSnapshot`, `LaborMarketSnapshot`, `HousingMarketSnapshot`, `CostOfLivingSnapshot`, `DemandFactorsSnapshot`, `ClimateRiskSnapshot`, `FloodRiskDetail`, `RentalUnderwritingSnapshot`, `RegulatoryRiskSnapshot`, `NeighborhoodSnapshot`, `RentalAnalysis`, `DocumentInsight`, `DocumentFactsBundle`, `RealEstateBrief` — plus 9 document-type extract schemas (appraisal, inspection, HOA, tax record, lease, flood cert, listing, CMA, zoning)

**Pipeline + agents ✅**
- `agents/realestate/_geo.py` — Census Geocoder → FIPS + CBSA + lat/lon; lookup-table fallback
- `agents/realestate/document_ingestion.py` — wraps `DocumentLoader` + `ScannedPDFOCR`; LLM classifies + extracts type-specific facts; produces `DocumentInsight` list + `DocumentFactsBundle`
- `agents/realestate/migration_analyst.py` — IRS SOI bulk CSV; Census ACS API; U-Haul index; FRED population series; produces city + state `MigrationSnapshot`
- `agents/realestate/economic_analyst.py` — BLS CES/LAUS/OES/QCEW/JOLTS; BEA RPP; static state tax table; FRED wage series; produces `LaborMarketSnapshot` + `CostOfLivingSnapshot`
- `agents/realestate/housing_analyst.py` — Zillow Research CSV cache; Redfin Data Center CSV cache; Census Building Permits API; HUD API; FBI NIBRS API; EPA AQS API; FEMA NFHL; Walk Score API; produces `HousingMarketSnapshot` + `DemandFactorsSnapshot`
- `agents/realestate/rental_underwriter.py` — no LLM; arithmetic model: rent estimates (RentCast / HUD FMR / ZORI), expenses (tax, insurance, NFIP, vacancy, mgmt, maintenance, CapEx), NOI, cap rate, CoC return, DSCR, break-even occupancy
- `agents/realestate/regulatory_analyst.py` — static 50-state table: eviction timeline, rent control exposure, STR rules, insurance market stress; `RegulatoryRiskSnapshot`
- `agents/realestate/neighborhood_analyst.py` — ACS tract demographics, Walk Score, HUD USPS vacancy, GreatSchools; `NeighborhoodSnapshot`
- `agents/realestate/rental_synthesizer.py` — LLM: synthesises underwriting + regulatory + neighborhood into `RentalAnalysis` with feasibility verdict, quantified pros/cons, and due-diligence checklist
- `agents/realestate/synthesizer.py` — LLM: Pareto framing of top 3–5 push/pull factors; city-vs-state divergence commentary; data gap flagging; produces `RealEstateBrief`
- `pipelines/realestate_pipeline.py` — `RealEstatePipeline.from_config()`; 7-node chain; `depth` gates; rental nodes triggered automatically when property details provided

**API endpoint ✅**
- `POST /api/real-estate-research` — synchronous; loads `documents_dir` when provided; exports to Tolaria if `export_to_tolaria=true`; registered in `server.py` with `_realestate_pipeline` singleton

**Config additions ✅**
```yaml
real_estate_research:
  data_sources:
    fred_api_key: ""          # api.stlouisfed.org — free
    census_api_key: ""        # api.census.gov — free
    bea_api_key: ""           # apps.bea.gov — free
    walk_score_api_key: ""    # api.walkscore.com — 1k req/day free
    epa_api_key: ""           # aqs.epa.gov — free
  zillow_cache_dir: "data/realestate/zillow/"    # pre-downloaded Zillow CSVs
  redfin_cache_dir: "data/realestate/redfin/"   # pre-downloaded Redfin CSVs
  irs_cache_dir: "data/realestate/irs/"         # pre-downloaded IRS SOI bulk files
  documents_dir: "data/realestate/docs/"        # default folder for document ingestion
  data_dir: "data/realestate/"
```

---

## 11. Open Questions — Status

| # | Question                                                                              | Status                                                                                                                                                                                                       |
|---|---------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| 1 | **Org mapping**: How are VP teams identified in Jira/Linear?                          | **Resolved** — by project key (`jira_project_keys`) or team key (`linear_team_keys`) configured in `config.yaml`. The `OrgNormalizerAgent` uses these to group issues by team.                               |
| 2 | **Board member personas**: Generic roles or actual VP names?                          | **Resolved as generic** — personas use role titles (Chief of Staff, VP Engineering, etc.). Actual names can be injected via `raw_paste` or `context` if needed.                                              |
| 3 | **Stock research depth**: Should "Quick" mode skip EDGAR?                             | **Resolved** — `depth="quick"` skips Alpha Vantage, Polygon.io, and SEC EDGAR. Only yfinance + NewsAPI run.                                                                                                  |
| 4 | **Decision Advisory debate**: Sequential or parallel?                                 | **Resolved as parallel** — all board members respond to the proposal simultaneously from their lens. CoS then synthesizes the debate. Sequential mode available via `parallel_execution: false`.             |
| 5 | **FastAPI server access model**: Always-on or on-demand?                              | **Open** — currently launched manually with `python server.py`. Always-on service setup (Windows nssm / macOS launchd) documented in SETUP.md but not automated.                                             |
| 6 | **MCP server transport**: stdio vs SSE?                                               | **Resolved** — `stdio` implemented in `mcp_server.py`. The `openresearch` entry in `.mcp.json` uses `"command": "python", "args": ["mcp_server.py"]`. SSE can be added later for Chrome extension use; the `Server` object is transport-agnostic. |
| 7 | **Tailored resume output**: Should the interview pipeline write a JD-targeted resume? | **Resolved** — `ResumeWriterAgent` (Node 5) added to interview pipeline. Takes `MasterProfile` + `FitVerdict` + JD, rewrites as targeted resume. Runs on `depth="full"`. Includes `tailoring_notes` transparency log. Output: `TailoredResume` in `InterviewPrepBrief`. |
| 8 | **Company research quality**: LLM knowledge vs live web?                              | **Resolved** — `MCPClient` added (`agents/mcp_client.py`). `CompanyResearcherAgent` runs 3 Brave Search queries before LLM call when `mcp.brave_search_key` is set. Falls back to LLM-only when key absent. |
| 9 | **Application pattern analysis**: Who reads `applications.json`?                      | **Resolved** — `ApplicationStore.insights()` added. `GET /api/tracker/insights` surfaces: win rate, stage funnel, most common failure stage, fit score vs outcome correlation, and 5 plain-English action items. No LLM calls. |
| 10 | **Real estate — city boundary definition**: How do we map a city name to county FIPS for IRS/Census lookups? | **Resolved** — `agents/realestate/_geo.py` calls Census Geocoder API → FIPS + CBSA code. Falls back to a static lookup table keyed by city+state. Multiple counties per metro are summed over CBSA. |
| 11 | **Real estate — Zillow/Redfin CSV freshness**: Data files are updated monthly; should the pipeline auto-download on first run? | **Resolved** — `cache_max_age_days: 30` in config; `HousingAnalystAgent` checks file mtime before downloading; fetches latest CSV from Zillow Research / Redfin public URLs when stale or absent. |
| 12 | **Real estate — U-Haul ranking source**: Annual index is published as a press release / web page, not a structured API. | **Resolved** — `MigrationAnalystAgent` scrapes the U-Haul Growth Cities page (lightweight HTML); static top-50 fallback table baked in for offline / quick mode. |
| 13 | **Real estate — IRS SOI migration files**: Bulk ZIP files are ~50 MB per year; should the pipeline cache them locally? | **Resolved** — `irs_cache_dir` config value (default `data/realestate/irs/`); pipeline checks for extracted CSVs before downloading; only county-level migration extract retained (not full file). |
