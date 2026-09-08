import { useState } from "react";
import { compareStocks } from "../api";
import type { ComparisonBrief } from "../types";
import { FinancialChart } from "../components/FinancialChart";

// Requirement #3: side-by-side comparison of any two stocks.
export function ComparisonPanel() {
  const [tickerA, setTickerA] = useState("");
  const [tickerB, setTickerB] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<ComparisonBrief | null>(null);

  async function handleCompare() {
    if (!tickerA.trim() || !tickerB.trim()) return;
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const res = await compareStocks(tickerA.trim(), tickerB.trim());
      setResult(res);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div>
      <h3>Compare Two Stocks</h3>
      <div className="query-box">
        <input value={tickerA} onChange={(e) => setTickerA(e.target.value)} placeholder="Ticker A, e.g. AAPL" />
        <input value={tickerB} onChange={(e) => setTickerB(e.target.value)} placeholder="Ticker B, e.g. MSFT" />
        <button type="button" onClick={handleCompare} disabled={loading}>
          {loading ? "Comparing..." : "Compare"}
        </button>
      </div>
      {error && <div className="error-banner">{error}</div>}

      {result && (
        <div>
          <h4>Overall lean: {result.overall_lean}</h4>
          <p>{result.summary}</p>

          <table className="data-table">
            <thead>
              <tr>
                <th>Category</th>
                <th>Winner</th>
                <th>Rationale</th>
              </tr>
            </thead>
            <tbody>
              {result.categories.map((c, i) => (
                <tr key={i}>
                  <td>{c.category}</td>
                  <td>{c.winner}</td>
                  <td>{c.rationale}</td>
                </tr>
              ))}
            </tbody>
          </table>

          <FinancialChart
            type="bar"
            yLabel="P/E ratio"
            series={[
              {
                name: "P/E",
                data: [
                  { x: result.brief_a.ticker, y: result.brief_a.fundamentals.pe_ratio ?? 0 },
                  { x: result.brief_b.ticker, y: result.brief_b.fundamentals.pe_ratio ?? 0 },
                ],
              },
            ]}
          />

          <div className="two-col">
            <div>
              <h4>{result.brief_a.ticker}</h4>
              <p>{result.brief_a.summary}</p>
            </div>
            <div>
              <h4>{result.brief_b.ticker}</h4>
              <p>{result.brief_b.summary}</p>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
