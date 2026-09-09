import { useEffect, useState } from "react";
import { getPortfolio, optimizePortfolio, removePortfolioHolding, upsertPortfolioHolding } from "../api";
import type { PortfolioHolding, PortfolioOptimizationResult } from "../types";
import { DataTable } from "../components/DataTable";

// Single-period rebalance optimization over current holdings
// (agents/stock/portfolio_optimizer.py) — previously implemented end-to-end
// on the backend with no frontend caller at all.
export function PortfolioPanel() {
  const [holdings, setHoldings] = useState<PortfolioHolding[]>([]);
  const [ticker, setTicker] = useState("");
  const [shares, setShares] = useState("");
  const [costBasis, setCostBasis] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [optimizing, setOptimizing] = useState(false);
  const [result, setResult] = useState<PortfolioOptimizationResult | null>(null);
  const [allowShort, setAllowShort] = useState(false);

  async function refresh() {
    const res = await getPortfolio();
    setHoldings(res.portfolio);
  }

  useEffect(() => {
    refresh().catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, []);

  async function handleAdd() {
    const parsedShares = parseFloat(shares);
    if (!ticker.trim() || !Number.isFinite(parsedShares) || parsedShares <= 0) {
      setError("Enter a ticker and a positive share count.");
      return;
    }
    const parsedCostBasis = costBasis.trim() ? parseFloat(costBasis) : undefined;
    try {
      const res = await upsertPortfolioHolding(ticker.trim().toUpperCase(), parsedShares, parsedCostBasis);
      setHoldings(res.portfolio);
      setTicker("");
      setShares("");
      setCostBasis("");
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  async function handleRemove(t: string) {
    const res = await removePortfolioHolding(t);
    setHoldings(res.portfolio);
  }

  async function handleOptimize() {
    setOptimizing(true);
    setError(null);
    setResult(null);
    try {
      const res = await optimizePortfolio({ allow_short: allowShort });
      setResult(res);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setOptimizing(false);
    }
  }

  return (
    <div>
      <h3>Portfolio</h3>
      <div className="query-box">
        <input value={ticker} onChange={(e) => setTicker(e.target.value)} placeholder="Ticker, e.g. AAPL" />
        <input
          value={shares}
          onChange={(e) => setShares(e.target.value)}
          placeholder="Shares"
          inputMode="decimal"
        />
        <input
          value={costBasis}
          onChange={(e) => setCostBasis(e.target.value)}
          placeholder="Cost basis (optional)"
          inputMode="decimal"
        />
        <button type="button" onClick={handleAdd}>
          Add / Update
        </button>
      </div>
      {error && <div className="error-banner">{error}</div>}

      <ul className="watchlist-grid">
        {holdings.map((h) => (
          <li key={h.ticker} className="watchlist-row">
            <span className="ticker">{h.ticker}</span>
            <span>{h.shares} shares</span>
            <span>{h.cost_basis != null ? `cost basis $${h.cost_basis.toFixed(2)}` : "no cost basis"}</span>
            <button type="button" className="remove-btn" onClick={() => handleRemove(h.ticker)}>
              Remove
            </button>
          </li>
        ))}
        {holdings.length === 0 && <li className="empty-state">No holdings yet — add one above.</li>}
      </ul>

      <p className="disclaimer">Single-period rebalance optimization — not investment advice.</p>
      <div className="query-box">
        <label>
          <input type="checkbox" checked={allowShort} onChange={(e) => setAllowShort(e.target.checked)} />
          {" "}Allow short positions
        </label>
        <button type="button" onClick={handleOptimize} disabled={optimizing || holdings.length === 0}>
          {optimizing ? "Optimizing..." : "Optimize"}
        </button>
      </div>

      {result && (
        <div>
          <p>
            As of {result.as_of_date} — expected annual return{" "}
            <strong>{(result.expected_annual_return * 100).toFixed(1)}%</strong>, expected annual volatility{" "}
            <strong>{(result.expected_annual_volatility * 100).toFixed(1)}%</strong>, estimated rebalance cost{" "}
            <strong>${result.total_est_cost.toFixed(2)}</strong>
          </p>
          <DataTable
            filename={`portfolio-optimization-${result.as_of_date}`}
            columns={["Ticker", "Current Weight", "Target Weight", "Trade", "Action", "Market Impact Cost", "Holding Cost"]}
            rows={result.trades.map((t) => [
              t.ticker,
              `${(t.current_weight * 100).toFixed(1)}%`,
              `${(t.target_weight * 100).toFixed(1)}%`,
              `${(t.trade_weight * 100).toFixed(1)}%`,
              t.action,
              `$${t.est_market_impact_cost.toFixed(2)}`,
              `$${t.est_holding_cost.toFixed(2)}`,
            ])}
          />
          {result.notes.length > 0 && (
            <ul>
              {result.notes.map((n, i) => (
                <li key={i}>{n}</li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
