# Review @docs/design.md Stock related section

and

## Equibles

Look at **https://github.com/daniel3303/Equibles**

A self-hosted MCP server that scrapes and serves public U.S. financial data and exposes it as MCP tools, so any MCP-capable client (Claude Code/Desktop, Cursor, or your own local-model agent loop) can query it directly.

**What it serves**:

- SEC filings (10-K/10-Q/8-K) with full-text search
- 13F institutional holdings, insider (Form 3/4) and congressional trades
- FINRA short volume / short interest, SEC fails-to-deliver
- FRED economic indicators, CFTC futures positioning, CBOE VIX/put-call
- Daily prices + technical indicators

## Here is the Review Comparison: Stock Research Section + Equibles Integration Assessment

### Current Pipeline - What We Have vs. What We're Missing

Looking at Section 3 of the design, the current Node 1–2 data layer covers:

| Source        | What it gives us                                      |
|---------------|-------------------------------------------------------|
| yfinance      | Price, P/E, EPS, margins, beta, analyst target        |
| Alpha Vantage | Income statement, balance sheet                       |
| Polygon.io    | Earnings calendar                                     |
| NewsAPI       | Headlines (last 30 days)                              |
| SEC EDGAR     | Basic CIK lookup → 8-K/10-Q/10-K filings              |

### Critical gaps today - the signals institutional analysts actually trade on

| Signal             | Gap                                                              |
|--------------------|------------------------------------------------------------------|
| Who owns it        | 13F institutional holdings completely absent                     |
| What insiders think| Form 3/4 insider buys/sells - not tracked                        |
| Short pressure     | FINRA short volume, SEC fails-to-deliver - absent                |
| Macro backdrop     | FRED interest rates, employment, CPI - absent                    |
| Options sentiment  | CBOE VIX, put/call ratio - absent                                |
| Futures positioning| CFTC commercial vs speculative - absent                          |
| Congressional      | DC trades - absent                                               |
| SEC full-text      | We do CIK lookup only; no semantic/keyword search across filing bodies |

Equibles fills every single one of these gaps.

### Should You Integrate? Yes - but via MCP, Not Code Adaptation

Don't copy/adapt the code directly. Two reasons:

**Wrong language** - it's C# .NET 10 / PostgreSQL. Adapting it to Python would mean rewriting the scrapers, the background workers, the database layer, the full-text search engine. That's months of work to replicate something that already runs in one docker compose up.

**AGPL-3.0 licence** - if you import or adapt the source code, your project must also be AGPL-licensed (open-source). Consuming it as a service over MCP avoids this entirely - you're just calling an API.

The right integration path: consume Equibles as an MCP server. This is exactly what it was built for, and you already have the client infrastructure.

### How It Fits the Existing Architecture

Equibles runs on port 8081 as an MCP SSE endpoint. Your agents/mcp_client.py already handles MCP tool calls. The wiring is:

- `.mcp.json`  →  equibles server at localhost:8081
- `config.yaml`  →  stock_research MCP servers += "equibles"
- `DataFetcherAgent`  →  calls equibles MCP tools for 13F, short interest, technical indicators
- `NewsAggregatorAgent`  →  calls equibles for SEC full-text search, insider trades, FRED macro

No new transport code needed - MCPClient already handles this. The agents just get a richer data payload before the LLM synthesis step.

### Concrete Changes to the Design

1. **.mcp.json** - add Equibles server entry

```json
"equibles": {
  "type": "sse",
  "url": "http://localhost:8081/mcp"
}
```

Unlike the other Node.js MCP servers in .mcp.json, Equibles is HTTP SSE (it runs in Docker), so no command/args needed - just a URL. Phase 7 (MCPClient stdio/SSE upgrade) already plans for this.

2. **config.yaml** - add to stock research MCP section

```yaml
mcp:
  servers:
    stock_research:
      - equibles          # ← new: institutional, short, macro, insider, SEC full-text
      - brave-search
      - fetch
```

Also add an equibles: config block for optional ticker filtering (Equibles supports limiting sync scope):

```yaml
equibles:
  enabled: false          # set true when docker compose is running
  server_url: "http://localhost:8081"
  tickers: []             # empty = all tickers; ["NVDA","AAPL"] = focused sync
```

3. **DataFetcherAgent** - extend Node 1 with Equibles calls

When Equibles is available (`mcp.is_available("equibles")`), add calls for:

- `get_institutional_holders(ticker)` → top holders + quarter-over-quarter change
- `get_short_interest(ticker)` → FINRA short volume + SEC fails-to-deliver
- `get_technical_indicators(ticker)` → RSI, MACD, Bollinger already computed
- `get_congressional_trades(ticker)` → alternative signal

These are injected into the context passed to FundamentalsAnalystAgent.

4. **NewsAggregatorAgent** - extend Node 2

Replace the basic CIK-lookup SEC walk with Equibles full-text search:

- `search_sec_filings(ticker, query="revenue guidance risk")` → relevant excerpts, not just filing metadata
- `get_insider_transactions(ticker, days=90)` → Form 3/4 recent buys/sells

5. **Schema changes** - schemas/stock.py

Two new optional sub-schemas on ResearchBrief:

```python
class InstitutionalSnapshot(BaseModel):
    top_holders: list[str]           # "Vanguard 8.2% (+0.4% QoQ)"
    total_institutional_ownership: float | None
    recent_13f_changes: list[str]    # who added/reduced significantly

class MarketStructureData(BaseModel):
    short_interest_ratio: float | None     # days-to-cover
    short_volume_pct: float | None         # FINRA % of daily volume
    fails_to_deliver: int | None
    insider_net_activity: str | None       # "net seller", "net buyer", "neutral"
    congressional_trades: list[str]
```

Add these as optional fields on ResearchBrief:

```python
institutional: InstitutionalSnapshot | None = None
market_structure: MarketStructureData | None = None
```

6. **ResearchSynthesizerAgent** - richer brief

The synthesizer already receives ValuationSummary + SentimentSummary. With Equibles data, the LLM prompt gains:

> "Institutional ownership is 72%; Vanguard added 0.4% last quarter → steady accumulation" → reinforces bull case

> "CEO sold $4M in shares 3 weeks ago; short interest at 18-day cover → elevated caution" → bear case signal

> "10-Q mentions 'supply chain headwinds' in risk section 14 times" → full-text insight unavailable today

The output quality of `ResearchBrief.bull_case` / `bear_case` / `key_risks` would materially improve.

### What This Doesn't Change

- The 5-node pipeline structure stays identical
- No new pipeline nodes needed - Equibles data slots into existing Nodes 1 and 2
- `depth="quick"` still skips Equibles (same pattern as Alpha Vantage / Polygon.io skip)
- LLMClient, server.py, schemas (except the two new optional fields) - unchanged
- All existing fallbacks remain: if Equibles isn't running, `mcp.is_available("equibles")` returns False and the pipeline proceeds as today

### Setup Cost vs. Value

| Dimension            | Assessment |
|----------------------|------------|
| Setup effort         | docker compose up + optional free FINRA/FRED keys. First sync takes time but runs in background. |
| Data freshness       | Equibles continuously scrapes; 13F data is quarterly by nature; prices + short volume are daily |
| No API keys required | Only FINRA + FRED (both free) are optional; everything else is public scraping |
| Local model impact   | This is the core win - local models (Qwen3-27B via LM Studio) get institutional + short + macro context they'd never have otherwise. The quality gap between local and cloud models narrows significantly on stock research. |
| Maintenance          | Self-hosted Docker service; you own the data, no rate limits, no telemetry |

### Recommended Design Update

The design.md Phase 7 build plan should add:

| Step | Deliverable | Phase |
|------|-------------|-------|
| 9    | Add equibles to .mcp.json (HTTP SSE transport) | Phase 7 |
| 10   | Extend DataFetcherAgent with Equibles tool calls (13F, short, technicals, congressional) | Phase 7 |
| 11   | Extend NewsAggregatorAgent with Equibles SEC full-text + insider trades | Phase 7 |
| 12   | InstitutionalSnapshot + MarketStructureData schemas; add as optional fields on ResearchBrief | Phase 7 |
| 13   | Update ResearchSynthesizerAgent prompt to use new fields when present | Phase 7 |

### Bottom Line

Integrate via MCP consumption - do not adapt the source code. Equibles is purpose-built to be consumed exactly the way you'd consume it. The C# codebase is not portable and the AGPL licence makes direct code adaptation legally risky for a private project.

The value proposition is strong and specific: the data signals Equibles provides (institutional positioning, insider activity, short structure, macro backdrop) are the exact inputs that separate a generic LLM-generated stock summary from something that reads like real sell-side research. For local models especially - which have no live data access at all - this is the difference between a useful research brief and a hallucinated one.

The integration fits cleanly into the existing architecture: one .mcp.json entry, one config.yaml flag, two agents extended with optional MCP calls, two optional schema fields. Minimal code churn; substantial output quality improvement.

You need to **download Equibles locally and run the project as is.** The integration is purely operational, not code-level:

git clone + docker compose up - Equibles runs as a local service on your machine. It starts scraping SEC/FINRA/FRED/etc. into its own PostgreSQL database automatically.

Your code never touches Equibles internals - you connect to it the same way Claude Desktop or Cursor would: as an MCP server at localhost:8081. You call its tools, get back data, done.

In OpenResearch, DataFetcherAgent and NewsAggregatorAgent gain a few extra `mcp.call("equibles", ...)` lines when the server is reachable - identical in pattern to how CompanyResearcherAgent already calls brave-search. Everything is gated behind `mcp.is_available("equibles")` so if Docker isn't running, the pipeline falls back silently to today's behaviour.

So the "integration" is really just:

- One entry in .mcp.json pointing at localhost:8081
- A few tool calls added to two existing agents
- Two optional fields added to ResearchBrief
- The Equibles codebase itself you treat as a black box - same as you treat yfinance or the Brave Search API. You don't modify it, you don't import it, you just run it.

### How to implement the integration changes now - update design.md, extend DataFetcherAgent, NewsAggregatorAgent, the stock schema, and the .mcp.json entry?

- Create .mcp.json with Equibles SSE entry
- Update config.yaml - add equibles section
- Update schemas/stock.py - add InstitutionalSnapshot + MarketStructureData
- Update agents/mcp_client.py - add Equibles MCP JSON-RPC transport
- Update agents/stock/data_fetcher.py - pull institutional, short, technical, congressional data
- Update agents/stock/news_aggregator.py - add SEC full-text search + insider trades via Equibles
- Update pipelines/stock_pipeline.py - wire MCPClient through to agents + synthesizer
- Update docs/design.md - reflect Equibles integration
