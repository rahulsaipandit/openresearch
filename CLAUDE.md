# CLAUDE.md

Guidance for Claude Code (and other AI assistants) working in this repo.

## Architecture principles

### No LLM does math

All numeric computation — price/return calculations, technical indicators, volatility
models, factor decomposition, options metrics, backtests, ML predictions — happens in
plain Python (numpy/pandas/scipy/statsmodels/etc.), never inside an LLM prompt.

The LLM's role is narration: it receives already-computed structured output and writes
the plain-English interpretation. It never derives the numbers itself.

Existing examples of this pattern:
- `agents/stock/signal_agent.py` — deterministic candlestick pattern/signal detection, no LLM
- `agents/stock/volatility.py` — EWMA/GARCH volatility, computed then handed to the LLM to interpret
- `agents/stock/factor_decomposition.py` — PCA/RMT factor analysis, computed then narrated

Apply this to new work the same way: build the calculation as a standalone
deterministic module/function first, and only pass its output to an LLM call if you
need a natural-language summary of it.

### No LangChain without checking first

This repo uses `langgraph` for agent orchestration and the raw `anthropic`/`openai`
SDKs directly — not LangChain. Don't add LangChain (or swap in another orchestration
framework) without checking with the user first; alternatives should be weighed
against what's already in place.
