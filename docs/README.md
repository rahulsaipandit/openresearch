# OpenResearch — AI Research & Executive Intelligence Platform

OpenResearch is a local AI platform with two capabilities:

1. **Stock Research Tool** — given a ticker, produces a structured analyst-style research brief with fundamentals, news sentiment, bull/bear cases, and a price target range.
2. **Executive Board** — a simulated boardroom of AI agents (Chief of Staff, VP Engineering, VP Product, VP People, CTO, Finance Proxy) that collectively analyzes your organization, surfaces cross-team conflicts, and produces weekly briefings or decision recommendations.

Both pipelines run locally via a FastAPI server at `localhost:7842`. A Chrome extension can call them directly. All LLM keys stay on your machine.

---

## Architecture

```
Chrome Extension (or any HTTP client)
        │  HTTP  localhost:7842
        ▼
  FastAPI Server  (server.py)
    ├── POST /api/stock-research    ──→  Stock Research Pipeline
    └── POST /api/board-session     ──→  Executive Board Pipeline
                                              │
                                    LLM Provider (config.yaml)
                                    Claude API  |  Local LLM (LM Studio / Ollama)
```

### Stock Research Pipeline

```
[1] DataFetcher       — Yahoo Finance (free), Alpha Vantage, Polygon.io
[2] NewsAggregator    — NewsAPI, SEC EDGAR filings
[3] FundamentalsAnalyst  (LLM) — valuation, moat, key metrics
[4] SentimentAnalyst     (LLM) — news tone, catalysts, risks
[5] ResearchSynthesizer  (LLM) — final ResearchBrief with verdict + price target
```

### Executive Board Pipeline

```
[1] OrgNormalizer     — normalize Jira / Linear / Notion / Slack / docs / paste → OrgSnapshot
[2] Board Agents (parallel):
      ChiefOfStaff · VPEngineering · VPProduct · VPPeople · CTO · CFOProxy
[3] ConflictDetector  (LLM) — cross-team disagreements, resource contention
[4] CoSSynthesis      (LLM) — final BoardBriefing for CEO
```

---

## Data Sources

### Stock Research

| Source | Auth | Free Tier | What it provides |
|---|---|---|---|
| Yahoo Finance (yfinance) | None | Unlimited | Price, P/E, EPS, margins, 52w range |
| Alpha Vantage | API key | 25 req/day | Income statement, balance sheet |
| Polygon.io | API key | 5 req/min | Earnings calendar, insider data |
| NewsAPI | API key | 100 req/day | Last 30 days headlines |
| SEC EDGAR | None | Unlimited | 8-K, 10-Q, 10-K filings |

### Executive Board

| Source | Auth | What it provides |
|---|---|---|
| Jira | Email + API token | Epics, stories, blockers by project |
| Linear | API key | Issues, cycle velocity by team |
| Notion | Integration token + DB IDs | OKRs, risk registers, status trackers |
| Slack | Bot token (read-only scopes) | Stand-up messages, blockers, team health signals |
| Word / PDF / text files | File path | Meeting notes, strategy docs, status reports |
| Manual paste | — | Plain text or JSON fallback |

---

## Output Schemas

### ResearchBrief

```python
ticker, company_name, as_of_date
verdict: "Strong Buy" | "Buy" | "Hold" | "Sell" | "Strong Sell"
price_target_low, price_target_high, current_price
summary                  # 2-3 sentence executive summary
bull_case: list[str]     # 3-5 specific bull points
bear_case: list[str]     # 3-5 specific bear points
key_risks: list[str]
upcoming_catalysts: list[str]
fundamentals: ValuationSummary
sentiment: SentimentSummary
sources: list[str]
```

### BoardBriefing

```python
session_date, mode
executive_summary        # 3-5 sentences for CEO
org_health_score         # 0-10
red_flags: list[str]     # requires immediate CEO attention
cross_team_conflicts: list[Conflict]
top_priorities: list[str]
action_items: list[ActionItem]   # owner + due_date + priority
decisions_recommended: list[Decision]
board_member_views: list[BoardMemberView]
```

---

## Board Members

| Agent | Role | Focus |
|---|---|---|
| `chief_of_staff` | Chief of Staff | Org health, CEO narrative, cross-cutting blockers |
| `vp_engineering` | VP Engineering | Sprint velocity, delivery risk, capacity |
| `vp_product` | VP Product | Roadmap alignment, OKR progress, prioritization |
| `vp_people` | VP People | Morale signals, attrition risk, hiring gaps |
| `cto` | CTO | Technical strategy, platform risks, architecture |
| `cfo_proxy` | Finance Proxy | Budget burn, project ROI, resource allocation |

---

## Session Modes

| Mode | What it does |
|---|---|
| `weekly_review` | Digest all org data → full briefing + action items |
| `decision_advisory` | User poses a proposal → board debates it → CoS recommendation |
| `health_scan` | Focused conflict + risk pass (faster, skips full briefing) |

---

## LLM Support

Configured via `config.yaml`:

```yaml
llm:
  provider_chain:
    - provider: anthropic
      model: claude-sonnet-4-6
      api_key: "sk-ant-..."

    # Optional local LLM fallback:
    - provider: openai_compatible
      base_url: http://localhost:1234/v1
      model: qwen3-27b
      api_key: lm-studio
```

Supported providers: `anthropic`, `openai`, `minimax`, `openai_compatible` (LM Studio, Ollama, any OpenAI-compatible endpoint).

Providers are tried in order. If the first hits a rate limit, it falls back to the next.

---

## Project Structure

```
openresearch/
├── server.py                    FastAPI server (localhost:7842)
├── config.yaml                  All configuration
├── agents/
│   ├── api_utils.py             LLM client with fallback chain
│   ├── stock/                   5 stock research agents
│   └── board/                   9 executive board agents
├── pipelines/
│   ├── stock_pipeline.py        Stock research orchestration
│   └── board_pipeline.py        Executive board orchestration
├── schemas/
│   ├── stock.py                 ResearchBrief, ValuationSummary, SentimentSummary
│   └── board.py                 OrgSnapshot, BoardBriefing, BoardMemberView, ...
├── integrations/
│   ├── jira.py                  Read-only Jira client
│   ├── linear.py                Read-only Linear GraphQL client
│   ├── notion.py                Read-only Notion database client
│   ├── slack.py                 Read-only Slack client (guardrailed)
│   └── documents.py             .docx / .pdf / .txt / .md loader
└── docs/
    ├── README.md                This file
    ├── SETUP.md                 Step-by-step setup guide
    └── design.md                Architecture design document
```

---

## Read-Only Guardrails

All integrations are read-only by design:

- **Slack**: a hard `_ALLOWED_METHODS` whitelist blocks any non-read API call at the code level — `PermissionError` is raised before the HTTP request is made.
- **Documents**: only `.docx`, `.pdf`, `.txt`, `.md` extensions are accepted; files over the size limit are skipped; total context is capped at 50,000 characters.
- **Jira / Linear / Notion**: only GET / query operations are exposed. No mutation methods exist in any integration class.

---

## API Reference

| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/health` | Liveness check + pipeline status |
| POST | `/api/stock-research` | Run stock research (synchronous) |
| POST | `/api/board-session` | Start board session (async, returns session_id) |
| GET | `/api/board-status/{id}` | Poll board session result |
| POST | `/api/board-health` | Test integration connections |

See [SETUP.md](SETUP.md) for installation and configuration instructions.
