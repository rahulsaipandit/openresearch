# Technical Signals + Backtesting — Design Note

## Source

["AI Trading: Evaluating Large Language Models for Technical Market Analysis"](https://arxiv.org/abs/2607.15414) (Ntale, 2026).

### Original approach (paper)

Benchmarks five LLMs (GPT-4 Turbo, Claude 3 Opus, Gemini 1.5 Pro, Llama 3 70B, FinGPT) directly on four trading tasks: reading candlestick charts to identify patterns, generating buy/sell signals from those patterns, backtesting the resulting signals, and comprehending financial reports. Findings:

- GPT-4 Turbo and FinGPT both beat the S&P 500 benchmark in backtests; FinGPT (domain fine-tuned) wins on risk-adjusted return.
- All five models share the same failure modes: **numerical hallucination** (miscounting bars, inventing price levels), **context-window limits** on long OHLC series, and **degraded accuracy in sideways/range-bound markets**.
- Conclusion: LLMs are usable for trading, but only with careful problem structuring, rigorous backtesting, and domain-specific tuning — not by asking a general model to eyeball a chart and emit a signal.

A second, informal source (a promotional X.com post for a product called "Horizon AI," not a paper — treated as anecdotal, not evidence) describes a similar research → code → backtest → live → post-mortem → fine-tune loop and two practices worth keeping regardless of the source's promotional framing: **kill switches belong in code, never in a prompt**, and a strategy's expected outcome should be **written down before the backtest runs**, not fitted after the fact.

### How we adapted it

The core lesson — don't let an LLM do arithmetic on price series — is already this codebase's house style. [`TrendAnalystAgent`](../agents/stock/trend_analyst.py) and [`PortfolioOptimizerAgent`](../agents/stock/portfolio_optimizer.py) both compute their numbers deterministically and use the LLM only for narrative framing downstream. We're extending that same split to cover the two things the paper tested that this repo doesn't do yet: pattern/signal detection and backtesting.

| Paper's task | Paper's approach | Our approach |
|---|---|---|
| Candlestick pattern ID | LLM reads chart/OHLC text | Deterministic pattern rules (TA-Lib or equivalent) over OHLC data — no LLM in the loop |
| Signal generation | LLM emits buy/sell/hold from patterns it just read | Signals derived from the same deterministic indicators (RSI/MACD/Bollinger, already fetched via Equibles in Node 1) + pattern rules — rule-based, reproducible |
| Backtesting | LLM-generated signals backtested against history | Real backtest harness (vectorbt or a small custom engine) run against the deterministic signals, reporting annualized return, Sharpe, max drawdown vs. a benchmark |
| Financial report comprehension | LLM reads report, summarizes | Unchanged — this is exactly where our existing LLM agents ([`document_insights.py`](../agents/stock/document_insights.py), [`sec_qa.py`](../agents/stock/sec_qa.py), `research_synthesizer.py`) already sit; narrative synthesis is the one task an LLM is actually suited for |

Net effect: the LLM never touches a number in this path. It only narrates what the deterministic signal/backtest layer already computed — e.g. "RSI-based signal generated 3 buy triggers this year, backtested Sharpe 1.2 vs. S&P 500's 0.8" becomes an LLM-written sentence in the brief, not an LLM-computed figure.

## Proposed additions

- `agents/stock/signal_agent.py` — pure-numeric agent (no LLM call), same philosophy docstring as `TrendAnalystAgent`/`PortfolioOptimizerAgent`. Computes candlestick pattern flags + indicator-based signals (reuses RSI/MACD/Bollinger already available from Equibles in Node 1 when running; falls back to computing them locally from yfinance OHLC when Equibles isn't available).
- `agents/stock/backtest_engine.py` — runs the generated signals against historical price series, reports annualized return, Sharpe ratio, max drawdown, and benchmark comparison (S&P 500). Sealed out-of-sample split (e.g. last 20% of history held out) rather than fitting and testing on the same window.
- `schemas/stock.py` — new `SignalSet` (pattern name, trigger dates, direction) and `BacktestResult` (return, Sharpe, drawdown, benchmark_return) schemas, added as optional fields on `ResearchBrief`, same pattern as the Equibles `InstitutionalSnapshot`/`MarketStructureData` fields.
- `ResearchSynthesizerAgent` prompt gains the signal/backtest numbers as pre-computed facts to narrate, same as it already does for Equibles data.

## What this doesn't change

- The 5-node pipeline structure stays identical; this slots in as new Node 1 outputs, same as Equibles did.
- No LLM is added to the numeric path — consistent with the paper's own conclusion that numerical hallucination is the main failure mode to avoid.
- `depth="quick"` skips the backtest (it's the most expensive step), same pattern as other optional Node 1 work.

## Open question

Whether to use TA-Lib (C extension, wheel availability varies by platform) vs. a pure-Python pattern library for candlestick detection — needs a quick spike before committing to the dependency.
