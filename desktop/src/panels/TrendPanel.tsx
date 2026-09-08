import { useState } from "react";
import { getTrend } from "../api";
import type { TrendData } from "../types";
import { FinancialChart } from "../components/FinancialChart";

// Requirement #7: five-year trend view + previous-year summary.
export function TrendPanel() {
  const [ticker, setTicker] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [data, setData] = useState<TrendData | null>(null);

  async function handleFetch() {
    if (!ticker.trim()) return;
    setLoading(true);
    setError(null);
    setData(null);
    try {
      const res = await getTrend(ticker.trim());
      setData(res);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div>
      <h3>Five-Year Trend</h3>
      <div className="query-box">
        <input
          value={ticker}
          onChange={(e) => setTicker(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleFetch()}
          placeholder="Ticker, e.g. AAPL"
        />
        <button type="button" onClick={handleFetch} disabled={loading}>
          {loading ? "Loading..." : "Fetch"}
        </button>
      </div>
      {error && <div className="error-banner">{error}</div>}

      {data && (
        <div>
          <p className="previous-year-summary">{data.previous_year_summary}</p>

          {data.volatility && (
            <div>
              <h4>Volatility (EWMA / GARCH)</h4>
              <p className="previous-year-summary">{data.volatility.interpretation}</p>
            </div>
          )}

          <h4>Price (5y, monthly)</h4>
          <FinancialChart
            type="line"
            yLabel="Close price"
            series={[{ name: data.ticker, data: data.price_history.map((p) => ({ x: p.date, y: p.close ?? 0 })) }]}
          />

          <h4>Revenue &amp; Net Income (annual)</h4>
          <FinancialChart
            type="bar"
            series={[
              { name: "Revenue", data: data.annual_financials.map((p) => ({ x: p.date, y: p.revenue ?? 0 })) },
              { name: "Net Income", data: data.annual_financials.map((p) => ({ x: p.date, y: p.net_income ?? 0 })) },
            ]}
          />
        </div>
      )}
    </div>
  );
}
