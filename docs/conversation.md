I'll fetch all three repositories in parallel to compare them.

## Agent:Fetch GitHub repo info for openresearch, rootcause, autofix
IN
Fetch the following three GitHub repositories and summarize each one's architecture, tech stack, key features, and how they integrate with LLMs (especially if they support Claude API, OpenAI, or local LLMs). For each repo, read the README, main entry points, and any config/env files you can find.

1. https://github.com/charanvadhyar/openresearch
2. https://github.com/ecstatic-pirate/rootcause
3. https://github.com/ecstatic-pirate/autofix

__For each repo provide__:
- What it does (purpose/goal)
- Tech stack and architecture
- LLM integration approach (which APIs/models, how it calls them)
- Key files and their roles
- Any configuration options
- Obvious strengths and weaknesses from the code structure

Use WebFetch to read the GitHub pages and raw files.
Here's my synthesis for your use case (Claude API or local LLM compatibility):

## Comparison Summary
### 1. OpenResearch (charanvadhyar/openresearch)
Purpose: Autonomous ML research pipeline — EDA → baseline → paper writing

**Pros**:
- Multi-provider LLM support (Anthropic, OpenAI, MiniMax) with fallback chains — Claude API ready out of the box
- Most feature-complete: LangGraph orchestration, Redis, ChromaDB, Optuna, notebook generation
- Provider-agnostic config via config.yaml — swapping to a local LLM (via OpenAI-compatible endpoint) would be straightforward
- Pydantic schemas throughout — clean data contracts between agents

**Cons**:
- Hard Kaggle dependency for code execution — not self-contained
- Heaviest stack by far (Redis, ChromaDB, ydata-profiling, 7 ML libraries)
- 7-agent pipeline is complex to debug or extend
- Most likely to have hidden cloud-provider assumptions

### 2. Rootcause (ecstatic-pirate/rootcause)

Purpose: Claude Code skill — runtime debugging investigation

**Pros**:
Zero external dependencies, pure JS skill file
Strong methodology (9-step, evidence-chain, read-only)
Works natively with Claude via /rootcause slash command

**Cons**:
__Tightly coupled to Claude Code CLI__ — not usable standalone with Claude API or local LLM
No LLM-provider abstraction; you'd need to rewrite it as a standalone script
Only useful if you're building inside the Claude Code ecosystem

### 3. Autofix (ecstatic-pirate/autofix)
Purpose: Claude Code skill — TDD fix-and-verify loop with git worktrees

**Pros**:
Test-before-implement discipline prevents regressions
Git worktree isolation makes it safe and reversible
Human confirmation gates; bounded retries (max 3)
Pairs perfectly with rootcause as a diagnose→fix pipeline

**Cons**:
__Same Claude Code coupling problem__ as rootcause — not a standalone Claude API app
Browser verification assumes a web project
No details on how LLM prompts are structured internally

## Recommendation for Claude API / Local LLM
Goal	                                                    Best Pick
Build a standalone app using Claude API	                    OpenResearch — has the cleanest LLM abstraction layer
Local LLM (Ollama, LM Studio via OpenAI-compat endpoint)	OpenResearch — swap the provider in config.yaml
Already using Claude Code CLI as your platform	            Rootcause + Autofix together as a pipeline

If you want to adapt rootcause/autofix to work with the Claude API directly, the methodology in their SKILL.md files is solid — you'd essentially port the 9-step/10-step logic into a Python script using the Anthropic SDK, which is a moderate but worthwhile effort. OpenResearch already did that architecture work for you.

What's your use case — are you building a debugging/fix tool, an ML research assistant, or something else?
ok, let me share some links and tell me which is the best one that is robust and will run locally too - 
https://peterfalkingham.com/2026/05/08/getting-local-ai-working-for-me-lm-studio-opencode-and-hermes/
https://ht-x.com/posts/2026/03/github-karpathy-autoresearch-ai-agents-running-res/
https://github.com/yibie/awesome-autoresearch
https://www.reddit.com/r/LocalLLaMA/comments/1ro00p2/project_karpathy_autoresearch_project_let_ai/
https://github.com/ecstatic-pirate/autofix
https://github.com/ecstatic-pirate/rootcause
https://github.com/moedesux/autoresearch-opencode

Skip ones that you already reviewed
Fetching the 5 new links in parallel now.

Agent:Fetch and analyze new research automation links
IN
Please fetch and analyze the following URLs. For each one, summarize: what it is, tech stack, LLM integration approach (especially local LLM support), key features, strengths, and weaknesses. Focus on robustness and local LLM compatibility (e.g., Ollama, LM Studio, OpenAI-compatible endpoints).

Use WebFetch for each URL.

URLs to fetch:
1. https://peterfalkingham.com/2026/05/08/getting-local-ai-working-for-me-lm-studio-opencode-and-hermes/
2. https://ht-x.com/posts/2026/03/github-karpathy-autoresearch-ai-agents-running-res/
3. https://github.com/yibie/awesome-autoresearch
4. https://www.reddit.com/r/LocalLLaMA/comments/1ro00p2/project_karpathy_autoresearch_project_let_ai/
5. https://github.com/moedesux/autoresearch-opencode

For GitHub repos also try to fetch the README raw content. For the GitHub repo moedesux/autoresearch-opencode, also check if there's a config file, main entry point, or any files showing LLM provider configuration.

Note: Do NOT re-review ecstatic-pirate/rootcause or ecstatic-pirate/autofix — those were already analyzed.

Be thorough but concise per link.


## Here's the full picture across all links, with the prior two (rootcause/autofix) as context:
Full Comparison — Robustness + Local LLM
Tool	                        Type	                Local LLM	              Robustness	      Ecosystem
moedesux/autoresearch-opencode	Code optimization loop	✅ Via OpenCode	        Medium (new, 186★)	OpenCode
OpenResearch (prev reviewed)	ML research pipeline	✅ Via config.yaml	    High (full stack)	 Standalone Python
Falkingham's stack	            Setup guide	            ✅ LM Studio + OpenCode	Proven personal use	 LM Studio + OpenCode
Karpathy AutoResearch	        ML experiment loop	    ❌ Cloud-first	        Research-grade	     Claude/cloud agents
Awesome-autoresearch	        Curated list	        N/A	Reference only	N/A
rootcause (prev reviewed)	    Debugging skill	        ❌ Claude Code only	    Good methodology	 Claude Code CLI
autofix (prev reviewed)	        Fix-and-verify skill	❌ Claude Code only	    Good methodology	 Claude Code CLI

## Winner for "Robust + Local LLM"
**Best overall**: moedesux/autoresearch-opencode + Falkingham's LM Studio setup

Here's why:
- moedesux/autoresearch-opencode is provider-agnostic by design — it delegates all LLM calls to OpenCode, so you swap the model at the OpenCode config level, not inside the skill

- Falkingham's article is essentially the deployment guide for this exact combination: LM Studio (local OpenAI-compatible endpoint) → OpenCode → skill. It proves the stack works with Qwen 3 27B and Gemma 4 27B
No MCP server needed, JSONL state persistence survives crashes, atomic writes with pre/post validation

**Caveat**: it's very new (last commit May 16, 2026) and the codebase has empty directories suggesting incomplete implementation. For production use, OpenResearch is more battle-hardened and has explicit Claude API + fallback chain support — but it pulls in Redis, ChromaDB, and a Kaggle dependency which complicates local-only deployment.

**My recommendation**:
If you want local LLM + code optimization → moedesux/autoresearch-opencode with LM Studio running Qwen 3 27B
If you want local LLM + ML research pipeline (EDA, baselines, reports) → OpenResearch with the OpenAI-compatible provider pointing at LM Studio/Ollama
If you want Claude API + debugging/fix workflow → rootcause → autofix pipeline within Claude Code CLI
What kind of task are you trying to automate — code optimization, ML experiments, or debugging?

## I want to build a stock research tool and a Executive Review assitant along with a board - Chief of Staff, VP of engineering etc to help run a org of 10 VPs with 200 people working on projeccts
Let me check your existing ExecutiveReviewPrep implementation first so I can design something that fits what you've already built.

Agent:Explore existing ExecutiveReviewPrep and skills structure
IN
Explore the codebase at d:\Github\page-agent-rp to understand:

1. The existing ExecutiveReviewPrep implementation - find and read the relevant files
2. The skills/impl/index.ts file to understand how skills are registered
3. Any existing financial/stock related code
4. The overall app architecture - what kind of app is this (extension? web app?), what framework, what LLM integration patterns exist
5. Any existing "board" or "agent" patterns

Key files to check:
- packages/extension/src/skills/impl/index.ts
- packages/extension/src/skills/impl/ (list all files)
- Any file with "Executive" or "Review" in the name
- packages/extension/wxt.config.js for app structure
- packages/extension/package.json for dependencies

Summarize: what the app is, what skills/features exist, how LLM is called, and what patterns are used for agent-like features.
Good context — you already have FinancialMonitor and ExecutiveReviewPrep in the extension. Before I design the architecture, a few scoping questions:

AskUserQuestion
OUT
User has answered your questions: "For the Stock Research Tool — what depth of analysis do you need?"="News & sentiment, Fundamental (financials, earnings, valuation)", "For the Executive Board — what should the AI board members actually do?"="Project health monitoring, Decision advisory, Weekly/sprint review, Conflict & dependency detection", "Where should this live and how should project data get in?"="Connect to Jira/Linear/Notion". You can now continue with the user's answers in mind.
Here's my proposed architecture for both systems, designed to fit your existing extension patterns:

## Design: Two New Features
1. Stock Research Tool (StockResearch.tsx)
Extends your existing FinancialMonitor into a multi-step research pipeline:

Ticker Input
    → Step 1: Fetch fundamentals (Yahoo Finance / Alpha Vantage / Polygon)
    → Step 2: Fetch recent news (NewsAPI or web scrape)
    → Step 3: LLM pass 1 — "Fundamental Analyst" persona → valuation summary
    → Step 4: LLM pass 2 — "News Analyst" persona → sentiment & catalysts
    → Step 5: LLM synthesis — combined research brief with Buy/Hold/Avoid framing
Output: structured report with Price Target rationale, Bull/Bear cases, Key Risks, Upcoming Catalysts.

2. Executive Board (ExecutiveBoard.tsx)
A multi-agent boardroom — each member gets the same org data, responds from their lens, then Chief of Staff synthesizes:


Data Sources (Jira / Linear / Notion)
    ↓ normalize to common project schema
    ↓
┌─────────────────────────────────────┐
│  Board Member Agents (parallel)     │
│  - Chief of Staff    (org health)   │
│  - VP Engineering    (velocity/debt)│
│  - VP Product        (roadmap/OKRs) │
│  - People/HR VP      (capacity/gaps)│
│  - CTO               (tech risk)    │
└─────────────────────────────────────┘
    ↓
Chief of Staff synthesis pass
    ↓
Weekly Briefing + Action Items + Red Flags
Board session modes:

Weekly Review — digest all 10 VPs' data → board briefing
Decision Advisory — pose a proposal → board debates it from each lens
Health Scan — surface conflicts, resource contention, timeline clashes
Integration: Jira / Linear / Notion
Settings panel additions with API keys. Data fetched via background service worker (avoids CORS). Normalized to:


interface ProjectSnapshot {
  team: string         // VP owner
  projects: Project[]  // status, blockers, health
  metrics: OrgMetrics  // velocity, capacity, burn
  risks: Risk[]
}
Sequencing recommendation
Phase	What	Effort
1	Stock Research Tool (fundamentals + news + LLM synthesis)	~2-3 days
2	Executive Board UI + board member personas + manual data paste	~2 days
3	Jira/Linear/Notion API integrations	~3-4 days
4	Multi-agent parallel execution + CoS synthesis	~2 days

# Design Document: AI Research & Executive Intelligence Platform
**Date:** 2026-05-17  
**Status:** Draft  
**Scope:** Stock Research Tool + Executive Board System

---

## 1. Chosen Foundation: OpenResearch

**Repo:** `https://github.com/charanvadhyar/openresearch`

### Why OpenResearch over the alternatives

| Criterion | OpenResearch | moedesux/autoresearch-opencode | rootcause + autofix |
|---|---|---|---|
| Multi-agent orchestration | LangGraph (production-grade) | Single-loop skill | Two-skill pipeline |
| Claude API support | Native (Anthropic SDK) | Via OpenCode | Claude Code CLI only |
| Local LLM support | OpenAI-compat endpoint in config.yaml | Via OpenCode | None |
| Report/synthesis pipeline | Built-in (Paper Writer agent) | None | None |
| State & memory | Redis + ChromaDB | JSONL files | None |
| Maturity | Full Python stack, well-structured | New (May 2026), empty dirs | Stable but narrow |
| Adaptability to new domains | High — swap agents per domain | Low — code-optimization only | Low — debug/fix only |

**Decision:** OpenResearch's LangGraph pipeline, multi-provider LLM abstraction, and synthesizer-agent pattern map directly onto both the Stock Research Tool and Executive Board. The other projects are either too narrow in scope or too immature.

### What gets kept vs replaced

| OpenResearch Component | Action | Reason |
|---|---|---|
| LangGraph orchestration layer | **Keep** | Core pipeline engine |
| LLM provider abstraction (config.yaml) | **Keep** | Claude + local LLM support |
| Pydantic schemas | **Keep** | Clean data contracts |
| Redis + ChromaDB | **Keep** | State persistence, vector memory |
| Report generation (Jinja2 → Markdown) | **Adapt** | Output format changes |
| Kaggle kernel executor | **Remove** | Not needed |
| ML-specific agents (EDA, Method Formulator) | **Replace** | New domain agents instead |
| Paper Writer agent | **Adapt → Board Synthesis agent** | Same pattern, different output |

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

| Source | Auth | Free Tier |
|---|---|---|
| Yahoo Finance (yfinance) | None | Unlimited |
| Alpha Vantage | API key | 25 req/day |
| Polygon.io | API key | 5 req/min |
| NewsAPI | API key | 100 req/day |
| SEC EDGAR | None | Unlimited |

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

| Agent ID | Role | Analytical Lens |
|---|---|---|
| `chief_of_staff` | Chief of Staff | Org health, CEO-level narrative, cross-cutting blockers |
| `vp_engineering` | VP Engineering | Sprint velocity, technical debt, delivery risk, capacity |
| `vp_product` | VP Product | Roadmap alignment, OKR progress, feature prioritization |
| `vp_people` | VP People / HR | Team morale signals, hiring gaps, attrition risk, performance |
| `cto` | CTO | Technical strategy, platform risks, architecture decisions |
| `cfo_proxy` | Finance Proxy | Budget burn rate, project ROI, resource allocation |

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
Recommendation: OpenResearch as the foundation.

Here's the reasoning in brief:

LangGraph orchestration maps directly onto both the stock pipeline (5 sequential nodes) and the executive board (6 parallel agents → conflict detector → synthesis) — you'd be adapting an existing pattern, not inventing one
Native Claude API + local LLM fallback via config.yaml provider chain — swap in LM Studio/Ollama with one config line, no code changes
Redis + ChromaDB already in place for state persistence — the board can remember previous sessions and the stock tool can cache research
moedesux/autoresearch-opencode is too narrow (code optimization only) and has incomplete directories; rootcause/autofix are Claude Code CLI-only
The design doc is at docs/5.md. It covers:

Full pipeline architecture for both features
All 6 board member agents and their lenses (Chief of Staff, VP Eng, VP Product, VP People, CTO, CFO Proxy)
Stock research pipeline: DataFetcher → NewsAggregator → FundamentalsAnalyst → SentimentAnalyst → Synthesizer
All Pydantic schemas (ResearchBrief, OrgSnapshot, BoardBriefing)
Jira/Linear/Notion integration specs
config.yaml structure for Claude + local LLM fallback
Phase-by-phase build sequence (4 weeks)
5 open questions that need answers before implementation (especially the Jira/Linear org-team mapping)
Want to answer those open questions and kick off Phase 1?

So which Github link would you recommend as the basis for a new project?
https://github.com/charanvadhyar/openresearch

It's the only one of the reviewed repos that gives you all three things you need out of the box:

Multi-agent orchestration (LangGraph) — directly adaptable to the 6 board member agents and the 5-node stock research pipeline
Claude API + local LLM support — provider chain in config.yaml, swap to LM Studio/Ollama with one line
Synthesis/report generation — the Paper Writer agent is the exact pattern you need for both the Research Brief and the Board Briefing
The others don't fit:

moedesux/autoresearch-opencode — OpenCode skill for code optimization, not a general agent framework
rootcause / autofix — locked to Claude Code CLI, no standalone use
Karpathy AutoResearch — ML experiment loop, cloud-only, GPU-dependent
awesome-autoresearch — a reference list, not executable code
Fork charanvadhyar/openresearch, strip the Kaggle executor and ML agents, add the FastAPI server wrapper, and you have your foundation. The design in docs/5.md tells you exactly what to keep vs replace.