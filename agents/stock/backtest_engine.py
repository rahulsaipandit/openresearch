"""
BacktestEngine — runs SignalAgent's triggers against historical prices.

Source reference: Ntale, "AI Trading: Evaluating Large Language Models for
Technical Market Analysis" (2026), https://arxiv.org/abs/2607.15414 — the
paper's four eval tasks are pattern ID, signal generation, backtesting, and
report comprehension; this module is the deterministic backtest counterpart
to its (LLM-generated, occasionally hallucinated) backtest step. See
docs/designStock_TechnicalSignalsAndBacktesting.md for the full design note,
including why the split from SignalAgent matters.

Pure numeric agent, no LLM call — same philosophy as TrendAnalystAgent,
PortfolioOptimizerAgent, and SignalAgent. The out-of-sample window is sealed:
metrics for the trailing OOS_FRACTION of history are reported separately from
the full-period numbers rather than being fit and tested on the same window.
"""

import logging

import numpy as np
import yfinance as yf

from schemas.stock import BacktestResult, SignalSet

logger = logging.getLogger(__name__)

TRADING_DAYS_PER_YEAR = 252
OOS_FRACTION = 0.2  # trailing 20% of history held out as the sealed out-of-sample window


class BacktestEngine:
    def run(self, ticker: str, signals: SignalSet, benchmark_ticker: str = "^GSPC") -> BacktestResult | None:
        ticker = ticker.upper().strip()
        try:
            hist = yf.Ticker(ticker).history(period="1y", interval="1d")
            hist = hist.dropna(subset=["Close"])
            if len(hist) < 30:
                return None
        except Exception as e:
            logger.warning(f"BacktestEngine price history failed for {ticker}: {e}")
            return None

        daily_returns = hist["Close"].pct_change().fillna(0.0)
        position = self._position_series(hist, signals)
        strategy_returns = (position.shift(1).fillna(0.0) * daily_returns)

        notes: list[str] = []
        benchmark_returns = self._benchmark_returns(benchmark_ticker, hist.index)
        if benchmark_returns is None:
            notes.append(f"Benchmark ({benchmark_ticker}) price history unavailable — benchmark fields are null.")

        oos_start = int(len(hist) * (1 - OOS_FRACTION))
        oos_window = ""
        oos_return = None
        if oos_start < len(hist) - 1:
            oos_return = self._annualized_return(strategy_returns.iloc[oos_start:])
            oos_window = (
                f"{hist.index[oos_start].strftime('%Y-%m-%d')} to "
                f"{hist.index[-1].strftime('%Y-%m-%d')} (trailing {int(OOS_FRACTION * 100)}%)"
            )

        return BacktestResult(
            strategy_return_pct=self._round_pct(self._annualized_return(strategy_returns)),
            strategy_sharpe=self._round(self._sharpe(strategy_returns)),
            strategy_max_drawdown_pct=self._round_pct(self._max_drawdown(strategy_returns)),
            benchmark_ticker=benchmark_ticker,
            benchmark_return_pct=self._round_pct(self._annualized_return(benchmark_returns)) if benchmark_returns is not None else None,
            benchmark_sharpe=self._round(self._sharpe(benchmark_returns)) if benchmark_returns is not None else None,
            out_of_sample_return_pct=self._round_pct(oos_return),
            out_of_sample_window=oos_window,
            num_trades=len(signals.triggers),
            notes=notes,
        )

    # ── Position simulation ──────────────────────────────────────────────────────

    def _position_series(self, hist, signals: SignalSet):
        """1.0 while long, 0.0 while flat — long only, no shorting the sell signals."""
        trigger_by_date = {t.date: t.action for t in signals.triggers}
        position = []
        is_long = False
        for ts in hist.index:
            date = ts.strftime("%Y-%m-%d")
            action = trigger_by_date.get(date)
            if action == "buy":
                is_long = True
            elif action == "sell":
                is_long = False
            position.append(1.0 if is_long else 0.0)
        return hist["Close"].copy() * 0 + position  # same index/dtype as a price-derived series

    def _benchmark_returns(self, benchmark_ticker: str, index):
        try:
            bench = yf.Ticker(benchmark_ticker).history(start=index[0], end=index[-1])
            if bench.empty:
                return None
            return bench["Close"].pct_change().fillna(0.0)
        except Exception as e:
            logger.warning(f"BacktestEngine benchmark fetch failed for {benchmark_ticker}: {e}")
            return None

    # ── Metrics ──────────────────────────────────────────────────────────────────

    def _annualized_return(self, returns) -> float | None:
        if returns is None or len(returns) == 0:
            return None
        cumulative = float((1 + returns).prod())
        years = len(returns) / TRADING_DAYS_PER_YEAR
        if years <= 0 or cumulative <= 0:
            return None
        return cumulative ** (1 / years) - 1

    def _sharpe(self, returns) -> float | None:
        if returns is None or len(returns) < 2:
            return None
        std = float(np.std(returns))
        if std == 0:
            return None
        return float(np.mean(returns)) / std * np.sqrt(TRADING_DAYS_PER_YEAR)

    def _max_drawdown(self, returns) -> float | None:
        if returns is None or len(returns) == 0:
            return None
        equity = (1 + returns).cumprod()
        running_max = equity.cummax()
        drawdown = equity / running_max - 1
        return float(drawdown.min())

    def _round(self, value: float | None, digits: int = 3) -> float | None:
        return None if value is None else round(value, digits)

    def _round_pct(self, value: float | None, digits: int = 2) -> float | None:
        return None if value is None else round(value * 100, digits)
