import { useEffect, useState } from "react";
import { getOpportunityRadar, refreshOpportunityRadar } from "../api";
import type { OpportunityRadarResult } from "../types";

// Reads the latest stored snapshot on mount — the snapshot itself is
// produced by a daily background batch job over the watchlist, not
// computed live on page load. See docs/Stocks/designStock_DashboardUI.md
// and server.py's _opportunity_radar_loop(). "Refresh Now" triggers an
// on-demand run for testing; normal use relies on the daily job.
export function OpportunityRadarPanel() {
  const [result, setResult] = useState<OpportunityRadarResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      setResult(await getOpportunityRadar());
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function handleRefresh() {
    setRefreshing(true);
    setError(null);
    try {
      setResult(await refreshOpportunityRadar());
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setRefreshing(false);
    }
  }

  return (
    <div className="panel-wide">
      <div className="query-box no-print">
        <p className="muted">
          Sector themes detected across your watchlist's recent headlines, updated daily.
        </p>
        <button type="button" onClick={handleRefresh} disabled={refreshing}>
          {refreshing ? "Refreshing..." : "Refresh Now"}
        </button>
      </div>

      {loading && <p className="muted">Loading...</p>}
      {error && <div className="error-banner">{error}</div>}

      {result && (
        <>
          <p className="muted">
            {result.generated_at} · {result.universe.length} tickers scanned
            {result.universe.length > 0 && ` (${result.universe.join(", ")})`}
          </p>

          {result.themes.length === 0 && (
            <p className="muted">
              No themes detected yet — themes need at least two matching headlines across your
              watchlist. Try adding more tickers or check back after the next daily run.
            </p>
          )}

          <div className="theme-grid">
            {result.themes.map((theme) => (
              <div key={theme.theme} className="card">
                <h4>{theme.theme}</h4>
                <p className="muted">Theme strength {theme.strength_score}/100</p>
                <p>{theme.description}</p>

                {theme.tickers.length > 0 && (
                  <>
                    <h5>Who's Affected</h5>
                    <div className="stat-row">
                      {theme.tickers.map((t) => (
                        <div
                          key={t.ticker}
                          className={`stat-badge sentiment-${
                            t.stance === "benefit" ? "bullish" : t.stance === "pressured" ? "bearish" : "neutral"
                          }`}
                        >
                          {t.ticker} {t.stance === "benefit" ? "▲" : t.stance === "pressured" ? "▼" : "·"} ({t.mention_count})
                        </div>
                      ))}
                    </div>
                  </>
                )}

                {theme.evidence.length > 0 && (
                  <>
                    <h5>Evidence</h5>
                    <ul className="nested-list">
                      {theme.evidence.map((e, i) => (
                        <li key={i}>
                          <strong>[{e.ticker}]</strong>{" "}
                          {e.url ? (
                            <a href={e.url} target="_blank" rel="noreferrer">
                              {e.title}
                            </a>
                          ) : (
                            e.title
                          )}
                          {e.source && <span className="muted"> · {e.source}</span>}
                        </li>
                      ))}
                    </ul>
                  </>
                )}
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
