# Initial Research Collection — Finance AI Feasibility

Raw research notes distilled into a reference doc. This captures the *why* behind `requirements.md`: what OpenResearch already has, what other tools/posts were reviewed, and what's actually worth reusing. Constraints: Windows machine, LM Studio with an RTX 4070 (~10GB VRAM) for local inference, so avoid large models — prefer compact/quantized models and retrieval-driven analysis over model scale.

## 1. OpenResearch — What It Already Has

`agents/stock/` is a working 5-node async pipeline (plain Python, not LangChain agents), wired together by `pipelines/stock_pipeline.py` and exposed via `POST /api/stock-research` and the `run_stock_research` MCP tool:

| Node | File | What it does |
|---|---|---|
| 1 | `data_fetcher.py` | Yahoo Finance (free), Alpha Vantage (income statement/balance sheet, key required), Polygon.io (earnings calendar, key required), and **Equibles** (self-hosted MCP/Docker service, `depth="full"` only) for 13F institutional holdings, FINRA short interest, SEC fails-to-deliver, insider trades, congressional trading, and technicals. Equibles calls fail silently if the service isn't running. |
| 2 | `news_aggregator.py` | NewsAPI headlines (key required), SEC EDGAR filing index via CIK lookup (free), plus Equibles SEC full-text search excerpts and Form 3/4 insider transactions. |
| 3 | `fundamentals_analyst.py` | LLM call → `ValuationSummary` pydantic model, with a rule-based fallback if JSON parsing fails. |
| 4 | `sentiment_analyst.py` | LLM call → `SentimentSummary` (tone, catalysts, risks, headlines). |
| 5 | `research_synthesizer.py` | Final LLM synthesis → `ResearchBrief` (verdict, price target, bull/bear case, risks, catalysts, sources), embedding Equibles sub-schemas (`InstitutionalSnapshot`, `MarketStructureData`, `TechnicalIndicators`) when available. |

**Orchestration:** Custom, not LangGraph-based, despite `langgraph` being a listed dependency. Per `docs/design.md`, LangGraph was only used as a "pattern basis" during design and then replaced with plain async Python pipelines per domain (stock/board/interview/realestate) — no shared graph engine. `orchestrator/graph.py` is unrelated legacy code from an older ML-experiment pipeline.

**UI:** None exists yet. `server.py` (FastAPI, `localhost:7842`) exposes REST endpoints and `mcp_server.py` exposes the same pipelines over MCP stdio. `docs/design.md` describes a planned-but-unbuilt Chrome Extension (Phase 5) with one panel per vertical. `docs/Finance-AI/finance` (Next.js/Supabase) and `docs/Finance-AI/AI-Trader` are untracked, separately-cloned reference repos used for research only — not part of OpenResearch itself.

**Product scope:** OpenResearch is multi-vertical — Stock Research, Executive Board (6 AI board members), Interview Prep, Real Estate — sharing infra (`LLMClient`, FastAPI server, pydantic schemas) but domain-isolated agents/pipelines.

### Requirement coverage vs. what's built

| Requirement | Status |
|---|---|
| Fundamentals breakdown | ✅ `fundamentals_analyst.py` |
| Insider/Congress trade alerts | ✅ via Equibles — **blocked until Equibles is set up** (not running yet) |
| Institutional (13F) holdings | ✅ via Equibles — same blocker |
| News + sentiment | ✅ NewsAPI + SEC EDGAR + LLM sentiment |
| Final synthesis brief | ✅ `research_synthesizer.py` |
| Stock comparison (2-ticker) | ❌ not present |
| Watchlist (20 stocks) | ❌ not present |
| Earnings call summaries | ❌ not present (news/filings only, not transcripts) |
| 5-year + prior-year trend view | ❌ not present |
| ETF-specific ownership breakout | ❌ not present (13F is institutional, not ETF-specific) |
| Personal memory/context system | ❌ not present |
| Desktop UI | ❌ none exists anywhere |

**Bottom line:** the backend is materially further along than expected — a working LLM synthesis pipeline with real data sources already wired. The actual gaps are: stock comparison, watchlist, earnings-call summarization, trend charts, ETF-specific ownership, the personal memory system, and building a UI at all (decided: a shared Tauri shell across all four verticals — see `requirements.md`).

### Orchestration framework question (LangChain?)

Recommendation: **don't reintroduce LangChain/LangGraph for orchestration.** `docs/design.md` already evaluated and deliberately dropped it in favor of plain async pipelines — the current agents already do the two things a LangChain chain would give (structured LLM calls parsed into Pydantic, with a deterministic fallback) without the abstraction/version-churn overhead. Reversing that would cost complexity for no new capability.

Where an external idea *is* worth adopting: a deterministic, citation-preserving document parser (see LiteParse, §4) for the earnings-call/filings summarization gap — that's a parsing concern, not an orchestration concern, and plugs directly into the existing "evidence-backed, source-cited" requirement.

---

## 2. Reference Apps Reviewed

Two separately-cloned repos under `docs/Finance-AI/` were compared as architecture references (not integrated into OpenResearch):

### AI-Trader
Python trading research/agent framework. LangChain + MCP (`langchain_mcp_adapters`) for tool-driven agents; CLI-driven, with local MCP services (`agent_tools/start_mcp_services.py`) and market-specific rule handling (A-share lot sizes, cash checks). **Pros:** reproducible historical simulation, multi-agent parallel runner, tool-oriented architecture. **Cons:** heavy local infra, complex `.env`/runtime-state setup, no web UI, tight LangChain/MCP coupling, file-based logging. Best fit: experimental autonomous trading/backtesting, not what we're building.

### finance (Next.js/Supabase app)
Full-stack chat-driven financial research product. Uses `ai` SDK, local LLM providers (Ollama/LM Studio), OpenAI, Valyu search API, Daytona sandbox for code execution, Supabase auth, Polar billing. **Pros:** modern web architecture, local-dev/production separation (SQLite fallback, no-Supabase dev mode), rich tool ecosystem (charts, CSV, Python execution), local LLM support. **Cons:** heavy external-vendor dependency (Valyu, Daytona, Supabase, Polar), high operational surface, not itself a Stocktaper clone — no dedicated watchlist component or Congress-trade-alert feature found in its source. Best fit: architecture/tool-design inspiration for the chat + chart layer, not directly reusable given the vendor coupling and that OpenResearch already has its own FastAPI backend.

**Verdict:** neither repo is a drop-in fit. AI-Trader confirms the "custom pipeline over LangChain" call is reasonable for a research (not live-trading) product, and has no UI at all (`scripts/start_ui.sh` just serves static docs over HTTP — not an app). `finance` is useful mainly as a UX/tool-design reference for chat, charts, and local-LLM wiring — **specifically**: a multi-series chart component (`financial-chart.tsx`), inline-citation markdown rendering (`citation-text-renderer.tsx`), a tabular CSV view, generic content dialogs, and a session-sidebar + streaming-response layout. Its agent orchestration (`api/chat/route.ts`, `lib/tools.ts`) and vendor plumbing (Supabase auth, Polar billing, Daytona sandbox, Valyu search) are explicitly *not* reused — that's what our own FastAPI backend already replaces.

**Note:** `docs/Finance-AI/AI-Trader/` and `docs/Finance-AI/finance/` are throwaway sample code kept only for this analysis — they will be deleted once implementation starts. The concrete frontend component requirements distilled from this review are captured independently in `requirements.md`'s "Frontend Component Requirements" section, so nothing is lost when the sample repos go away.

---

## 3. Open-Source Finance Repos Evaluated

*(Verified 2026-08-01 against primary sources — corrections from the original pass noted inline.)*

| Repo | License | Verdict |
|---|---|---|
| [EdgarTools](https://github.com/dgunning/edgartools) | MIT ✅ verified | **Best fit for SEC/filings/insider/ownership.** Confirmed: typed filing objects, XBRL financials, Form 4 insider trades, 13F holdings as structured objects, built-in MCP server. Good as a fallback/supplement to Equibles for the same data. |
| [OpenBB](https://github.com/OpenBB-finance/OpenBB) | **AGPLv3** ⚠️ correction | Originally assumed permissive — it's actually copyleft with network-use (SaaS) obligations. ~71k stars (higher than the "50K+" originally cited). Local LLM/agent hooks confirmed via MCP + `agents-for-openbb`. **Do not bundle/import directly without legal review** — treat as architecture/data-source inspiration only. |
| [FinanceToolkit](https://github.com/JerBouma/FinanceToolkit) | MIT ✅ verified | Strong fit for ratios/valuation/risk metrics. "200+" is metrics overall (ratios + risk + technical + economic indicators combined), not 200+ ratios alone — a mild overstatement in the original summary, but the underlying scope (80+ ratios, DuPont, WACC, Altman Z-Score, VaR, CDaR) is real and usable directly for the trend-analysis/comparison features. |
| [OpenTerminalUI](https://github.com/Hitheshkaranth/OpenTerminalUI) | Not re-verified | Claimed: React/TS frontend + FastAPI backend + LM Studio support — closest architecture match to our target stack. Treat as inspiration only until independently checked. |
| [ValueCell](https://github.com/ValueCell-ai/valuecell) | Apache 2.0 ✅ verified real | Not hallucinated — ~11k stars, 430 commits, active, downloadable builds. Orchestrator/agent-separation pattern (central controller for planning/memory/routing + specialized agents via A2A protocol) is legitimate and could inform how the shared Tauri shell talks to OpenResearch's per-domain pipelines. **Correction:** its Strategy Agent is crypto-exchange-focused (Binance/OKX/Hyperliquid), not general equities — useful for the orchestration pattern only. |
| [stock-analyzer-bot](https://github.com/Pranav082001/stock-analyzer-bot) | No license file | 134 stars, hobby project, genuinely small (17 commits). **Correction:** Streamlit is listed as a planned improvement, not built — it currently runs as LangChain + OpenAI function-calling with no UI at all. Useful only as a minimal prompt-pattern reference; don't reuse code without checking with the author given the missing license. |
| [Qlib](https://github.com/microsoft/qlib) (Microsoft) | Not re-verified | Quant research/backtesting ML platform. Optional/future — overkill for an MVP research assistant. |
| [LEAN](https://github.com/QuantConnect/Lean) (QuantConnect) | Not re-verified | Institutional-grade algo trading/execution engine. Optional/future — only relevant if we add live execution, not research. |
| [Ghostfolio](https://github.com/ghostfolio/ghostfolio) | Not re-verified | Private wealth/portfolio dashboard. Useful only as watchlist/portfolio UI inspiration. |
| [FinceptTerminal](https://github.com/Fincept-Corporation/FinceptTerminal) | AGPL-style, restrictive | Avoid direct reuse — native C++/Qt, far from the Python + Tauri target, and licensing risk for any commercial use. UX inspiration only. |
| [Neuberg](https://github.com/KoNananachan/Neuberg) | BSL | Avoid direct reuse — BSL license, large web-terminal scope mismatched to our target. UI/panel inspiration only. |
| FinRobot | Unreachable | Could not verify via README fetch in the original pass — not a strong candidate until checked directly. |

### Practical takeaway
- Best reuse candidates: `EdgarTools` (fallback/supplement to Equibles), `FinanceToolkit` (ratios/valuation layer).
- Reference/inspiration only, not import: `OpenBB` (license), `OpenTerminalUI` (architecture), `ValueCell` (orchestrator pattern), `Ghostfolio` (watchlist UX).
- Avoid: `FinceptTerminal`, `Neuberg` (license/complexity).
- Optional/future: `Qlib`, `LEAN` (only if quant backtesting/execution becomes in-scope).

---

## 4. External Posts & Articles Reviewed

### Two Reddit posts (r/Wallstreetbetsnew, r/ChatGPTPromptGenius)
Both trace to blog posts by **Austin Starks, founder of NexusTrade**, cross-posted to Reddit — not organic community writeups. Verified against the primary blog articles (Reddit threads themselves were unreachable via fetch). Core technical claims hold up and are reasonable engineering advice:
- Generic LLMs rely on stale training data and hallucinate financial facts — don't treat them as a market oracle.
- The fix is augmenting the model with real-time data + structured prompts/function-calling, not just prompting harder.
- Natural-language finance questions are ambiguous ("what stocks are similar to Tesla?") — need precise, structured queries (SQL/API calls) rather than asking the model to guess facts directly.

Both posts are explicitly promotional for NexusTrade (multiple CTAs, embedded product links). Treat the technical framing as valid vendor-perspective advice, not independent consensus — and don't cite "Reddit pushback" since the actual comment threads couldn't be verified.

**Relevance to us:** validates the existing pipeline design (real data → structured LLM output → cited synthesis) rather than suggesting anything new.

### Trading-R1 (financial-domain fine-tuned model)
A 4B-parameter model trained via a 3-stage pipeline (Structure → Claims → Decision) using SFT + RL (group relative policy optimization) + distillation from larger models, tested on NVDA/AAPL/AMZN/META/MSFT/SPY. Strong design ideas worth borrowing conceptually (not the model itself, which isn't something we'd fine-tune ourselves):
- **Strict thesis structure** — separate sections for market data, fundamentals, sentiment — mirrors what `ResearchBrief` already does.
- **Evidence-linked claims** — every claim must cite a source/number from context — directly reinforces the "no claim without source" principle we want for earnings-call/filings summaries.
- **Watch-outs:** narrow training scope (14 tickers, large-cap US tech-heavy), reward-shaping risk, and label brittleness across market regimes — not directly applicable since we're not training a model, but a reminder to keep verdicts (`Strong Buy`...`Strong Sell`) grounded in explicit, cited evidence rather than vibes.

**Relevance to us:** reinforces evidence-grounding as a design principle already present in `research_synthesizer.py`; no code/model to reuse.

### ValueCell (multi-agent platform)
Confirmed real (see §3 table). Orchestrator separates planning/memory/routing (central controller) from specialized agents (DeepResearch, Strategy, News) communicating over an A2A-style protocol, with streaming partial responses and human-in-the-loop correction. **Relevant pattern:** if the Tauri shell ever needs a shared orchestrator across the four OpenResearch verticals (rather than each panel calling its own endpoint independently), ValueCell's separation-of-concerns model is a reasonable reference. Not a reuse candidate for code (crypto-focused Strategy Agent, different stack).

### LiteParse / LlamaIndex due-diligence blog
A free, open-source, **model-free** (deterministic, non-LLM) document parser that extracts text from complex financial PDFs and returns citations as exact bounding-box references — enabling "source page X, section Y" citations in agent output. Not independently re-fetched/verified this pass; treat the specific claims with the same skepticism applied elsewhere until checked directly.

**Relevance to us:** directly useful for the earnings-call/filings summarization gap (#5 in requirements). A deterministic parser with citation metadata would feed structured, source-linked text into a new earnings-summarizer agent (or extend `fundamentals_analyst.py`), reinforcing the auditability requirement already stated in `requirements.md` without needing an LLM-based extraction step that could hallucinate document structure.

### Stocktaper.com (named target reference)
Confirmed real, live product ($7.99/mo or $63/yr, 7-day free trial). Verified sections: fundamentals ("Decoded"), watchlist/earnings/insider alerts, Congress-trade tracking, 1v1 stock comparison, sector "Radar." **Notably absent:** no distinct 5-year trend view or ETF-specific ownership breakdown was found — meaning two of our target requirements (#7, and the ETF half of #6) go *beyond* what the named reference product itself offers. These are genuine differentiators to build, not just feature parity.

### Stock Analyzer Bot (Pranav082001) — hobby reference
See §3 for the corrected verdict (no built UI, LangChain + OpenAI function-calling only). Useful only as a minimal example of the "extract ticker → fetch data → LLM analysis with positives/negatives" flow — a simpler version of what `agents/stock/` already does more thoroughly.

---

## 5. Net Takeaways

1. **Don't rebuild the pipeline** — `agents/stock/` already covers fundamentals, insider/Congress trades, and institutional holdings (once Equibles is running).
2. **Don't adopt LangChain/LangGraph** — the custom pipeline decision in `docs/design.md` is sound and already validated by comparison against AI-Trader's more brittle LangChain/MCP coupling.
3. **Do set up Equibles** before building UI panels for insider/Congress/13F data — it's the single blocker on three requirements.
4. **Do consider a deterministic document parser** (LiteParse-style) for the earnings-call/filings summarization gap, for auditability.
5. **Do treat 5-year trend view and ETF-specific ownership as real differentiators** — Stocktaper itself doesn't have them.
6. **Do build the Tauri shell as shared infrastructure** across all four verticals, not stock-only — see `requirements.md` for the architecture decision.
7. **License hygiene:** avoid importing OpenBB (AGPLv3), FinceptTerminal, or Neuberg directly into a codebase we intend to keep closed/personal; EdgarTools and FinanceToolkit (both MIT) are safe to depend on directly if needed.
