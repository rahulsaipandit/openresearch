# Finance AI Requirements

*Background research and source verification live in [`Initial_requirement_collection.md`](./Initial_requirement_collection.md) — this doc is the actionable spec.*

## Overview

Build a desktop research assistant using a **Tauri frontend as the shared UI for the whole OpenResearch platform** (Stock Research, Executive Board, Interview Prep, Real Estate), talking to the existing local **FastAPI server** (`server.py`, `localhost:7842`). This replaces the Chrome Extension that `docs/design.md` describes as planned-but-unbuilt (Phase 5) — Tauri becomes the one desktop shell for all four verticals rather than a stock-only app.

Within that shell, the Stock Research panel should feel like an LLM-powered stock analyzer that aggregates recent market data, company financials, and news, then produces structured investment intelligence that's easy to consume for non-experts. The goal is a reliable analysis starting point, not a final trading recommendation — sourced, transparent insights instead of endlessly searching YouTube/blogs.

The system should answer questions like *"Is it a good time to invest in Yes Bank?"* or *"How are Reliance Industries' current financials looking?"* with a comprehensive, cited analysis in under a minute, while clearly stating it's a research aid, not investment advice.

## Existing Foundation (already built — do not rebuild)

`agents/stock/` already implements a 5-node async pipeline (`pipelines/stock_pipeline.py`, exposed at `POST /api/stock-research` and via `mcp_server.py`'s `run_stock_research` tool):

1. `data_fetcher.py` — Yahoo Finance (free), Alpha Vantage (income statement/balance sheet), Polygon.io (earnings calendar), and **Equibles** (self-hosted MCP/Docker service, `depth="full"` only) for 13F institutional holdings, FINRA short interest, SEC fails-to-deliver, insider Form 3/4 transactions, congressional trading, and technical indicators (RSI/MACD/Bollinger/SMAs).
2. `news_aggregator.py` — NewsAPI headlines, SEC EDGAR filing index, plus Equibles SEC full-text search excerpts.
3. `fundamentals_analyst.py` — LLM-generated `ValuationSummary` (fair value range, margins, growth, moat assessment).
4. `sentiment_analyst.py` — LLM-generated `SentimentSummary` (tone, catalysts, risks, headlines).
5. `research_synthesizer.py` — final LLM synthesis into `ResearchBrief` (verdict, price target, bull/bear case, risks, catalysts, sources), with Equibles data attached when available.

### Equibles dependency — not yet set up

Insider trades, Congress trades, 13F institutional holdings, and technical indicators all depend on Equibles, a self-hosted Docker service (`docker compose up -d`, MCP at `localhost:8081`). It is **not running** in this environment. Until it is, those fields return `None` in `ResearchBrief` (pipeline degrades gracefully rather than failing) and requirements #2 and part of #6 below can't be demoed end-to-end.

**Action item:** set up Equibles before building UI panels that depend on this data, or scope `EdgarTools` as a fallback data source for Form 4/13F if self-hosting Equibles isn't viable long-term (see stack notes below).

## Requirements Status

| # | Requirement | Status |
|---|---|---|
| 1 | Detailed fundamentals breakdown | ✅ built (`fundamentals_analyst.py`), rendered in the Stock panel's fundamentals table |
| 2 | Insider and Congress trade alerts | ✅ built, blocked on Equibles setup |
| 3 | Side-by-side comparison of any two stocks | ✅ built — `ComparisonAnalystAgent` + `POST /api/stock-compare`, Comparison panel in `desktop/` |
| 4 | Watchlist of up to 20 stocks | ✅ built — `WatchlistStore` (20-cap enforced) + `/api/watchlist` CRUD, Watchlist panel |
| 5 | Summarized earnings calls | ⚠️ partial — `DocumentInsightsAgent` summarizes an uploaded PDF (transcript/report) with page-level citations; no automated transcript *sourcing* (user must supply the PDF) |
| 6 | ETF and institutional ownership insights | ⚠️ partial — institutional 13F via Equibles; no ETF-specific breakout |
| 7 | Five-year trend analysis + previous-year summary | ✅ built — `TrendAnalystAgent` + `GET /api/stock-trend/{ticker}`, Trend panel with price + revenue/net-income charts + EWMA/GARCH volatility |
| — | Personal memory/context system | ❌ not built |
| — | Desktop UI | ✅ built — Tauri + React shell in `desktop/`; frontend compiles clean, full Rust build (`cargo build`) verified, `tauri dev` confirmed live (HMR observed reflecting code changes in the running window) |
| — | Natural-language query → ticker extraction | ✅ built — `QueryRouterAgent` + `POST /api/query`; verifies every LLM-guessed ticker against yfinance before running analysis, returns a clarification question instead of guessing when it can't resolve one |
| — | Research Primer (richer, multi-section document) | ✅ built — "middle ground" scope (see below); `POST /api/stock-primer`, Primer panel with print-to-PDF |
| — | SEC Insights (filing Q&A with citations) | ✅ built — local chromadb + EdgarTools, `POST /api/sec-insights`, SEC Insights panel |
| — | Document Insights (uploaded-PDF summarization with citations) | ✅ built — LiteParse (subprocess) + LLM, `POST /api/stock-document-insights`, Document Insights panel |

## What's Implemented (this pass)

**Backend** (`server.py` + new modules, all tested via `fastapi.testclient.TestClient`):
- `schemas/query.py`, `schemas/comparison.py`, `schemas/watchlist.py`, plus `TrendPoint`/`TrendData`/`VolatilityMetrics` added to `schemas/stock.py`
- `agents/stock/query_router.py` — `QueryRouterAgent`, `agents/stock/comparison_analyst.py` — `ComparisonAnalystAgent`, `agents/stock/trend_analyst.py` — `TrendAnalystAgent` (deterministic, no LLM call)
- `agents/stock/volatility.py` — EWMA (RiskMetrics decay=0.94) and GARCH(1,1) daily-return volatility estimators, pure numeric functions (no LLM, no I/O), unit-tested in `tests/test_volatility.py` against synthetic return series; wired into `TrendAnalystAgent` off a separate ~1y daily-close fetch (the existing 5y series is monthly, too coarse for daily-return volatility)
- `store/watchlist_store.py` — atomic JSON store, 20-item cap enforced (verified: adding a 21st ticker raises)
- New endpoints: `POST /api/query`, `POST /api/stock-compare`, `GET /api/stock-trend/{ticker}`, `GET|POST /api/watchlist`, `DELETE /api/watchlist/{ticker}`

### Research Primer (middle-ground scope)

Requested as "similar to" a sample 123-page institutional research primer PDF — but that document turned out to be the output of a multi-stage adversarial "20/60/20" process (baseload facts → per-unknown deep-dive "work orders" → adversarial bear-case review → underwriting synthesis), not just a longer report. Scoped down deliberately, per user decision, to a single-pass pipeline that reuses the existing `ResearchBrief` + `TrendData` rather than building a multi-day, per-unknown deep-dive subsystem:

- `schemas/primer.py` — `ResearchPrimer` (wraps `ResearchBrief` + `TrendData`, adds `BusinessFoundation`, `driver_tree`, `debate_map`, `AdversarialReview`, `underwriting_summary`)
- `agents/stock/business_foundation.py`, `agents/stock/driver_debate.py`, `agents/stock/adversarial_review.py` — three new LLM agents, same JSON-in/pydantic-out/fallback pattern as existing agents
- `pipelines/primer_pipeline.py` — `ResearchPrimerPipeline`, orchestrates the existing `StockResearchPipeline` + `TrendAnalystAgent` plus the three new agents
- `POST /api/stock-primer` — verified via unit tests with a stub LLM (happy path + fallback path) for all three new agents
- Frontend: Primer panel renders all sections with print-friendly CSS; "Save as PDF" uses the browser's native `window.print()` rather than a new backend PDF-generation dependency

### SEC Insights (filing Q&A with citations)

Requested as "similar to" `run-llama/sec-insights` — critically evaluated first: keep the citation-Q&A *concept*, reject the Postgres+PGVector/S3/CloudFront/Vercel/Render production-SaaS infra (irrelevant to a single-user local desktop app). Two vector-store alternatives (`turbovec`, `LEANN`) were independently verified (GitHub API, not just summaries) and rejected — both solve a 10M+ document corpus-scale problem; our per-ticker filing corpus is a few hundred chunks, so their compression/storage-reduction value doesn't apply.

- **Local embeddings, per user decision:** `chromadb` `PersistentClient`, default local ONNX MiniLM embedding function (no cloud embeddings API, no GPU dependency, ~79MB one-time model download) — `store/sec_vector_store.py`, one shared collection filtered by a `ticker` metadata field
- **Ingestion:** `agents/stock/sec_ingest.py` uses `edgartools` (verified real, MIT, already the scoped Equibles fallback) to fetch the latest 10-K/10-Q and chunk the business/risk-factors/MD&A sections
- **Q&A:** `agents/stock/sec_qa.py` — retrieves top-k chunks, LLM answers with `[n]` citation markers mapped back to filing/section/date
- `POST /api/sec-insights` — verified end-to-end with **real** EdgarTools ingestion (live SEC EDGAR fetch) and **real** chromadb semantic search (a risk-related question correctly retrieved the risk-factors section), stub LLM for the synthesis step
- Frontend: SEC Insights panel (ticker + question → cited answer)

### Document Insights (LiteParse integration)

Requested follow-up: integrate `@llamaindex/liteparse` (verified real — Apache-2.0, standalone npm package, single dependency, has a CLI — via direct npm/GitHub inspection, not just the vendor blog) for bounding-box citations. It's a Node.js CLI tool, not a Python library, so the integration shells out to a locally-installed copy (`tools/liteparse/`, its own `package.json`) rather than importing in-process.

- `integrations/liteparse.py` — subprocess wrapper, parses LiteParse's JSON output (`schemas/document_insights.py`: `ParsedDocument`/`ParsedPage`/`ParsedTextItem` with real `x/y/width/height` bounding boxes, verified against actual CLI output on a real PDF)
- `agents/stock/document_insights.py` — `DocumentInsightsAgent` summarizes an uploaded PDF (earnings-call transcript, analyst report) with per-citation document name + page + bounding box, filling requirement #5's ingestion gap
- **Citation tightening (this pass):** two gaps identified by re-reading the LiteParse blog's due-diligence-agent example against our own implementation:
  - `DocumentCitation` now carries `document_name` per citation (was previously only on the top-level `DocumentInsightAnswer`, and was the throwaway temp file path — `server.py` now passes the real uploaded filename through). Each citation is now self-describing rather than relying on an implicit single-document-per-answer assumption.
  - The LLM is now asked for a short verbatim quote (5-15 words) per cited page, fuzzy-matched (stdlib `difflib`, no new dependency) back against LiteParse's `text_items` for that page — `agents/stock/document_insights.py`'s `_find_best_span` — to find the tightest run of consecutive items covering the actual cited text; `_union_bbox` merges their boxes. Below a 0.6 match-ratio threshold it falls back to the page's first text item, same as before. Still not pixel-perfect sentence highlighting in every case (depends on the LLM's quote being a genuine substring/near-match), but materially tighter than "always the first box on the page" — unit-tested in `tests/test_document_insights.py` against constructed text-item fixtures (no LiteParse CLI or LLM needed for these tests).
  - Still not done: no PDF-viewer highlight-overlay UI (`pdf.js` integration) — the frontend still renders citations as page-number + excerpt cards, not a clickable jump-to-location view. Flagged as a possible future pass, not attempted here.
- `POST /api/stock-document-insights` (multipart file upload) — verified end-to-end against the real 123-page primer PDF: real LiteParse subprocess parse, real bounding boxes returned, correct page-citation mapping (stub LLM for synthesis)
- Frontend: Document Insights panel (ticker + PDF upload → cited summary), each citation card now shows `document_name` alongside its page number

**Frontend** (`desktop/` — Tauri v2 + React + TypeScript + Vite):
- Shared shell (`App.tsx`) navigating all four verticals
- Stock Research panel: query box → `ResearchBrief` view with cited text, fundamentals table, bull/bear case; sub-tabs for Dashboard, Watchlist, Compare, Trend
- **Dashboard sub-tab** (`DashboardPanel.tsx`) — a single-page, three-column overview (snapshot/technicals/insider+Congress trades on the left, price chart + volatility + income statement + notable events in the center, sentiment/headlines/institutional ownership on the right), modeled after a reference stock-dashboard screenshot the user shared. Composed entirely from the existing `ResearchBrief` + `TrendData` payloads (`runStockResearch` + `getTrend` called together, no new backend endpoint) — sections the reference showed that we have no real data source for (executive bios/photos, per-analyst-firm rating tables, compensation summaries) were deliberately left out rather than faked; Equibles-gated fields (insider/Congress trades, institutional holders, technicals) render an explicit "requires Equibles" note when absent instead of an empty section.
- The four Frontend Component Requirements from earlier in this doc, implemented: `FinancialChart.tsx` (line/bar/area/scatter + PNG export), `CitedText.tsx`, `DataTable.tsx` (+ CSV export), `ContentDialog.tsx`
- Thin passthrough panels for Board/Interview/RealEstate
- `npm install`, `tsc`, and `vite build` all pass with zero errors. **Not yet done:** `cargo build`/`tauri dev` (Rust compile not run this session), app icons for release bundling — see `desktop/README.md`.

## Target Architecture

- **Desktop frontend: Tauri** — one shell for all four OpenResearch verticals (Stock, Executive Board, Interview Prep, Real Estate), not a stock-only app. Panels map to existing endpoints: `POST /api/stock-research`, `POST /api/board-session` + polling, `POST /api/interview-prep`, `POST /api/real-estate-research`.
- **Backend API: FastAPI** — already implemented (`server.py`, `localhost:7842`). No new backend framework needed; new work is new endpoints/fields on the existing server plus the pipeline gaps above.
- **Core logic:** Python
- **AI layer:** LLMs with retrieval augmentation and structured prompt design — already implemented via `LLMClient.from_config()` (Anthropic primary, local LM Studio/Ollama fallback via the `openai_compatible` provider)
- **Orchestration:** plain async Python pipelines per domain, not LangChain/LangGraph — a deliberate, already-validated choice (see `docs/design.md` and `Initial_requirement_collection.md` §1 and §5). Don't reintroduce LangChain for orchestration; a deterministic document parser (LiteParse-style) is worth considering separately for earnings-call/filings ingestion (requirement #5).

## Deployment Constraints

- Host the Python backend in a **venv** or **Docker container** depending on developer preference and local Windows setup.
- Keep dependencies, API keys, and environment configuration isolated and repeatable.
- Target local LLMs that fit an RTX 4070 with **~10 GB VRAM** — prefer compact/quantized 7B/8B variants, mixed CPU/GPU inference, or client-server hosting via LM Studio.
- Avoid excessively large models; rely on retrieval and prompt engineering rather than model scale.

## Core Features (detailed spec for the gaps)

### 3. Stock Comparison
- Compare any two stocks side by side
- Highlight strengths/weaknesses across fundamentals, valuation, growth, profitability, and sentiment
- Summarize where each company is better
- Support both absolute and relative comparisons

### 4. Watchlist
- Save up to 20 stocks
- Display recent price change, news highlights, and a quick sentiment score
- Allow one-click analysis from watchlist items

### 5. Earnings Summary
- Summarize recent earnings calls and results
- Extract key beats/misses, revenue guidance, margin commentary, management tone
- Provide concise takeaways and action considerations
- Needs a transcript/document source not currently wired (current pipeline only covers filings/news, not call transcripts) — a deterministic, citation-preserving parser (LiteParse-style) is a good fit here so summaries stay auditable

### 6. ETF and Institutional Ownership (completing the partial build)
- Institutional holders: ✅ via Equibles 13F (once running)
- ETF exposure specifically: ❌ needs its own data source — not covered by 13F data as-is
- Ownership-change and concentration trend highlights

### 7. Trend Analysis
- Five-year trend view for price, revenue, and key metrics
- Previous-year summary with highlights and change indicators
- Visual and textual trend analysis
- Note: this goes beyond what the named reference product (Stocktaper) itself offers — treat as a genuine differentiator, not parity work
- **Volatility (EWMA + GARCH):** `VolatilityMetrics` on `TrendData` — `ewma_annualized_pct` (RiskMetrics-style EWMA, decay=0.94, weights recent daily returns more heavily via smooth exponential decay) and `garch_forecast_annualized_pct`/`garch_long_run_annualized_pct` (GARCH(1,1) via the `arch` package: a one-day-ahead forecast plus the long-run average variance it mean-reverts toward). A deterministic `interpretation` string flags when current volatility is running hot/cold vs. the GARCH long-run average, so the LLM never has to eyeball or hallucinate this comparison. Computed off ~1y of *daily* closes fetched separately from the 5y *monthly* series already used for the price chart.

## AI Requirements

### Reliable AI workflow
- Don't rely on base LLM training data for facts — augment with real-time data and document context
- Use structured prompts and function calls for stable output
- Enforce evidence-backed reasoning; add auditability through source citations or data references

### Required capabilities
- Accept natural-language queries about stocks and financials; extract ticker symbols reliably — **❌ not built** (see Requirements Status table); today the backend only accepts a direct ticker

### Query Router (design — not yet implemented)

A new lightweight step in front of the existing pipeline, not part of the deep synthesis chain:

- **`QueryRouterAgent.route(query: str) -> QueryIntent`** — LLM call (persona: "financial query router") extracts a structured guess from free text: `{intent: single_analysis|comparison|watchlist_add|unknown, companies: [{name, likely_ticker, exchange_guess}], depth}`. Parsed into a pydantic model, same JSON-in/pydantic-out pattern as the existing agents, with a regex fallback if parsing fails.
- **Ticker verification, not blind trust:** a small local model can hallucinate tickers or guess the wrong exchange suffix (e.g. "Yes Bank" → must resolve to `YESBANK.NS`, not a US symbol). Each `likely_ticker` must be verified against yfinance (already a free, no-key dependency) before proceeding. If it doesn't resolve, return `clarification_needed=True` with a specific question rather than silently running analysis on a wrong/invented symbol — this keeps the evidence-backed principle intact even for a cheap extraction step.
- **New endpoint:** `POST /api/query` — `{query}` in, runs the router, then either calls the existing `StockResearchPipeline` (single ticker), runs it twice for a comparison, or returns the clarification question. No changes needed to the pipeline itself.
- **Why this is a good fit for a local LM Studio model specifically:** it's a narrow classification/extraction task, not deep multi-step reasoning — well within a quantized 7B/8B model's ability, and a good place to actually use the local-inference path the RTX 4070/10GB constraint already anticipates, while reserving Claude (or whatever's first in the provider chain) for the heavier fundamentals/sentiment/synthesis nodes.
- **Not limited to the router step:** the same LM Studio `openai_compatible` endpoint (already supported by `LLMClient.from_config()`, just commented out by default in `config.yaml`) can back any conversational/chat-style interaction in the query interface too, not only ticker extraction — e.g. answering simple follow-up questions about an already-generated brief without re-running the full pipeline. Whether a given call goes to the local model or the cloud provider is just a matter of where it sits in the `provider_chain`, per node/task — no new plumbing required beyond enabling the existing config block.
- Fetch a mix of data: prices, fundamentals, news, filings, insider activity, ownership data
- Generate a structured analysis: thesis, evidence, positives, negatives, suggestions
- Support comparative queries across two tickers
- Summarize earnings and filings in plain language

## Recommended Open Source Stack

*(Critically re-evaluated against actual requirements, not adopted just because they were reviewed — see `Initial_requirement_collection.md` §3 for verification detail.)*

**Actual dependencies added (all verified, not adopted on vendor claims alone):**
- **`FinanceToolkit`** (MIT) — ratio/valuation/risk-metric calculation layer; directly reduces work for comparison (#3) and trend-analysis (#7).
- **`EdgarTools`** (MIT, module name `edgar`) — **now actively used**, not just conditional. Equibles is still not set up in this environment, so EdgarTools became the real SEC filing data source for the Research Primer and SEC Insights ingestion (`agents/stock/sec_ingest.py`). Verified with a live SEC EDGAR fetch (real ticker, real 10-K). If Equibles is set up later, this stays as the SEC Insights/Primer data source regardless — Equibles doesn't expose section-level filing text through our MCP client the way EdgarTools' `TenK.risk_factors`/`.business`/`.management_discussion` do.
- **`chromadb`** (Apache-2.0) — local embedded vector store for SEC Insights semantic search, chosen over `turbovec` and `LEANN` (see below).
- **`@llamaindex/liteparse`** (Apache-2.0, npm) — PDF text + bounding-box extraction for Document Insights, installed locally under `tools/liteparse/` and invoked via subprocess (it's a Node CLI, not a Python library).
- **`arch`** (NCSA license, PyPI) — GARCH(1,1) volatility model fitting for the Trend view's volatility metrics (`agents/stock/volatility.py`); the standard, actively-maintained Python library for ARCH/GARCH family models (built on `statsmodels`/`scipy`). EWMA itself needed no new dependency — it's a ~10-line variance recursion implemented directly with `numpy` (now an explicit dependency rather than only a transitive one via `yfinance`/`pandas`).

**Vector-store alternatives considered and rejected — verified via GitHub API, not just summaries:**
- **`turbovec`** (MIT, Rust+Python bindings, 14.5k+ stars — confirmed real) — solves 10M+ document corpus compression (31GB→4GB vs FAISS); our per-ticker filing corpus is a few hundred chunks, so that value doesn't apply. Also just a raw index — no embedding generation or persistence layer, more assembly required.
- **`LEANN`** (MIT, Python, 12.7k+ stars — confirmed real, MLSys 2026 paper, explicitly "100% private RAG on your personal device") — genuinely philosophically aligned, but its storage-reduction value prop (97% savings) only matters at a scale we're nowhere near, and its native dependency chain (Boost, Protocol Buffers, OpenBLAS/MKL, ZeroMQ, libomp) is real Windows-build risk for no benefit here. **Worth revisiting** if the still-unbuilt personal memory/context system grows into a large multi-document local RAG store — that's a better match for LEANN's actual value prop than per-ticker SEC filings.

**No action — inspiration was considered and rejected as unnecessary for our actual scope:**
- **`OpenBB`** — AGPLv3 copyleft; real legal risk, no exception carved out here.
- **`OpenTerminalUI`** — never independently verified beyond its README; nothing concrete earned adoption.
- **`ValueCell`**'s orchestrator pattern — our `server.py` + per-vertical pipelines already provide the same separation of concerns; adding a second orchestration layer solves a problem we don't have.
- **`Ghostfolio`** — solves live multi-brokerage aggregation, a bigger problem than the actual requirement (a personal `Portfolio.csv` + watchlist).
- **`Qlib`**, **`LEAN`** — no backtesting/execution requirement exists; correctly out of scope.
- **`FinceptTerminal`**, **`Neuberg`** — license/architecture mismatch.
- **`run-llama/sec-insights`**'s production infra (Postgres+PGVector, S3+CloudFront, Vercel/Render, Sentry, Arize Phoenix) — SaaS reference-app infra irrelevant to a single-user local desktop app. Only its citation-Q&A *concept* was kept.

## UX and Interaction

- Tauri app shell with navigation across verticals: Stock Research, Executive Board, Interview Prep, Real Estate — each a panel/route calling its existing FastAPI endpoint
- Stock Research panel:
  - Query box for natural language questions
  - Watchlist panel (up to 20 stocks)
  - Comparison mode for two stock symbols
  - Earnings summary view for the latest quarter
  - Trend dashboard with charts for five-year and one-year summaries
  - Alerts panel for insider/Congress trades (requires Equibles running)
  - Research Primer sub-tab: multi-section document with print-to-PDF
  - SEC Insights sub-tab: filing Q&A with citations
  - Document Insights sub-tab: upload a PDF, get a cited summary
  - Clear disclaimer: research assistant, not investment advice
- Other verticals (Board/Interview/RealEstate) reuse the same shell chrome and just need thin result-rendering views for their existing `BoardBriefing` / `InterviewPrepBrief` / `RealEstateBrief` schemas — no new backend logic required for those three.

### Frontend Component Requirements

*(Derived from reviewing throwaway sample code under `docs/Finance-AI/` — that code will be deleted once this analysis is done, so the requirements are captured here in our own terms, not as references back to it.)*

1. **Multi-series financial chart component**
   - Supports line, bar, area, and scatter chart types against a typed series schema (each series has a name and a list of `{x, y}` points, optionally sized/labeled points for scatter).
   - Must support overlaying two or more series on one chart — this is the rendering backbone for both the 5-year trend view (#7) and the two-stock comparison view (#3).
   - Export the rendered chart as a PNG image.
   - Framework-agnostic requirement, not tied to any specific charting library — Recharts, Chart.js, or D3 are all acceptable implementations.

2. **Cited-text renderer**
   - Renders analysis text (e.g. `ResearchBrief.summary`, bull/bear case, risks) with inline citation markers (`[1]`, `[2]`, ...) that link to the corresponding entry in `ResearchBrief.sources`.
   - Reinforces the auditability requirement under AI Requirements — every generated claim should be traceable to a source in the UI, not just in the raw JSON.

3. **Tabular data view with export**
   - Displays structured tabular data (e.g. fundamentals line items, watchlist rows, institutional holders) with sortable columns.
   - Supports exporting the visible table to CSV.

4. **Content dialogs / expandable panels** (lower priority, generic utility)
   - Simple modal or expandable-panel component for showing longer content (full filing excerpts, full earnings-call summary, source document snippets) without navigating away from the main view.
   - Only needed to support the citation/auditability requirement above — not a component to over-invest in.

5. **Query interface layout**
   - A query box → single-shot structured result view, not a multi-turn chat UI. The requirement is "ask a question, get a comprehensive cited analysis in under a minute" (see Product Vision) — there's no requirement for conversational back-and-forth or a chat-session history sidebar, so don't build one.
   - The result view renders rich content inline — charts, tables, and cited text together in one scrollable view — rather than only plain text.
   - Past analyses are already persisted via the existing Tolaria vault export (`export_to_tolaria`) — that's the history mechanism. Don't build a second, bespoke session-history system on top of it.
   - This layout is shared shell chrome (see above) — each vertical's panel plugs its own request form and result renderer into this same layout.

6. **Watchlist and stock-comparison views** — genuinely new UI, not adapted from anything: a watchlist list/grid (ticker, price change, sentiment, one-click "analyze") and a 2-column side-by-side comparison view built on components #1–#3 above.

## Personal Memory & Context System

Build support for personal investor context so the app can use market data more helpfully.

### What to store
- Investor profile: experience, background, goals, time horizon, risk tolerance, portfolio size, strategy style
- Strategy rules: drawdown limits, position sizing, rebalancing rules, entry/exit criteria, watchlist priorities
- Portfolio state: current positions, weights, target allocations
- Watchlist and trade ideas: themes, tickers, potential setups, catalysts
- Prompt templates: saved prompts, query patterns, session workflows

### Folder setup
A local folder with five Markdown files and one CSV file:

1. `Investor-profile.md` — experience/background, goals and time horizon, risk tolerance, portfolio size, preferred sectors, decision style.
2. `Strategy.md` — maximum drawdown, rebalancing parameters, position sizing targets, entry/exit criteria, rules for adding/removing positions.
3. `Portfolio.csv` — symbol, shares, cost basis, market value, current weight, target weight, notes.
4. `Watchlist.md` — sectors, tickers, potential setups, catalysts, monitoring notes.
5. `Prompts.md` — prompt templates, question structures, common analysis workflows for reuse each session.

### Scheduled task ideas
- Complete portfolio analysis
- Daily news review
- Overnight market moves summary
- Trading ideas based on rule-based parameters

## Nonfunctional Requirements

- Fast enough to respond within ~60 seconds for a full analysis
- Modular backend so new data sources and tools can be added easily
- Secure local desktop app with data privacy by default
- Stable ability to render charts and rich text from backend results

## Notes

- Build as a research support tool, not a fully automated trading system.
- Strong prompts and example-guided output formatting are critical.
- Encourage users to verify conclusions and use AI output as a starting point, not a final answer.
