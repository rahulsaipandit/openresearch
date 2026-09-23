import { useEffect, useRef, useState } from "react";
import { analyzePairs } from "../api";
import type { PairsAnalysisResult } from "../types";
import { DataTable } from "../components/DataTable";

const REFRESH_INTERVAL_MS = 5 * 60 * 1000;

const SIGNAL_LABEL: Record<PairsAnalysisResult["signal"], string> = {
  long_spread: "Long spread (long Y, short beta*X)",
  short_spread: "Short spread (short Y, long beta*X)",
  flat: "Flat — no signal",
};

// Kalman-filtered adaptive hedge ratio for pairs trading (agents/stock/
// pairs_trading.py) — a corrected implementation of the "Kalman Filters for
// Adaptive Pairs Trading" article: z-scores from the filter's own innovation
// variance, adaptive observation noise, cointegration re-checked every call,
// and half-life gating the signal instead of just being reported.
export function PairsTradingPanel() {
  const [tickerY, setTickerY] = useState("KO");
  const [tickerX, setTickerX] = useState("PEP");
  const [capital, setCapital] = useState("100000");
  const [autoRefresh, setAutoRefresh] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<PairsAnalysisResult | null>(null);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  async function handleAnalyze() {
    if (!tickerY.trim() || !tickerX.trim()) {
      setError("Enter both tickers.");
      return;
    }
    const parsedCapital = parseFloat(capital);
    setLoading(true);
    setError(null);
    try {
      const res = await analyzePairs({
        ticker_y: tickerY.trim().toUpperCase(),
        ticker_x: tickerX.trim().toUpperCase(),
        capital: Number.isFinite(parsedCapital) && parsedCapital > 0 ? parsedCapital : undefined,
      });
      setResult(res);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (intervalRef.current) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
    if (autoRefresh) {
      intervalRef.current = setInterval(() => {
        handleAnalyze();
      }, REFRESH_INTERVAL_MS);
    }
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoRefresh, tickerY, tickerX, capital]);

  return (
    <div>
      <h3>Pairs Trading</h3>
      <div className="query-box">
        <input value={tickerY} onChange={(e) => setTickerY(e.target.value)} placeholder="Ticker Y, e.g. KO" />
        <input value={tickerX} onChange={(e) => setTickerX(e.target.value)} placeholder="Ticker X, e.g. PEP" />
        <input value={capital} onChange={(e) => setCapital(e.target.value)} placeholder="Capital" inputMode="decimal" />
        <button type="button" onClick={handleAnalyze} disabled={loading}>
          {loading ? "Analyzing..." : "Analyze"}
        </button>
      </div>
      <div className="query-box">
        <label>
          <input type="checkbox" checked={autoRefresh} onChange={(e) => setAutoRefresh(e.target.checked)} />
          {" "}Auto-refresh every 5 minutes
        </label>
      </div>
      <p className="disclaimer">
        On-demand analysis, not a live trading system — recomputes the filter from scratch each call rather than
        tracking open positions.
      </p>

      {error && <div className="error-banner">{error}</div>}

      {result && (
        <div>
          <p>
            As of {result.as_of_date} — {result.ticker_y}/{result.ticker_x}, {result.n_observations} trading days.
            Hedge ratio (beta) <strong>{result.hedge_ratio.toFixed(4)}</strong>, spread{" "}
            <strong>{result.spread.toFixed(3)}</strong>, z-score <strong>{result.z_score.toFixed(2)}</strong>.
          </p>

          <div className="factor-exposure">
            <h4>Signal: {SIGNAL_LABEL[result.signal]}</h4>
            {result.signal !== "flat" && (
              <p>
                Shares Y: <strong>{result.shares_y.toFixed(2)}</strong>, Shares X:{" "}
                <strong>{result.shares_x.toFixed(2)}</strong>
              </p>
            )}
            <DataTable
              filename={`pairs-${result.ticker_y}-${result.ticker_x}-${result.as_of_date}`}
              columns={["Metric", "Value"]}
              rows={[
                ["Engle-Granger p-value", result.engle_granger_pvalue.toFixed(4)],
                ["Cointegrated (p<0.05)", result.cointegrated ? "Yes" : "No"],
                ["ADF p-value (recent window)", result.adf_pvalue.toFixed(4)],
                ["Stationary now (p<0.05)", result.stationary_now ? "Yes" : "No"],
                ["Half-life (days)", result.half_life_days != null ? result.half_life_days.toFixed(1) : "N/A"],
                ["Observation noise (R)", result.observation_noise.toFixed(6)],
              ]}
            />
            {result.warnings.length > 0 && (
              <ul>
                {result.warnings.map((w, i) => (
                  <li key={i} className="error-banner">
                    {w}
                  </li>
                ))}
              </ul>
            )}
          </div>

          {result.history.length > 0 && (
            <div className="factor-exposure">
              <h4>Recent history (last {result.history.length} trading days)</h4>
              <DataTable
                filename={`pairs-${result.ticker_y}-${result.ticker_x}-history`}
                columns={["Date", "Hedge Ratio", "Spread", "Z-Score"]}
                rows={result.history.map((h) => [
                  h.date,
                  h.hedge_ratio.toFixed(4),
                  h.spread.toFixed(3),
                  h.z_score.toFixed(2),
                ])}
              />
            </div>
          )}

          <details className="explainer">
            <summary>How and why this works (Kalman filter for adaptive pairs trading)</summary>
            <div className="explainer-body">
              <p>
                This models the relationship between two assets as{" "}
                <span className="formula-inline">Y_t = alpha_t + beta_t * X_t + eps_t</span>, treating the hedge
                ratio beta_t as a hidden state that evolves over time (a random walk) instead of a fixed-window
                regression that goes stale when the relationship shifts.
              </p>
              <ul>
                <li>
                  <strong>Z-scores</strong> come from the Kalman filter's own innovation variance at each step, not
                  a rolling historical standard deviation — the filter already knows its own uncertainty.
                </li>
                <li>
                  <strong>Observation noise (R)</strong> is estimated adaptively online (innovation-based adaptive
                  estimation), so the filter doesn't over-react in calm markets or under-react in volatile ones.
                </li>
                <li>
                  <strong>Cointegration</strong> is re-checked on every call (Engle-Granger over the full lookback,
                  plus an ADF stationarity test on the recent spread) rather than assumed permanent — a pair that
                  stops being cointegrated turns this into an accidental trend-following trade that bleeds capital.
                </li>
                <li>
                  <strong>Half-life</strong> of mean reversion gates the signal: no trade fires outside a 1-20 day
                  half-life or when the spread shows no mean reversion at all.
                </li>
                <li>
                  <strong>Position sizing</strong> uses share quantities (Q_y = capital / price_y,{" "}
                  Q_x = beta * Q_y), not raw percent-change subtraction, which isn't valid for a dollar-neutral
                  hedge.
                </li>
              </ul>
              <p>
                This is a one-shot analysis re-run on demand or every 5 minutes, not a live execution system — it
                doesn't track open positions, account for slippage/borrow costs, or place trades.
              </p>
            </div>
          </details>
        </div>
      )}
    </div>
  );
}
