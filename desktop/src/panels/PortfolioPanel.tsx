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

          {result.factor_exposure && (
            <div className="factor-exposure">
              <h4>Diversification check</h4>
              <p>
                Of {result.factor_exposure.n_tickers} tickers ({result.factor_exposure.n_observations} trading
                days), <strong>{result.factor_exposure.n_significant_factors}</strong> factor
                {result.factor_exposure.n_significant_factors === 1 ? "" : "s"} clear the noise threshold. The
                top factor alone explains{" "}
                <strong>{(result.factor_exposure.top_factor_variance_share * 100).toFixed(1)}%</strong> of
                variance.
              </p>
              {result.factor_exposure.concentration_warning && (
                <p className="error-banner">
                  This portfolio is concentrated in one underlying factor — diversifying across more tickers
                  hasn't diversified the actual risk.
                </p>
              )}

              <details className="explainer">
                <summary>How and why this works (PCA + Random Matrix Theory)</summary>
                <div className="explainer-body">
                  <p>
                    This article by{" "}
                    <a href="https://x.com/L1vsun/article/2070860569838579754" target="_blank" rel="noreferrer">
                      Livsun (@L1vsun)
                    </a>{" "}
                    explains how quantitative hedge funds reduce the complexity of trading hundreds of individual
                    stocks by extracting a small set of underlying market drivers using statistical techniques.
                  </p>

                  <hr />

                  <h5>Key Concepts &amp; Takeaways</h5>
                  <ul>
                    <li>
                      <strong>The Illusion of 500 Independent Bets:</strong> Although the S&amp;P 500 consists of
                      500 distinct companies, their movements are heavily correlated due to shared macroeconomic
                      factors (interest rates, energy prices, market sentiment). Estimating a full 500×500
                      covariance matrix requires tracking 125,250 co-movements, most of which are sampling noise
                      rather than true structural signals.
                    </li>
                    <li>
                      <strong>Dimensionality Reduction via PCA:</strong> Funds use Principal Component Analysis
                      (PCA) to extract orthogonal portfolios (eigenportfolios) that capture the market's variance:
                      <ol>
                        <li>
                          <strong>First Eigenportfolio:</strong> Represents overall market directional movement
                          ("all stocks going up/down together"), accounting for a massive share of total variance.
                        </li>
                        <li>
                          <strong>Subsequent Eigenportfolios:</strong> Represent sector rotations, style dynamics
                          (growth vs. value, large vs. small), and macro factors.
                        </li>
                      </ol>
                    </li>
                    <li>
                      <strong>Separating Signal from Noise (Random Matrix Theory):</strong> Quant desks use Random
                      Matrix Theory (specifically the Marchenko–Pastur law) to define a noise threshold.
                      Eigenvalues falling below this bound are statistically indistinguishable from random noise,
                      filtering out roughly 480+ pseudo-factors and retaining only the few true latent market
                      forces.
                    </li>
                  </ul>

                  <hr />

                  <h5>Visual Analysis of Diagram</h5>
                  <p>
                    The article highlights a fundamental linear factor model formula that quant desks use to
                    decompose individual equity returns:
                  </p>
                  <p className="formula">r_i = β_i,1 f_1 + β_i,2 f_2 + ... + β_i,5 f_5 + ε_i</p>
                  <ul>
                    <li>
                      <strong>Stock Return (r_i):</strong> The total return of stock i.
                    </li>
                    <li>
                      <strong>Hidden Forces / Factor Returns (f_1 … f_5):</strong> The underlying, unobserved
                      systematic market drivers extracted via PCA (e.g. market factor, sector/style trends).
                    </li>
                    <li>
                      <strong>Factor Exposures (β_i,1 … β_i,5):</strong> The sensitivity or loading of stock i to
                      each of the hidden forces.
                    </li>
                    <li>
                      <strong>Residual / Idiosyncratic Return (ε_i):</strong> The true asset-specific return
                      leftover once exposure to all latent market forces is hedged out.
                    </li>
                  </ul>

                  <hr />

                  <h5>Practical Applications for Traders</h5>
                  <ol>
                    <li>
                      <strong>Portfolio Risk Checks:</strong> Measuring factor exposure prevents traders from
                      unintentionally taking market-wide direction bets under the guise of stock diversification —
                      this is what the check above does.
                    </li>
                    <li>
                      <strong>Statistical Arbitrage &amp; Pairs Trading:</strong> Rather than hedging one stock
                      against another specific stock, funds hedge a stock against its exposures (β's) to the
                      underlying PCA factors, then trade the mean-reversion of the remaining residual (ε_i). This
                      is not implemented here — it's a live, continuously-monitored trading strategy, out of
                      scope for a research tool.
                    </li>
                  </ol>
                </div>
              </details>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
