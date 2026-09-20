# Research: vectorbt + "Turn-of-the-Month" Calendar-Effect Strategy

Source: [polakowo/vectorbt](https://github.com/polakowo/vectorbt) (the backtesting library used), plus a walkthrough of a specific calendar-effect strategy built on it.

## The strategy: "turn-of-the-month" flow effect

This is a **calendar-effect strategy**, not a price-pattern or fundamentals strategy — it trades purely off the day-of-month, on the premise that flows (payroll investing, month-end institutional rebalancing, etc.) create a recurring seasonal drift around month boundaries, independent of any indicator computed from price. Concretely, from the code walked through:

1. **Data**: daily closes for a single ticker (TLT — the 20+ year Treasury ETF, a classic subject for flow-effect studies) via `vbt.YFData.download(...).get("Close")`.
2. **Signal construction**: four boolean signal series (`short_entries`, `short_exits`, `long_entries`, `long_exits`), built with `pd.DataFrame.vbt.signals.empty_like(close)` and populated purely from calendar position:
   - **Short entry**: first trading day of each new month — detected via `~tlt.index.tz_convert(None).to_period("M").duplicated()` (the first occurrence of each month-period is `False` under `.duplicated()`, so `~` flags it).
   - **Short exit**: 5 trading days after each short entry (`short_entries.shift(5)`).
   - **Long entry**: 7 calendar days *before* each short-entry date, via `short_entries.shift(-7)` — i.e. positioned near each month's end.
   - **Long exit**: 1 day before that, via `short_entries.shift(-1)`.

   The net effect: short the first ~5 days of the month, flat mid-month, long the last ~7 days of the prior structure — a systematic, recurring pattern with **no market data in the entry/exit logic at all**, just calendar arithmetic on the trading-day index.
3. **Simulation**: `vbt.Portfolio.from_signals(close=close, entries=long_entries, exits=long_exits, short_entries=short_entries, short_exits=short_exits, freq="1d")` — a single call simulates the full long/short cycle (note `entries`/`exits` here are the *long*-side signals; `short_entries`/`short_exits` handle the short side separately, so all four boolean masks built in step 2 feed directly into one `Portfolio` object). `pf.stats()` then returns the full tear-sheet (total return, benchmark return, Sharpe/Sortino/Calmar, max drawdown, win rate, profit factor, per-trade stats — the same metric set shown in vectorbt's own README example above), and `pf.plot().show()` renders an interactive equity-curve/drawdown chart. No manual position-tracking loop or return-series bookkeeping needed — that's the "vectorized" part of vectorbt's pitch, and it's a noticeably shorter path to a full tear sheet than this project's own hand-rolled `BacktestEngine._position_series`/`_sharpe`/`_max_drawdown` methods.

This is a real, well-studied phenomenon in quant finance (the "turn-of-the-month effect"), but it is a pure seasonality bet — its edge, if any, depends entirely on whether the historical flow pattern persists, not on anything the strategy "understands" about the asset.

## vectorbt — the library

From [README.md](https://github.com/polakowo/vectorbt/blob/master/README.md):

- **What it is**: a vectorized backtesting framework built on pandas/NumPy/Numba (with an optional Rust engine), designed to backtest thousands of parameter combinations or strategy variants at once instead of looping bar-by-bar — "packs thousands of configurations into NumPy arrays... turning hours of grid search into seconds."
- **Feature set**: built-in data access (`vbt.YFData` wraps yfinance), signal generation/masking utilities (`.vbt.signals.empty_like`, crossovers, etc.), a full `Portfolio` simulation object (`from_signals`, `from_holding`, `from_random_signals`) with trade/drawdown/performance analytics (Sharpe, Sortino, Calmar, Omega, profit factor, win rate, etc. — considerably more metrics than this project's own `BacktestEngine`), indicator integrations (TA-Lib, Pandas TA), walk-forward optimization tooling, and interactive Plotly visualization.
- **This is the open-source "community edition"**; a paid **VectorBT PRO** tier adds parallelization, portfolio optimization, pattern recognition, limit orders, leverage, and more.
- **License**: Apache 2.0 **with Commons Clause** ([LICENSE.md](https://github.com/polakowo/vectorbt/blob/master/LICENSE.md)) — free to use, modify, and even redistribute, but you may not **sell** a product or service "whose value derives, entirely or substantially," from the software itself. This is not a copyleft restriction on your own code, but it does mean vectorbt can't be repackaged as a paid backtesting-as-a-service offering built primarily around it. For OpenResearch — an internal research tool, not a product sold as "backtesting via vectorbt" — this license is not a blocker, but it's worth flagging since it's stricter than the plain Apache 2.0 used by TensorTrade ([docs/researchTensorTrade.md](researchTensorTrade.md)) or MIT used by Kronos ([docs/researchKronos.md](researchKronos.md)).
- **Dependencies**: pandas, NumPy, Numba (JIT), optional Rust engine, optional TA-Lib/Pandas-TA. Lighter than TensorTrade's TensorFlow+Ray stack, comparable in weight to what's already in this project (numpy, pandas already present; adds Numba).

## Relevance to OpenResearch's Stock feature

Two separate things to weigh here:

**1. The turn-of-the-month strategy itself** is a new *signal type* — pure calendar seasonality, distinct from the deterministic candlestick-pattern + RSI/MACD/Bollinger signals [`SignalAgent`](../agents/stock/signal_agent.py) already generates (see [docs/designStock_TechnicalSignalsAndBacktesting.md](designStock_TechnicalSignalsAndBacktesting.md)). It would be cheap to add as another rule-based trigger source — it needs nothing but a trading-calendar index, no new data source, no LLM, consistent with the existing "no LLM touches a number" design philosophy. Worth a small spike if calendar effects are of interest, independent of whether vectorbt itself gets adopted.

**2. vectorbt as a backtesting engine** would be a **replacement candidate** for [`agents/stock/backtest_engine.py`](../agents/stock/backtest_engine.py), which is currently a small hand-rolled engine (~140 lines: annualized return, Sharpe, max drawdown, single-signal-set position simulation, sealed 20% out-of-sample window). That file's own docstring already flagged this exact tradeoff — the original design note ([docs/designStock_TechnicalSignalsAndBacktesting.md](designStock_TechnicalSignalsAndBacktesting.md)) listed "vectorbt or a small custom engine" as the two options and the custom engine was what actually got built. Reasons to reconsider now vs. then:
   - **For vectorbt**: far more metrics out of the box (Sortino, Calmar, Omega, profit factor, trade-level stats), proper multi-asset/parameter-sweep support if the Stock feature ever wants to compare signal variants, and it's already the tool used in the walkthrough you're reviewing.
   - **Against**: the current custom engine is small, fully understood, has no license caveats, and already does what `ResearchBrief`'s `BacktestResult` schema needs (return/Sharpe/drawdown/OOS window) — swapping it in would be a moderate refactor (new dependency, re-mapping vectorbt's richer `Portfolio.stats()` output back onto the existing `BacktestResult` schema in [schemas/stock.py](../schemas/stock.py)) for metrics the research brief doesn't currently surface to the user.

**Recommendation:** the calendar-effect signal idea is a reasonable, low-cost addition to `SignalAgent` if calendar seasonality is a signal type you want covered — happy to spike it. Swapping the backtest engine to vectorbt is a larger, separate decision (new dependency + Commons Clause license to note + schema remapping) that trades engine simplicity for a richer metrics surface not yet asked for; I'd hold off unless the brief needs those extra metrics (Sortino/Calmar/trade-level stats) specifically.
