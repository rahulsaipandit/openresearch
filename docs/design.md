# Design Document: AI Research & Executive Intelligence Platform

**Date:** 2026-05-17  
**Status:** Draft  
**Scope:** Stock Research Tool + Executive Board System

---

## 1. Chosen Foundation: OpenResearch

**Repo:** `https://github.com/charanvadhyar/openresearch`

### Why OpenResearch over the alternatives

| Criterion                   | OpenResearch                          | moedesux/autoresearch-opencode | rootcause + autofix  |
|-----------------------------|---------------------------------------|--------------------------------|----------------------|
| Multi-agent orchestration   | LangGraph (production-grade)          | Single-loop skill              | Two-skill pipeline   |
| Claude API support          | Native (Anthropic SDK)                | Via OpenCode                   | Claude Code CLI only |
| Local LLM support           | OpenAI-compat endpoint in config.yaml | Via OpenCode                   | None                 |
| Report/synthesis pipeline   | Built-in (Paper Writer agent)         | None                           | None                 |
| State & memory              | Redis + ChromaDB                      | JSONL files                    | None                 |
| Maturity                    | Full Python stack, well-structured    | New (May 2026), empty dirs     | Stable but narrow    |
| Adaptability to new domains | High — swap agents per domain         | Low — code-optimization only   | Low — debug/fix only |

**Decision:** OpenResearch's LangGraph pipeline, multi-provider LLM abstraction, and synthesizer-agent pattern map directly onto both the Stock Research Tool and Executive Board. The other projects are either too narrow in scope or too immature.

### What gets kept vs replaced

| OpenResearch Component                      | Action                            | Reason                           |
|---------------------------------------------|-----------------------------------|----------------------------------|
| LangGraph orchestration layer               | **Keep**                          | Core pipeline engine             |
| LLM provider abstraction (config.yaml)      | **Keep**                          | Claude + local LLM support       |
| Pydantic schemas                            | **Keep**                          | Clean data contracts             |
| Redis + ChromaDB                            | **Keep**                          | State persistence, vector memory |
| Report generation (Jinja2 → Markdown)       | **Adapt**                         | Output format changes            |
| Kaggle kernel executor                      | **Remove**                        | Not needed                       |
| ML-specific agents (EDA, Method Formulator) | **Replace**                       | New domain agents instead        |
| Paper Writer agent                          | **Adapt → Board Synthesis agent** | Same pattern, different output   |

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
│              Local FastAPI Server (new — wraps OpenResearch) │
│   POST /api/stock-research     POST /api/board-session       │
│   POST /api/board-health       GET  /api/board-status/:id    │
└──────────────────┬───────────────────┬───────────────────────┘
                   │                   │
     ┌─────────────▼─────┐   ┌─────────▼───────────────────┐
     │  Stock Research   │   │  Executive Board Pipeline   │
     │  Pipeline         │   │                             │
     │  (LangGraph)      │   │  (LangGraph)                │
     └─────────────┬─────┘   └─────────────────────────────┘
                   │
     ┌─────────────▼──────────────────────────────────────┐
     │  LLM Provider (config.yaml)                        │
     │  Claude API  OR  LM Studio / Ollama (local)        │
     │  OpenAI-compatible endpoint                        │
     └────────────────────────────────────────────────────┘
```

### Local API Server

A thin FastAPI wrapper around the OpenResearch pipeline, running at `localhost:7842`. The Chrome extension calls it directly. This avoids CORS issues and keeps the LLM keys off the browser.

```python
# server.py (new file)
POST /api/stock-research      # { ticker, depth, provider }
POST /api/board-session       # { mode, context, data_sources }
POST /api/board-health        # { jira_token, linear_token, notion_token }
GET  /api/board-status/:id    # poll for async board session result
```

---

## 3. Feature 1: Stock Research Tool

### Goal

Given a stock ticker, produce a structured research brief covering fundamentals, news sentiment, and a synthesized analyst-style view with bull/bear framing.

### Pipeline (LangGraph nodes)

```
TickerInput
    ↓
[Node 1] DataFetcher
    - Yahoo Finance (free, no key): price, P/E, EPS, revenue, margins
    - Alpha Vantage (free tier): income statement, balance sheet
    - Polygon.io (if configured): earnings calendar, insider trades
    ↓
[Node 2] NewsAggregator
    - NewsAPI or Google News RSS: last 30 days headlines
    - SEC EDGAR EDGAR API (free): recent 8-K, 10-Q filings summary
    ↓
[Node 3] FundamentalsAnalyst  ← LLM (Claude / local)
    persona: "You are a buy-side fundamental analyst..."
    output: ValuationSummary { fair_value_range, key_metrics, moat_assessment }
    ↓
[Node 4] SentimentAnalyst  ← LLM (Claude / local)
    persona: "You are a news-driven equity researcher..."
    output: SentimentSummary { tone, catalysts, risks, analyst_consensus }
    ↓
[Node 5] ResearchSynthesizer  ← LLM (Claude / local)
    persona: "You are a senior equity strategist writing a one-page brief..."
    output: ResearchBrief (see schema below)
    ↓
Output → Chrome Extension
```

### Output Schema

```python
class ResearchBrief(BaseModel):
    ticker: str
    company_name: str
    as_of_date: str
    verdict: Literal["Strong Buy", "Buy", "Hold", "Sell", "Strong Sell"]
    price_target_low: float
    price_target_high: float
    summary: str                   # 2-3 sentence executive summary
    bull_case: list[str]           # 3-5 bullet points
    bear_case: list[str]           # 3-5 bullet points
    key_risks: list[str]
    upcoming_catalysts: list[str]  # earnings date, product launches, etc.
    fundamentals: ValuationSummary
    sentiment: SentimentSummary
    sources: list[str]             # URLs used
```

### Data Sources & Keys

| Source                   | Auth    | Free Tier   |
|--------------------------|---------|-------------|
| Yahoo Finance (yfinance) | None    | Unlimited   |
| Alpha Vantage            | API key | 25 req/day  |
| Polygon.io               | API key | 5 req/min   |
| NewsAPI                  | API key | 100 req/day |
| SEC EDGAR                | None    | Unlimited   |

Keys stored in `config.yaml` (same pattern as existing OpenResearch providers).

### Chrome Extension Component

Extends existing `FinancialMonitor.tsx` pattern. New component `StockResearch.tsx`:

- Ticker input + "Research" button
- Depth selector: Quick (news + price) / Full (all nodes)
- Progress indicator showing which pipeline node is running
- Output: rendered `ResearchBrief` with color-coded verdict badge
- Cache: store result in Chrome storage with 4-hour TTL

---

## 4. Feature 2: Executive Board

### Goal

A simulated boardroom of AI agents — each with a distinct executive lens — that collectively analyzes org health across 10 VPs / 200 people, debates decisions, produces weekly briefings, and surfaces cross-team conflicts.

### Board Members

| Agent ID         | Role           | Analytical Lens                                               |
|------------------|----------------|---------------------------------------------------------------|
| `chief_of_staff` | Chief of Staff | Org health, CEO-level narrative, cross-cutting blockers       |
| `vp_engineering` | VP Engineering | Sprint velocity, technical debt, delivery risk, capacity      |
| `vp_product`     | VP Product     | Roadmap alignment, OKR progress, feature prioritization       |
| `vp_people`      | VP People / HR | Team morale signals, hiring gaps, attrition risk, performance |
| `cto`            | CTO            | Technical strategy, platform risks, architecture decisions    |
| `cfo_proxy`      | Finance Proxy  | Budget burn rate, project ROI, resource allocation            |

Each agent runs as a separate LangGraph node with its own system prompt persona and output schema. All agents receive the same normalized `OrgSnapshot` as input.

### Pipeline (LangGraph nodes)

```
DataIngestion (Jira / Linear / Notion / manual paste)
    ↓
[Node 1] OrgNormalizer
    - Normalize to OrgSnapshot schema
    - Deduplicate, resolve team → VP mapping
    ↓
[Node 2..7] Board Member Agents (parallel fan-out)
    Each receives: OrgSnapshot + session_mode
    Each outputs: BoardMemberView { findings, risks, recommendations, questions }
    ↓
[Node 8] ConflictDetector  ← LLM
    - Finds cross-agent disagreements, resource contention, timeline clashes
    - Identifies what VP Engineering said vs what VP Product needs
    ↓
[Node 9] ChiefOfStaffSynthesis  ← LLM
    - Reads all BoardMemberView outputs + ConflictReport
    - Produces the final BoardBriefing
    ↓
Output → Chrome Extension
```

### Session Modes

**Weekly Review** — digest all project/team data, produce briefing + action items  
**Decision Advisory** — user poses a proposal; each board member responds from their lens; CoS synthesizes the debate into a recommendation  
**Health Scan** — focused conflict + risk detection pass; faster (skips full briefing)

### Core Schemas

```python
class OrgSnapshot(BaseModel):
    snapshot_date: str
    teams: list[TeamStatus]        # one per VP
    org_metrics: OrgMetrics        # overall velocity, headcount, budget
    active_initiatives: list[Initiative]
    open_risks: list[Risk]
    decisions_pending: list[Decision]

class TeamStatus(BaseModel):
    vp_name: str
    team_name: str
    headcount: int
    active_projects: list[Project]
    blockers: list[str]
    morale_signal: Literal["green", "yellow", "red"] | None
    budget_status: Literal["on_track", "at_risk", "over"] | None

class BoardMemberView(BaseModel):
    agent_id: str
    role: str
    key_findings: list[str]        # top 3-5 observations
    risks: list[Risk]
    recommendations: list[str]
    questions_for_ceo: list[str]   # escalations
    confidence: float              # 0-1, self-reported

class BoardBriefing(BaseModel):
    session_date: str
    mode: Literal["weekly_review", "decision_advisory", "health_scan"]
    executive_summary: str         # 3-5 sentences for CEO
    org_health_score: float        # 0-10
    red_flags: list[str]           # requires immediate attention
    cross_team_conflicts: list[Conflict]
    top_priorities: list[str]      # ranked
    action_items: list[ActionItem] # owner, due_date, description
    board_member_views: list[BoardMemberView]
    decisions_recommended: list[Decision]
```

### Data Integrations

#### Jira
```python
# Fetch epics, stories, blockers per team
GET /rest/api/3/search?jql=project={key}&fields=summary,status,assignee,priority,blockers
```
Maps to: `TeamStatus.active_projects`, `TeamStatus.blockers`

#### Linear
```python
# Fetch issues, cycles, projects per team
GET /graphql → issues(filter: { team: { key: { eq: "{key}" } } })
```
Maps to: `TeamStatus.active_projects`, velocity via cycle metrics

#### Notion
```python
# Fetch database pages (status trackers, OKR docs, risk registers)
POST /v1/databases/{id}/query
```
Maps to: `OrgSnapshot.active_initiatives`, `OrgSnapshot.open_risks`

All three integrations are optional. If none configured, the ingestion step accepts a JSON/Markdown paste as fallback (same UX as current `ExecutiveReviewPrep`).

### Chrome Extension Component

New component `ExecutiveBoard.tsx`:

- **Data tab**: configure Jira/Linear/Notion tokens + manual paste fallback
- **Session tab**: choose mode (Weekly Review / Decision Advisory / Health Scan), add decision proposal text if advisory mode
- **Board tab**: live progress showing each board member "thinking" then "done"
- **Briefing tab**: rendered `BoardBriefing` — red flags highlighted, action items with owners, board member cards expandable

---

## 5. LLM Configuration

Both pipelines share a single `config.yaml`:

```yaml
llm:
  provider_chain:
    - provider: anthropic
      model: claude-sonnet-4-6
      api_key: ${ANTHROPIC_API_KEY}
    - provider: openai_compatible   # local LLM fallback
      base_url: http://localhost:1234/v1
      model: qwen3-27b              # or any model in LM Studio / Ollama
      api_key: lm-studio            # placeholder, not validated

stock_research:
  data_sources:
    yahoo_finance: true
    alpha_vantage_key: ${ALPHA_VANTAGE_KEY}
    polygon_key: ${POLYGON_KEY}
    news_api_key: ${NEWS_API_KEY}
  cache_ttl_hours: 4

executive_board:
  board_members: [chief_of_staff, vp_engineering, vp_product, vp_people, cto, cfo_proxy]
  parallel_execution: true
  max_retries: 2
  integrations:
    jira:
      base_url: ${JIRA_BASE_URL}
      api_token: ${JIRA_API_TOKEN}
      email: ${JIRA_EMAIL}
    linear:
      api_key: ${LINEAR_API_KEY}
    notion:
      api_key: ${NOTION_API_KEY}
      database_ids: []              # user populates via settings UI
```

For local LLM: point LM Studio or Ollama to `localhost:1234` (LM Studio default) and set `model` to the loaded model name. The provider chain falls back automatically if the first provider fails.

---

## 6. File Structure (additions to OpenResearch)

```
openresearch/
├── agents/
│   ├── stock/
│   │   ├── data_fetcher.py         # new
│   │   ├── news_aggregator.py      # new
│   │   ├── fundamentals_analyst.py # new
│   │   ├── sentiment_analyst.py    # new
│   │   └── research_synthesizer.py # new
│   └── board/
│       ├── org_normalizer.py       # new
│       ├── chief_of_staff.py       # new
│       ├── vp_engineering.py       # new
│       ├── vp_product.py           # new
│       ├── vp_people.py            # new
│       ├── cto.py                  # new
│       ├── cfo_proxy.py            # new
│       ├── conflict_detector.py    # new
│       └── cos_synthesis.py        # new
├── pipelines/
│   ├── stock_pipeline.py           # new LangGraph graph
│   └── board_pipeline.py           # new LangGraph graph
├── integrations/
│   ├── jira.py                     # new
│   ├── linear.py                   # new
│   └── notion.py                   # new
├── schemas/
│   ├── stock.py                    # new (ResearchBrief etc.)
│   └── board.py                    # new (OrgSnapshot, BoardBriefing etc.)
├── server.py                       # new FastAPI wrapper
└── config.yaml                     # modified (add stock + board sections)
```

---

## 7. Build Sequence

### Phase 1 — Foundation (Week 1)
- Fork OpenResearch, strip Kaggle executor and ML-specific agents
- Add FastAPI server skeleton with `/api/stock-research` and `/api/board-session` endpoints
- Implement LLM provider config (Claude + local LLM fallback)
- Verify end-to-end call from Chrome extension to local server

### Phase 2 — Stock Research (Week 2)
- Implement `DataFetcher` (yfinance + Alpha Vantage)
- Implement `NewsAggregator` (NewsAPI + SEC EDGAR)
- Implement analyst agents + `ResearchSynthesizer`
- Wire LangGraph pipeline
- Build `StockResearch.tsx` in Chrome extension

### Phase 3 — Executive Board Core (Week 3)
- Define all Pydantic schemas (`OrgSnapshot`, `BoardBriefing`)
- Implement all 6 board member agents with persona prompts
- Implement `ConflictDetector` and `ChiefOfStaffSynthesis`
- Wire LangGraph pipeline with parallel fan-out
- Build `ExecutiveBoard.tsx` with manual paste input

### Phase 4 — Integrations (Week 4)
- Jira integration (fetch epics/issues/blockers by team)
- Linear integration (issues + cycle metrics)
- Notion integration (database query for OKR/risk pages)
- Settings UI in Chrome extension for tokens + Notion DB IDs

---

## 8. Open Questions

1. **Org mapping**: How are the 10 VP teams identified in Jira/Linear? By project key, label, or team ID? This determines the normalization logic.
2. **Board member personas**: Should board member prompts reference the actual VP names in the org, or stay generic roles?
3. **Stock research depth**: Should "Quick" mode skip the EDGAR filing fetch (adds latency) and use only Yahoo + NewsAPI?
4. **Decision Advisory**: When a proposal is submitted, should the board members respond in sequence (simulating a debate) or in parallel (faster, less interactive)?
5. **Access model**: Is the local FastAPI server always-on, or started on demand when the extension needs it?
