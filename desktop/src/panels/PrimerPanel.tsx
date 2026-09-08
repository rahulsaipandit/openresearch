import { useState } from "react";
import { runStockPrimer } from "../api";
import type { ResearchPrimer } from "../types";
import { FinancialChart } from "../components/FinancialChart";
import { CitedText } from "../components/CitedText";

// Research Primer — richer multi-section document, "middle ground" scope
// per requirements.md (business foundation, driver tree, debate map,
// adversarial review, underwriting synthesis) built on the existing
// ResearchBrief + TrendData, not a full multi-day deep-dive pipeline.
//
// PDF export uses the browser's native print-to-PDF (window.print()) rather
// than a new backend PDF-generation dependency — .primer-print CSS controls
// what actually renders in the printed output.
export function PrimerPanel() {
  const [ticker, setTicker] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [primer, setPrimer] = useState<ResearchPrimer | null>(null);

  async function handleGenerate() {
    if (!ticker.trim()) return;
    setLoading(true);
    setError(null);
    setPrimer(null);
    try {
      const res = await runStockPrimer(ticker.trim());
      setPrimer(res);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div>
      <div className="query-box no-print">
        <input
          value={ticker}
          onChange={(e) => setTicker(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleGenerate()}
          placeholder="Ticker, e.g. AAPL"
        />
        <button type="button" onClick={handleGenerate} disabled={loading}>
          {loading ? "Generating primer (this takes longer than a quick brief)..." : "Generate Primer"}
        </button>
        {primer && (
          <button type="button" onClick={() => window.print()}>
            Save as PDF
          </button>
        )}
      </div>
      {error && <div className="error-banner no-print">{error}</div>}
      {primer && <PrimerView primer={primer} />}
    </div>
  );
}

function PrimerView({ primer }: { primer: ResearchPrimer }) {
  const brief = primer.research_brief;

  return (
    <div className="primer-doc">
      <header className="primer-header">
        <h1>{primer.company_name} ({primer.ticker})</h1>
        <p className="muted">Research Primer &middot; as of {primer.as_of_date}</p>
        <p className="disclaimer">Research assistant output — not investment advice.</p>
      </header>

      <section className="primer-section">
        <h2>1. Market Snapshot &amp; Verdict</h2>
        <div className="stat-row">
          <div className={`stat-badge verdict-${brief.verdict.toLowerCase().replace(/\s+/g, "-")}`}>
            {brief.verdict}
          </div>
          <div className="stat-badge">
            Target ${brief.price_target_low.toFixed(0)}–${brief.price_target_high.toFixed(0)}
          </div>
        </div>
        <CitedText text={brief.summary} sources={brief.sources} />
      </section>

      <section className="primer-section">
        <h2>2. Business Foundation</h2>
        <p>{primer.business_foundation.overview}</p>
        <p><strong>Revenue model:</strong> {primer.business_foundation.revenue_model}</p>
        {primer.business_foundation.key_segments.length > 0 && (
          <p className="muted">Segments: {primer.business_foundation.key_segments.join(", ")}</p>
        )}
        {primer.business_foundation.unit_economics_notes && (
          <p className="muted">{primer.business_foundation.unit_economics_notes}</p>
        )}
      </section>

      <section className="primer-section">
        <h2>3. Financial Architecture &amp; Five-Year Trend</h2>
        <p className="previous-year-summary">{primer.trend.previous_year_summary}</p>
        <div className="page-break-avoid">
          <FinancialChart
            type="line"
            yLabel="Close price"
            series={[{ name: primer.ticker, data: primer.trend.price_history.map((p) => ({ x: p.date, y: p.close ?? 0 })) }]}
          />
        </div>
      </section>

      <section className="primer-section">
        <h2>4. Driver Tree</h2>
        <table className="data-table">
          <thead>
            <tr><th>Driver</th><th>Direction</th><th>Confidence</th><th>Note</th></tr>
          </thead>
          <tbody>
            {primer.driver_tree.map((d, i) => (
              <tr key={i}>
                <td>{d.driver}</td>
                <td className={`priority priority-${d.direction === "headwind" ? "high" : d.direction === "mixed" ? "medium" : "low"}`}>
                  {d.direction}
                </td>
                <td>{d.confidence}</td>
                <td>{d.note}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section className="primer-section">
        <h2>5. Debate Map</h2>
        {primer.debate_map.map((d, i) => (
          <div key={i} className="card page-break-avoid">
            <p><strong>{d.question}</strong></p>
            <div className="two-col">
              <p><span className="muted">Bull:</span> {d.bull_view}</p>
              <p><span className="muted">Bear:</span> {d.bear_view}</p>
            </div>
            <p className="muted">Would resolve with: {d.what_would_resolve_it}</p>
          </div>
        ))}
      </section>

      <section className="primer-section page-break-avoid">
        <h2>6. Adversarial Review</h2>
        <p>{primer.adversarial_review.integrated_bear_case}</p>
        {primer.adversarial_review.reconciliation_notes.length > 0 && (
          <>
            <h4>Reconciliation Notes</h4>
            <ul className="risk-list">
              {primer.adversarial_review.reconciliation_notes.map((n, i) => <li key={i}>{n}</li>)}
            </ul>
          </>
        )}
        {primer.adversarial_review.numeric_sanity_checks.length > 0 && (
          <>
            <h4>Numeric Sanity Checks</h4>
            <ul>
              {primer.adversarial_review.numeric_sanity_checks.map((n, i) => <li key={i}>{n}</li>)}
            </ul>
          </>
        )}
      </section>

      <section className="primer-section page-break-avoid">
        <h2>7. Underwriting Summary</h2>
        <p>{primer.underwriting_summary}</p>
      </section>
    </div>
  );
}
