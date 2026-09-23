# Kalman-Filtered Adaptive Pairs Trading — Design Note

## Source

[Livsun (@L1vsun), "How To Use Kalman Filters To Build Adaptive Pairs Trading Strategies"](https://rahul--pandit.leaflet.pub/3mw7hkuzacs2b) — an accessible walkthrough of using a Kalman filter to track a time-varying hedge ratio between two cointegrated assets, instead of a fixed-window OLS regression that goes stale when the relationship shifts.

Core model: `Y_t = alpha_t + beta_t * X_t + eps_t`, with `(alpha_t, beta_t)` treated as a hidden state evolving as a random walk (state equation) and a linear price relationship (observation equation). Standard progression in quant finance — moving from static/rolling OLS to state-space models is well-established (Ernest Chan's pairs-trading writeups use the same construction).

## Accuracy review

The high-level framing is sound, but the article's own reference implementation has several bugs that would prevent it from running correctly or being trustworthy in production:

| Issue | Problem |
|---|---|
| `spread` property returns `state_means[:, 0]` (the intercept), separately "corrected" in `get_spread` | A buggy property alongside a correct method breaks standard usage — callers using the property silently get the wrong value |
| Signal generation zeroes out exits, then `.ffill()`s over the zeros | The explicit exit signal gets wiped out by the forward-fill immediately after it's set — a genuine logic bug, not just a style issue |
| Z-scores from rolling/expanding historical std | The Kalman filter already computes its own uncertainty (`P_t\|t-1`) at every step; using a separately-computed rolling std ignores information the filter already has and introduces lag |
| Fixed `observation_covariance` (R) and `transition_covariance` (Q) | Market volatility is heteroskedastic; a fixed R makes the filter over-react in calm regimes and under-react in volatile ones |
| Cointegration tested once (Engle-Granger) at pair selection, then assumed permanent | Pairs decouple. A Kalman filter with a stale cointegration assumption will keep adjusting beta to chase price moves — a mean-reversion strategy silently becomes an accidental trend-follower |
| Half-life computed but never used to gate trading | The formula itself (`-ln(2)/ln(1+rho)` from `delta_S_t = a + rho*S_{t-1} + eps`) is actually consistent with the OU-process derivation `lambda = -ln(1+rho)/dt`, but reporting it without acting on it (e.g. skipping pairs whose half-life falls outside a sane trading window) wastes the diagnostic |
| Returns computed as `signal * (Y.pct_change() - beta * X.pct_change())` | Percent returns can't be subtracted across assets weighted by beta without accounting for actual position sizing and dollar exposure — not a valid P&L calculation for a dollar-neutral hedge |
| Backtest ignores slippage, execution delay, and short-borrow/locate fees | Reported Sharpe 2.12 / 12.3% annual return / -4.9% max drawdown would be meaningfully worse net of real trading frictions |

None of this undermines the core idea (state-space hedge ratio estimation over static OLS); it means the reference code needed a rewrite, not just a port.

## What was implemented

`agents/stock/pairs_trading.py` — `PairsTradingAgent`, pure numeric (custom 2-state Kalman filter in numpy, no `pykalman` dependency — avoids the exact "dimension mismatch across backend versions" class of bug the article's `pykalman` usage was exposed to), fixing each issue above:

- **Z-scoring**: `z_t = innovation_t / sqrt(H_t P_t|t-1 H_t^T + R_t)`, computed directly from the filter's own innovation and its variance at every step — no separate rolling std.
- **Adaptive R**: innovation-based adaptive estimation (Mehra, 1970) — an exponentially-forgotten estimate of `R` updated from each step's residual variance. This is a cheaper substitute for a full EM re-fit, which is the right tradeoff here because the filter is meant to be recomputed on demand or every few minutes (stateless, no persistent training), not fit once offline.
- **Cointegration re-checked every call**: Engle-Granger over the full lookback window, plus an Augmented Dickey-Fuller test on the recent spread window, so a broken-down pair is flagged (`cointegrated`, `stationary_now`) instead of assumed stable forever.
- **Half-life gates the signal**: computed from the same Kalman-filtered spread used for trading (not a separately-fetched raw price series); a pair with an undefined half-life (no mean reversion) or a half-life outside 1-20 days produces `signal: "flat"` with an explanatory warning, rather than a number nobody acts on.
- **Position sizing**: share quantities, `Q_y = capital / price_y`, `Q_x = beta_t * Q_y`, with sign flipped for long vs. short spread — not percent-change subtraction.
- Exposed as `POST /api/pairs-analyze` (`server.py`), surfaced in the desktop app as a new "Pairs" sub-tab (`desktop/src/panels/PairsTradingPanel.tsx`) with a manual "Analyze" button and an optional 5-minute auto-refresh, matching the source article's monitoring cadence.

## What was deliberately not implemented

This is a one-shot analysis tool, not a live trading system — same line drawn in [designStock_FactorDecompositionRMT.md](designStock_FactorDecompositionRMT.md): OpenResearch is a research tool, not an execution system.

- **No position tracking across calls.** The agent is stateless by design, matching the "fetch every 5 minutes or on demand" framing this was scoped under: every call re-fetches history and re-runs the filter from scratch, with no memory of a prior call. Concretely, this means `signal: "long_spread"` / `"short_spread"` means **"would enter here now"**, not **"you are currently in this trade."** There is no notion of "already in a long-spread position, now check the exit threshold" — the agent has no way to know a position exists. If you want exits to fire correctly against a remembered entry (rather than just re-evaluating entry thresholds every call), that needs an explicit position store (e.g. alongside `store/portfolio_store.py`) and separate entry/exit signal logic keyed off "am I flat or in a position" — a real, separate feature, not a natural extension of this one. Not built; flagging so it isn't assumed to exist.
- **No trade execution.** Sizing (`shares_y`, `shares_x`) is advisory output, not an order sent anywhere.
- **No slippage, execution delay, or short-borrow/locate fee modeling** in the sizing or signal output — the article's own backtest numbers (Sharpe 2.12, 12.3% annual, -4.9% max drawdown) would be optimistic net of these, and nothing here corrects for that because nothing here backtests at all; this is a live/current-state analysis, not a backtest.

## Bottom line

Implemented as an on-demand/polling analysis endpoint plus UI panel — not scoping-only, unlike the RMT note. The reference article's core state-space idea is legitimate; its reference code was not production-safe as written, and every fix above is a direct response to a documented bug in that code (see accuracy-review table).
