"""
SignalAgent — candlestick pattern detection + indicator-based buy/sell signals.

Source reference: Ntale, "AI Trading: Evaluating Large Language Models for
Technical Market Analysis" (2026), https://arxiv.org/abs/2607.15414 — benchmarks
GPT-4 Turbo / Claude 3 Opus / Gemini 1.5 Pro / Llama 3 70B / FinGPT on reading
candlestick charts and generating trading signals directly. Its finding: every
model, general-purpose or finance-tuned, hallucinates numbers and degrades in
sideways markets when asked to do this arithmetic itself.

Same philosophy as TrendAnalystAgent and PortfolioOptimizerAgent: pure
deterministic math over fetched OHLC data, no LLM call, nothing to
hallucinate. Patterns and triggers computed here are handed to the LLM only
as pre-computed facts to narrate (see ResearchSynthesizerAgent), never as
something it derives itself. See docs/designStock_TechnicalSignalsAndBacktesting.md.
"""

import logging

import yfinance as yf

from schemas.stock import CandlestickPattern, SignalSet, SignalTrigger

logger = logging.getLogger(__name__)

RSI_PERIOD = 14
RSI_OVERBOUGHT = 70.0
RSI_OVERSOLD = 30.0
BULLISH_LOOKBACK_BARS = 3  # a pattern "confirms" a signal if it occurred within this many bars


class SignalAgent:
    def generate(self, ticker: str) -> SignalSet | None:
        """
        Compute candlestick patterns + buy/sell/hold triggers for a ticker,
        from ~1y of daily yfinance OHLC. Returns None if there isn't enough
        price history to say anything.
        """
        ticker = ticker.upper().strip()
        try:
            hist = yf.Ticker(ticker).history(period="1y", interval="1d")
            hist = hist.dropna(subset=["Open", "High", "Low", "Close"])
            if len(hist) < 30:
                return None
        except Exception as e:
            logger.warning(f"SignalAgent price history failed for {ticker}: {e}")
            return None

        patterns = self._detect_patterns(hist)
        rsi_series = self._rsi(hist["Close"])
        macd_line, macd_signal = self._macd(hist["Close"])
        sma50 = hist["Close"].rolling(50).mean()

        triggers = self._build_triggers(hist, patterns, rsi_series, macd_line, macd_signal, sma50)

        latest_action = triggers[-1].action if triggers else "hold"
        current_signal = latest_action if triggers and self._is_recent(triggers[-1], hist) else "hold"

        summary = self._build_summary(patterns, triggers, rsi_series)

        return SignalSet(
            patterns=patterns[-10:],
            triggers=triggers[-10:],
            current_signal=current_signal,
            summary=summary,
        )

    # ── Candlestick pattern detection ───────────────────────────────────────────

    def _detect_patterns(self, hist) -> list[CandlestickPattern]:
        patterns: list[CandlestickPattern] = []
        rows = list(hist.itertuples())
        for i in range(1, len(rows)):
            prev, cur = rows[i - 1], rows[i]
            date = cur.Index.strftime("%Y-%m-%d")

            prev_body = abs(prev.Close - prev.Open)
            cur_body = abs(cur.Close - cur.Open)
            cur_range = cur.High - cur.Low
            if cur_range <= 0:
                continue

            # Bullish engulfing: prior red candle, current green candle whose body
            # fully engulfs the prior candle's body.
            if (
                prev.Close < prev.Open
                and cur.Close > cur.Open
                and cur.Open <= prev.Close
                and cur.Close >= prev.Open
            ):
                patterns.append(CandlestickPattern(pattern="bullish_engulfing", date=date, direction="bullish"))

            # Bearish engulfing: mirror image.
            elif (
                prev.Close > prev.Open
                and cur.Close < cur.Open
                and cur.Open >= prev.Close
                and cur.Close <= prev.Open
            ):
                patterns.append(CandlestickPattern(pattern="bearish_engulfing", date=date, direction="bearish"))

            # Hammer: small body in the top third of the range, lower shadow at
            # least 2x the body, little to no upper shadow.
            lower_shadow = min(cur.Open, cur.Close) - cur.Low
            upper_shadow = cur.High - max(cur.Open, cur.Close)
            if cur_body > 0 and lower_shadow >= 2 * cur_body and upper_shadow <= cur_body * 0.3:
                patterns.append(CandlestickPattern(pattern="hammer", date=date, direction="bullish"))

            # Doji: body is a tiny fraction of the day's range — indecision.
            if cur_body <= cur_range * 0.1:
                patterns.append(CandlestickPattern(pattern="doji", date=date, direction="neutral"))

        return patterns

    # ── Indicators (only computed here when Equibles isn't available) ──────────

    def _rsi(self, closes, period: int = RSI_PERIOD):
        delta = closes.diff()
        gain = delta.clip(lower=0).rolling(period).mean()
        loss = (-delta.clip(upper=0)).rolling(period).mean()
        rs = gain / loss.replace(0, float("nan"))
        return 100 - (100 / (1 + rs))

    def _macd(self, closes):
        ema12 = closes.ewm(span=12, adjust=False).mean()
        ema26 = closes.ewm(span=26, adjust=False).mean()
        macd_line = ema12 - ema26
        signal_line = macd_line.ewm(span=9, adjust=False).mean()
        return macd_line, signal_line

    # ── Trigger rules (rule-based, not LLM-generated) ───────────────────────────

    def _build_triggers(self, hist, patterns, rsi_series, macd_line, macd_signal, sma50) -> list[SignalTrigger]:
        pattern_by_date = {p.date: p for p in patterns}
        triggers: list[SignalTrigger] = []
        macd_cross_up = (macd_line.shift(1) <= macd_signal.shift(1)) & (macd_line > macd_signal)
        macd_cross_down = (macd_line.shift(1) >= macd_signal.shift(1)) & (macd_line < macd_signal)

        for i in range(1, len(hist)):
            date_ts = hist.index[i]
            date = date_ts.strftime("%Y-%m-%d")
            rsi = rsi_series.iloc[i]
            price = hist["Close"].iloc[i]
            ma50 = sma50.iloc[i]
            if rsi != rsi:  # NaN — not enough history yet for this bar
                continue

            recent_pattern = self._pattern_in_window(pattern_by_date, hist, i, BULLISH_LOOKBACK_BARS)

            if rsi < RSI_OVERSOLD and recent_pattern and recent_pattern.direction == "bullish":
                triggers.append(SignalTrigger(
                    date=date, action="buy",
                    reason=f"RSI oversold ({rsi:.1f}) + {recent_pattern.pattern} on {recent_pattern.date}",
                ))
            elif macd_cross_up.iloc[i] and ma50 == ma50 and price > ma50:
                triggers.append(SignalTrigger(
                    date=date, action="buy",
                    reason=f"MACD bullish crossover with price above 50-day SMA (${price:.2f} > ${ma50:.2f})",
                ))
            elif rsi > RSI_OVERBOUGHT and recent_pattern and recent_pattern.direction == "bearish":
                triggers.append(SignalTrigger(
                    date=date, action="sell",
                    reason=f"RSI overbought ({rsi:.1f}) + {recent_pattern.pattern} on {recent_pattern.date}",
                ))
            elif macd_cross_down.iloc[i] and ma50 == ma50 and price < ma50:
                triggers.append(SignalTrigger(
                    date=date, action="sell",
                    reason=f"MACD bearish crossover with price below 50-day SMA (${price:.2f} < ${ma50:.2f})",
                ))

        return triggers

    def _pattern_in_window(self, pattern_by_date, hist, i: int, lookback: int) -> CandlestickPattern | None:
        for j in range(max(0, i - lookback), i + 1):
            date = hist.index[j].strftime("%Y-%m-%d")
            if date in pattern_by_date and pattern_by_date[date].direction != "neutral":
                return pattern_by_date[date]
        return None

    def _is_recent(self, trigger: SignalTrigger, hist, within_bars: int = 5) -> bool:
        recent_dates = {d.strftime("%Y-%m-%d") for d in hist.index[-within_bars:]}
        return trigger.date in recent_dates

    def _build_summary(self, patterns, triggers, rsi_series) -> str:
        if not triggers:
            return "No qualifying buy/sell triggers in the trailing year; indicators neutral."
        last = triggers[-1]
        latest_rsi = rsi_series.dropna().iloc[-1] if rsi_series.dropna().size else None
        rsi_note = f" Current RSI: {latest_rsi:.1f}." if latest_rsi is not None else ""
        return f"Most recent trigger: {last.action} on {last.date} ({last.reason}).{rsi_note}"
