# Stock Dashboard UI — Design Note

## Source

A reference screenshot the user shared (a mocked-up stock-profile page: ticker header
with market cap/P/E/52-week range/dividend yield/volume/shares outstanding, a ratings
snapshot bar chart, a price-target ladder, an earnings countdown, and a bottom
"Opportunity Radar" section mapping sector themes to companies that benefit/are
pressured), plus [stocktaper.com](https://www.stocktaper.com/) as a second reference
point. The user asked whether we'd already built something like this and, if not, to
scope what it would take.

## Current state

**Status: all three of options/puts-calls analysis, earnings call summaries, and
Opportunity Radar are implemented** (see sections 1, 2, and 3 below).
Most of the rest of the screenshot's content already exists, just spread across
different panels rather than laid out like the mock:

- [`desktop/src/panels/StockPanel.tsx`](../../desktop/src/panels/StockPanel.tsx) — free-text
  query → `ResearchBriefView` (verdict, price target range, bull/bear case,
  fundamentals table, key risks, upcoming catalysts). This is the "latest news
  analysis" entry point.
- [`desktop/src/panels/DashboardPanel.tsx`](../../desktop/src/panels/DashboardPanel.tsx) —
  the closest existing match to the reference screenshot: enter a ticker, get a
  one-page overview (snapshot table, technicals, insider/congress trades, price
  chart, income statement, sentiment/outlook rail, institutional holders). Explicitly
  built "inspired by a reference screenshot the user shared" per its own header
  comment — this predates the current ask and should be extended rather than
  duplicated.
- [`desktop/src/panels/TrendPanel.tsx`](../../desktop/src/panels/TrendPanel.tsx) — 5-year
  price/volatility trend per ticker, plus a previous-year summary.
- [`desktop/src/panels/ComparisonPanel.tsx`](../../desktop/src/panels/ComparisonPanel.tsx) /
  `compareStocks()` — side-by-side two-stock comparison.
- [`desktop/src/panels/WatchlistPanel.tsx`](../../desktop/src/panels/WatchlistPanel.tsx) —
  watchlist capped at 20 tickers (`Watchlist (${items.length}/20)`).
- Insider transactions, congressional trades, and institutional (13F) holders are
  already fetched by `DataFetcherAgent._fetch_equibles_market_structure` /
  `_fetch_equibles_institutional` (`agents/stock/data_fetcher.py`) and already
  rendered in `DashboardPanel.tsx`'s left/right rails — gated on Equibles being
  available locally.

Not yet built: options/puts-calls volume + interpretation, the Opportunity Radar
sector-theme section, earnings call summaries, and ETF-vs-fund distinction within
institutional holders.

## Architecture constraint

Every new piece below follows the house rule now written up in `CLAUDE.md`/`AGENTS.md`:
**no LLM does math.** All numeric computation happens in plain Python, the same
pattern already used by `signal_agent.py` (deterministic candlestick/technicals) and
`volatility.py` (EWMA/GARCH) — compute first, LLM writes the one-paragraph
"what this means," never invents the number.

## Proposed additions

### 1. Puts/Calls volume + interpretation — implemented

**Data**: `yfinance` exposes `Ticker.option_chain(expiry)` for free — calls/puts
volume, open interest, implied vol, strike. No new paid key needed.

**New deterministic module** — `agents/stock/options_analyst.py`, same shape as
`signal_agent.py` (no LLM):
- Pull the nearest 2-3 expiries, aggregate call volume vs put volume → **put/call
  ratio**.
- Compare to the stock's own trailing-30-day average P/C ratio (needs a small
  rolling cache — SQLite table, one row/day) to flag *unusual* activity, not just an
  absolute number.
- Flag OI concentration at strikes far from spot (e.g. heavy call OI 20% above spot =
  bullish positioning bet) and IV skew (put IV >> call IV = downside hedging demand).
- Output a small structured object: `{ put_call_ratio, vs_30d_avg,
  unusual_call_activity, unusual_put_activity, iv_skew, dominant_strike_call,
  dominant_strike_put }` — pure numbers, no verdict.

**LLM's only job**: given that structured object, write 2-3 sentences translating
it — e.g. "Call volume is running 2.3x the 30-day average, concentrated at the $230
strike (7% above spot) — positioning consistent with bets on a move higher into the
Nov 18 earnings date, though put OI at $200 shows meaningful downside hedging too."
Template-adjacent narration, not a free-form prediction — same guardrail style the
other analyst agents already use.

**Plumbing**: new `OptionsData` type in `types.ts` / `schemas/stock.py`, new field on
`ResearchBrief.options`, new `DataFetcherAgent._fetch_options()` method, new card in
`DashboardPanel.tsx` next to Technicals.

### 2. Opportunity Radar (biggest lift) — final design, implemented

Fundamentally different from the rest of the app — cross-ticker/sector, not
single-ticker. Two approaches were considered; **Approach A (deterministic
batch job)** was chosen over **Approach B** (LLM proposes themes ad hoc from raw
headlines each page load) because B is non-deterministic and not
rerunnable/backtestable, conflicting with the code-as-source-of-truth principle
already established for this app (options analysis, backtesting, signals).

Approach A's three open sub-decisions are now resolved:

- **Universe: watchlist-driven, explicitly, for now.** The batch job scans exactly
  the tickers in the user's existing `WatchlistStore` (up to 20) rather than a
  separate, independently maintained sector-universe list. This is a deliberate
  scope decision, not an oversight: it means Opportunity Radar's coverage is only as
  broad as the watchlist — a sparse or narrow watchlist yields a thin radar. Trade-off
  accepted because it needs zero new configuration and zero new maintenance burden
  (reuses a store that already exists), versus building and curating a second ticker
  universe. Revisit if/when a user wants sector coverage beyond their own watchlist.
- **Storage: a JSON file store (`store/theme_store.py`), not SQL.** Same atomic-write
  pattern as `AlertStore`/`WatchlistStore`/`OptionsHistoryStore` — there is no SQL
  database anywhere else in this app, so introducing one for a single feature would
  be inconsistent with everything around it. Snapshots are keyed by date so a future
  "yesterday vs. today" diff view is possible without a storage change.
- **Trigger: a plain `asyncio` background loop in `server.py`'s lifespan**, same
  mechanism as the existing alert poller (`_alert_poll_loop`) — not a job-scheduling
  framework (Celery, cron, Inngest). Runs once daily instead of every 5 minutes;
  same justification as `alert_store.py`'s own docstring for why the alert poller
  doesn't warrant heavier infrastructure. A manual refresh endpoint is also exposed
  for on-demand testing.

Computation pipeline (all deterministic except the one narration step, per the
narrate-not-decide pattern used everywhere else in this codebase):
1. Pull headlines for each watchlist ticker via the existing `NewsAggregatorAgent`.
2. Extract candidate theme phrases from headline text (regex-based capitalized
   phrase extraction — no TF-IDF/embedding library added as a new dependency, since
   this repo doesn't have scikit-learn and a lightweight heuristic is enough for
   watchlist-scale headline volume).
3. Score each phrase deterministically: frequency × recency-weighted × distinct
   watchlist-ticker count (a source-diversity proxy) → "Theme Strength."
4. Classify each mentioning ticker's stance (benefit / pressured / mentioned) with a
   small deterministic positive/negative keyword lexicon per headline — a heuristic,
   documented as such in code, not a sentiment model.
5. LLM writes one paragraph per surviving theme, grounded only in the evidence
   headlines already collected — same guardrail as the options/backtest narration.

Deliberately **not** included: a "Discovery Gap" or "Confidence" score like the
reference screenshot's mock — neither is derivable from real data available here
without fabricating a number, and this app's standing principle (see
`DashboardPanel.tsx`'s own header comment) is to omit sections with no real data
source rather than invent one.

New: `store/theme_store.py`, `agents/stock/opportunity_radar.py`,
`schemas/opportunity_radar.py`, `desktop/src/panels/OpportunityRadarPanel.tsx`,
endpoints `GET /api/opportunity-radar` (reads the latest stored snapshot — fast, no
LLM call on page load) and `POST /api/opportunity-radar/refresh` (manual trigger).

### 3. Earnings call summaries — implemented

#### Final design

**Alpha Vantage is the primary transcript source** — its `EARNINGS_CALL_TRANSCRIPT`
endpoint was confirmed live (not just from docs) to work on the free tier: a call
with the public `demo` key against `IBM` returned a full transcript with speaker
names, titles, and per-turn sentiment; the same call against a non-demo ticker
returned a message pointing to "claim your free API key," not a paid-upgrade prompt.
This reuses the `alpha_vantage_key` already configured for
`INCOME_STATEMENT`/`BALANCE_SHEET` — zero new cost, zero new integration surface.
**Equibles enriches when its MCP server is running** (`get_earnings_call_transcript`
— verified speaker roles, the linked 8-K, pre-extracted guidance statements), same
"Equibles enriches when available, core pipeline works without it" pattern already
used for institutional/short-interest data. Neither source is mandatory; the feature
degrades to unavailable (not fabricated) if Alpha Vantage has no key configured.

#### Alternatives considered and rejected

| Option | Why not |
|---|---|
| **API Ninjas** | No free tier for transcripts at all. Raw text requires the Developer tier ($39/mo annual, $59/mo monthly); structured extras (summary, sentiment, guidance) require Business tier ($99/mo annual, $149/mo monthly). |
| **Financial Modeling Prep** | Transcripts only on the $149/mo Premium plan. |
| **Finnhub** | Transcript/live-call endpoints are explicitly premium; no free tier, even though other Finnhub datasets do have one. |
| **EarningsCalls.dev** | Free tier is preview-only (250-char snippets, 50 req/month); full transcript text requires the $24.99/mo Pro plan. |
| **Roic AI** | Genuinely free on every tier (5 req/min, 2-year history cap) — a real option, but would have been a brand-new integration surface with no existing client code in this repo. Not needed once Alpha Vantage was confirmed working; worth revisiting only if Alpha Vantage's coverage proves too thin. |
| **Scraping Seeking Alpha / Motley Fool** | Both post full transcripts fast (sometimes same-day), which is genuinely appealing for freshness — but both explicitly prohibit scraping/automated access in their terms of service, and a scraper breaks silently whenever either site's markup changes. That fragility conflicts with this codebase's reproducibility principle (see `docs/designStock_TechnicalSignalsAndBacktesting.md`'s "kill switches belong in code" note): a transcript source that changes shape without warning and returns wrong or truncated data silently is worse than one that just returns an error. Rejected on both legal and reliability grounds, not revisited. |
| **SEC EDGAR 8-K exhibits** | A real free/legal option worth flagging separately — see below. Not implemented now because coverage is inherently partial, but it's the most promising future fallback specifically because this repo already has EDGAR infrastructure to extend. |
| **Hugging Face academic transcript datasets** | Static snapshots under CC BY-NC licenses — wrong shape for a live "summarize the quarter that just reported" feature (stale by definition, and the non-commercial license is a poor fit for a tool that may see production/commercial use). Fine for backtesting/research use, not for this feature. |

#### SEC EDGAR 8-K exhibits — noted, not implemented

Some companies furnish the full call transcript (or detailed prepared remarks) as an
`EX-99.1`/`EX-99.2` exhibit to an 8-K under Item 2.02/7.01 — legally unambiguous,
free, and queryable via EDGAR's full-text search API (EFTS) for "earnings call" /
"conference call" within 8-K filings. Confirmed this is real (not just a theoretical
Reddit claim) against live EDGAR filings — e.g. Liquidity Services' and
Overstock.com's 8-Ks include verbatim call transcripts as exhibits. It is **not
universal** — many companies file only the press release as Exhibit 99.1 and skip
the transcript — so it can't be the primary source, but it's a genuine fallback for
tickers Alpha Vantage doesn't cover. This repo already has SEC EDGAR
infrastructure (`agents/stock/sec_ingest.py`, EdgarTools, used by `sec_qa.py`) that
could be extended to search 8-K exhibits for transcript-shaped text as a third
fallback tier. Tracked as future work, not built — the coverage gain needs to be
weighed against the added parsing complexity (exhibits are unstructured
HTML/text, not the clean JSON Alpha Vantage returns) before it's worth doing.

#### Shipped

`agents/stock/earnings_call_summarizer.py` (transcript fetch + LLM summarization
into highlights/guidance/management-tone/notable-Q&A — the one LLM agent in this
codebase that operates on a source document rather than pre-computed numbers, which
is fine per the "no LLM does math" rule since summarization isn't arithmetic or
decision-making), `EarningsCallSummary` schema, `/api/stock-earnings-call` endpoint,
and a lazy-loaded card in `DashboardPanel.tsx` (fetched on demand via a button, not
alongside the rest of the dashboard, since transcript fetch + summarization is a
heavier separate LLM call).

### 4. Already built, needs surfacing/reorganizing only

- **Insider + Congress trades** — already in `DashboardPanel.tsx` (Equibles-gated).
- **Institutional/ETF holders** — already in `DashboardPanel.tsx` via 13F; doesn't
  currently distinguish ETF vs. active fund — would need a `holder_type` field
  checked/added on the Equibles payload if not already present.
- **Side-by-side comparison** — `ComparisonPanel.tsx` / `compareStocks()`.
- **20-stock watchlist** — `WatchlistPanel.tsx`.
- **5-year trend + previous-year summary** — `TrendPanel.tsx`.
- **Detailed fundamentals** — exists via `ValuationSummary`; could deepen with more
  Alpha Vantage line items if more than P/E/EPS/margins is wanted.

### 5. Header layout

`DashboardPanel.tsx`'s current `stat-row` (verdict, price, target, sentiment) is a
subset of the reference screenshot's top bar (market cap, P/E, 52-week range,
dividend yield, volume, shares out, ratings snapshot bars, price-target ladder,
earnings countdown). All the underlying numbers already exist in
`fundamentals`/`price_data` — this is a pure layout change to `DashboardPanel.tsx`,
no new backend work.

## Phasing

1. ~~Header layout rework + options/puts-calls card~~ — **done.**
2. ~~Opportunity Radar (Approach A)~~ — **done.**
3. ~~Earnings call summaries~~ — **done.**

## Open questions

- Whether Equibles' 13F payload already carries a holder-type (ETF vs. fund) field —
  needs checking against a live Equibles instance before scoping #4's ETF split.
- A prediction-model layer (e.g. XGBoost trained on price/fundamentals/technicals,
  queried by the LLM for strategic narration) was also discussed as a longer-term
  direction, alongside generalizing `agents/stock/backtest_engine.py` (currently
  single-ticker, 1-year lookback, `SignalAgent`-trigger-specific) to support
  multi-period historical simulation and a pluggable position-series source. Tracked
  as future work, not scoped here — see conversation history for the gap analysis
  against `backtest_engine.py`'s current capabilities.
