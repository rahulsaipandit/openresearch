import { useState } from "react";
import { getEarningsCallSummary, getTrend, runStockResearch } from "../api";
import type { EarningsCallSummary, ResearchBrief, TrendData } from "../types";
import { CitedText } from "../components/CitedText";
import { FinancialChart } from "../components/FinancialChart";

// One-page overview dashboard (ticker snapshot + price chart + income
// statement + sentiment/outlook side rails), inspired by a reference
// screenshot the user shared. Composed entirely from data the existing
// pipeline already produces (ResearchBrief + TrendData), plus the
// deterministic OptionsAnalyst snapshot (agents/stock/options_analyst.py —
// see docs/designStock_DashboardUI.md). Sections we have no real data
// source for (executive bios, per-analyst-firm rating tables, Opportunity
// Radar sector themes, earnings call summaries) are simply omitted rather
// than invented — tracked as future work in the design doc.

function fmtMoney(n: number | null | undefined): string {
  if (n == null) return "N/A";
  if (Math.abs(n) >= 1e12) return `$${(n / 1e12).toFixed(2)}T`;
  if (Math.abs(n) >= 1e9) return `$${(n / 1e9).toFixed(2)}B`;
  if (Math.abs(n) >= 1e6) return `$${(n / 1e6).toFixed(2)}M`;
  return `$${n.toLocaleString()}`;
}

function fmtPct(n: number | null | undefined): string {
  return n == null ? "N/A" : `${(n * 100).toFixed(1)}%`;
}

function fmtNum(n: number | null | undefined, digits = 2): string {
  return n == null ? "N/A" : n.toFixed(digits);
}

function fmtCompact(n: number | null | undefined): string {
  if (n == null) return "N/A";
  if (Math.abs(n) >= 1e9) return `${(n / 1e9).toFixed(2)}B`;
  if (Math.abs(n) >= 1e6) return `${(n / 1e6).toFixed(2)}M`;
  if (Math.abs(n) >= 1e3) return `${(n / 1e3).toFixed(2)}K`;
  return n.toLocaleString();
}

export function DashboardPanel() {
  const [ticker, setTicker] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [brief, setBrief] = useState<ResearchBrief | null>(null);
  const [trend, setTrend] = useState<TrendData | null>(null);
  const [earningsCall, setEarningsCall] = useState<EarningsCallSummary | null>(null);
  const [earningsCallLoading, setEarningsCallLoading] = useState(false);
  const [earningsCallError, setEarningsCallError] = useState<string | null>(null);

  async function handleFetch() {
    if (!ticker.trim()) return;
    setLoading(true);
    setError(null);
    setBrief(null);
    setTrend(null);
    setEarningsCall(null);
    setEarningsCallError(null);
    try {
      const [briefRes, trendRes] = await Promise.all([
        runStockResearch(ticker.trim(), "full"),
        getTrend(ticker.trim()),
      ]);
      setBrief(briefRes);
      setTrend(trendRes);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  // Lazy-loaded on demand, not fetched alongside the rest of the dashboard —
  // pulling and summarizing a full transcript is a separate, heavier LLM
  // call (see agents/stock/earnings_call_summarizer.py).
  async function handleLoadEarningsCall() {
    if (!ticker.trim()) return;
    setEarningsCallLoading(true);
    setEarningsCallError(null);
    try {
      setEarningsCall(await getEarningsCallSummary(ticker.trim()));
    } catch (e) {
      setEarningsCallError(e instanceof Error ? e.message : String(e));
    } finally {
      setEarningsCallLoading(false);
    }
  }

  const verdictClass = brief ? `verdict-${brief.verdict.toLowerCase().replace(/\s+/g, "-")}` : "";

  return (
    <div className="panel-wide">
      <div className="query-box no-print">
        <input
          value={ticker}
          onChange={(e) => setTicker(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleFetch()}
          placeholder="Ticker, e.g. PLTR"
        />
        <button type="button" onClick={handleFetch} disabled={loading}>
          {loading ? "Loading..." : "Load Dashboard"}
        </button>
      </div>
      {error && <div className="error-banner">{error}</div>}

      {brief && trend && (
        <>
          <div className="dashboard-header">
            <h2>
              {brief.company_name} ({brief.ticker})
            </h2>
            <div className="stat-row">
              <div className={`stat-badge verdict ${verdictClass}`}>{brief.verdict}</div>
              {brief.current_price != null && <div className="stat-badge">${brief.current_price.toFixed(2)}</div>}
              <div className="stat-badge">
                Target ${brief.price_target_low.toFixed(0)}–${brief.price_target_high.toFixed(0)}
              </div>
              <div className={`stat-badge sentiment-${brief.sentiment.tone}`}>{brief.sentiment.tone}</div>
            </div>
            <div className="stat-row">
              <div className="stat-badge">Market Cap {fmtMoney(brief.fundamentals.market_cap)}</div>
              <div className="stat-badge">P/E {fmtNum(brief.fundamentals.pe_ratio)}</div>
              {(brief.fundamentals.fifty_two_week_low != null || brief.fundamentals.fifty_two_week_high != null) && (
                <div className="stat-badge">
                  52wk {fmtNum(brief.fundamentals.fifty_two_week_low, 0)}–{fmtNum(brief.fundamentals.fifty_two_week_high, 0)}
                </div>
              )}
              {brief.fundamentals.dividend_yield != null && (
                <div className="stat-badge">Div Yield {fmtPct(brief.fundamentals.dividend_yield)}</div>
              )}
              {brief.fundamentals.volume != null && (
                <div className="stat-badge">Volume {fmtCompact(brief.fundamentals.volume)}</div>
              )}
              {brief.fundamentals.shares_outstanding != null && (
                <div className="stat-badge">Shares Out {fmtCompact(brief.fundamentals.shares_outstanding)}</div>
              )}
            </div>
          </div>

          <div className="dashboard-grid">
            {/* ── Left rail: company snapshot + market-structure signals ── */}
            <div className="dashboard-col dashboard-left">
              <div className="card">
                <h4>Snapshot</h4>
                <table className="kv-table">
                  <tbody>
                    <tr>
                      <th>Market Cap</th>
                      <td>{fmtMoney(brief.fundamentals.market_cap)}</td>
                    </tr>
                    <tr>
                      <th>P/E</th>
                      <td>{fmtNum(brief.fundamentals.pe_ratio)}</td>
                    </tr>
                    <tr>
                      <th>Forward P/E</th>
                      <td>{fmtNum(brief.fundamentals.forward_pe)}</td>
                    </tr>
                    <tr>
                      <th>EPS</th>
                      <td>{fmtNum(brief.fundamentals.eps)}</td>
                    </tr>
                    <tr>
                      <th>Revenue Growth YoY</th>
                      <td>{fmtPct(brief.fundamentals.revenue_growth_yoy)}</td>
                    </tr>
                    <tr>
                      <th>Profit Margin</th>
                      <td>{fmtPct(brief.fundamentals.profit_margin)}</td>
                    </tr>
                    <tr>
                      <th>Debt/Equity</th>
                      <td>{fmtNum(brief.fundamentals.debt_to_equity)}</td>
                    </tr>
                  </tbody>
                </table>
              </div>

              {brief.technicals && (
                <div className="card">
                  <h4>Technicals</h4>
                  <table className="kv-table">
                    <tbody>
                      {brief.technicals.rsi_14 != null && (
                        <tr>
                          <th>RSI (14)</th>
                          <td>{fmtNum(brief.technicals.rsi_14, 1)}</td>
                        </tr>
                      )}
                      {brief.technicals.sma_50 != null && (
                        <tr>
                          <th>SMA 50</th>
                          <td>
                            {fmtNum(brief.technicals.sma_50)}
                            {brief.technicals.price_vs_sma50 && ` (${brief.technicals.price_vs_sma50})`}
                          </td>
                        </tr>
                      )}
                      {brief.technicals.sma_200 != null && (
                        <tr>
                          <th>SMA 200</th>
                          <td>
                            {fmtNum(brief.technicals.sma_200)}
                            {brief.technicals.price_vs_sma200 && ` (${brief.technicals.price_vs_sma200})`}
                          </td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                  {brief.technicals.trend_signal && <p className="muted">{brief.technicals.trend_signal}</p>}
                </div>
              )}

              {brief.options && (
                <div className="card">
                  <h4>Puts &amp; Calls</h4>
                  <table className="kv-table">
                    <tbody>
                      {brief.options.put_call_volume_ratio != null && (
                        <tr>
                          <th>Put/Call Ratio</th>
                          <td>
                            {fmtNum(brief.options.put_call_volume_ratio)}
                            {brief.options.put_call_ratio_30d_avg != null &&
                              ` (30d avg ${fmtNum(brief.options.put_call_ratio_30d_avg)})`}
                          </td>
                        </tr>
                      )}
                      {brief.options.dominant_call_strike != null && (
                        <tr>
                          <th>Top Call Strike</th>
                          <td>${fmtNum(brief.options.dominant_call_strike, 0)}</td>
                        </tr>
                      )}
                      {brief.options.dominant_put_strike != null && (
                        <tr>
                          <th>Top Put Strike</th>
                          <td>${fmtNum(brief.options.dominant_put_strike, 0)}</td>
                        </tr>
                      )}
                      {brief.options.iv_skew != null && (
                        <tr>
                          <th>IV Skew (put − call)</th>
                          <td>{fmtNum(brief.options.iv_skew, 3)}</td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                  {(brief.options.unusual_call_activity || brief.options.unusual_put_activity) && (
                    <p className={`stat-badge ${brief.options.unusual_call_activity ? "sentiment-bullish" : "sentiment-bearish"}`}>
                      {brief.options.unusual_call_activity ? "Unusual call activity" : "Unusual put activity"}
                    </p>
                  )}
                  {brief.options.summary && <p className="muted">{brief.options.summary}</p>}
                </div>
              )}

              {brief.market_structure && brief.market_structure.recent_insider_transactions.length > 0 && (
                <div className="card">
                  <h4>Insider Trades</h4>
                  <ul className="nested-list">
                    {brief.market_structure.recent_insider_transactions.slice(0, 6).map((t, i) => (
                      <li key={i}>
                        <strong>{t.insider_name}</strong>
                        {t.title && ` (${t.title})`} — {t.transaction_type ?? "N/A"}
                        {t.total_value != null && ` · ${fmtMoney(t.total_value)}`}
                        {t.transaction_date && <span className="muted"> · {t.transaction_date}</span>}
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {brief.market_structure && brief.market_structure.congressional_trades.length > 0 && (
                <div className="card">
                  <h4>Trades by Congress</h4>
                  <ul className="nested-list">
                    {brief.market_structure.congressional_trades.slice(0, 6).map((t, i) => (
                      <li key={i}>{t}</li>
                    ))}
                  </ul>
                </div>
              )}

              {!brief.market_structure && (
                <p className="muted">
                  Insider / Congress trade data requires Equibles — not available in this environment.
                </p>
              )}
            </div>

            {/* ── Center: price chart, volatility, income statement, notable events ── */}
            <div className="dashboard-col dashboard-center">
              <div className="card">
                <h4>Price (5y, monthly)</h4>
                <FinancialChart
                  type="line"
                  yLabel="Close price"
                  series={[
                    { name: trend.ticker, data: trend.price_history.map((p) => ({ x: p.date, y: p.close ?? 0 })) },
                  ]}
                />
                <p className="previous-year-summary">{trend.previous_year_summary}</p>
              </div>

              {trend.volatility && (
                <div className="card">
                  <h4>Volatility (EWMA / GARCH)</h4>
                  <p>{trend.volatility.interpretation}</p>
                </div>
              )}

              <div className="card">
                <h4>Income Statement (annual)</h4>
                <FinancialChart
                  type="bar"
                  series={[
                    { name: "Revenue", data: trend.annual_financials.map((p) => ({ x: p.date, y: p.revenue ?? 0 })) },
                    {
                      name: "Net Income",
                      data: trend.annual_financials.map((p) => ({ x: p.date, y: p.net_income ?? 0 })),
                    },
                  ]}
                />
              </div>

              <div className="card">
                <h4>Earnings Call Summary</h4>
                {!earningsCall && !earningsCallLoading && (
                  <button type="button" onClick={handleLoadEarningsCall}>
                    Load Earnings Call Summary
                  </button>
                )}
                {earningsCallLoading && <p className="muted">Fetching and summarizing transcript...</p>}
                {earningsCallError && <div className="error-banner">{earningsCallError}</div>}
                {earningsCall && (
                  <div>
                    <p className="muted">
                      {earningsCall.quarter}
                      {" · "}
                      <span className={`sentiment-${earningsCall.management_tone === "confident" ? "bullish" : earningsCall.management_tone === "defensive" || earningsCall.management_tone === "cautious" ? "bearish" : "neutral"}`}>
                        {earningsCall.management_tone} tone
                      </span>
                    </p>
                    {earningsCall.key_highlights.length > 0 && (
                      <>
                        <h5>Highlights</h5>
                        <ul>
                          {earningsCall.key_highlights.map((h, i) => (
                            <li key={i}>{h}</li>
                          ))}
                        </ul>
                      </>
                    )}
                    {earningsCall.guidance.length > 0 && (
                      <>
                        <h5>Guidance</h5>
                        <ul>
                          {earningsCall.guidance.map((g, i) => (
                            <li key={i}>{g}</li>
                          ))}
                        </ul>
                      </>
                    )}
                    {earningsCall.notable_qa.length > 0 && (
                      <>
                        <h5>Notable Q&amp;A</h5>
                        <ul className="nested-list">
                          {earningsCall.notable_qa.map((qa, i) => (
                            <li key={i}>{qa}</li>
                          ))}
                        </ul>
                      </>
                    )}
                    {earningsCall.linked_8k_url && (
                      <p className="muted">
                        <a href={earningsCall.linked_8k_url} target="_blank" rel="noreferrer">
                          Linked 8-K filing
                        </a>
                      </p>
                    )}
                  </div>
                )}
              </div>

              <div className="card">
                <h4>Notable Events &amp; Catalysts</h4>
                <ul>
                  {brief.upcoming_catalysts.map((c, i) => (
                    <li key={i}>{c}</li>
                  ))}
                </ul>
              </div>

              <div className="card">
                <h4>Summary</h4>
                <CitedText text={brief.summary} sources={brief.sources} />
              </div>
            </div>

            {/* ── Right rail: sentiment, price target, ownership ── */}
            <div className="dashboard-col dashboard-right">
              <div className="card">
                <h4>Sentiment &amp; Outlook</h4>
                <p>
                  Tone: <strong className={`sentiment-${brief.sentiment.tone}`}>{brief.sentiment.tone}</strong>
                </p>
                {brief.sentiment.analyst_consensus && <p>{brief.sentiment.analyst_consensus}</p>}
                <h5>Catalysts</h5>
                <ul>
                  {brief.sentiment.catalysts.map((c, i) => (
                    <li key={i}>{c}</li>
                  ))}
                </ul>
                <h5>Risks</h5>
                <ul className="risk-list">
                  {brief.sentiment.risks.map((r, i) => (
                    <li key={i}>{r}</li>
                  ))}
                </ul>
              </div>

              {brief.sentiment.recent_headlines.length > 0 && (
                <div className="card">
                  <h4>Recent Headlines</h4>
                  <ul>
                    {brief.sentiment.recent_headlines.slice(0, 6).map((h, i) => (
                      <li key={i}>{h}</li>
                    ))}
                  </ul>
                </div>
              )}

              {brief.institutional && brief.institutional.top_holders.length > 0 ? (
                <div className="card">
                  <h4>Top Institutional Holders</h4>
                  {brief.institutional.total_institutional_ownership_pct != null && (
                    <p className="muted">
                      {fmtPct(brief.institutional.total_institutional_ownership_pct / 100)} of float
                      {brief.institutional.as_of_quarter && ` as of ${brief.institutional.as_of_quarter}`}
                    </p>
                  )}
                  <ul className="nested-list">
                    {brief.institutional.top_holders.slice(0, 6).map((h, i) => (
                      <li key={i}>
                        <strong>{h.institution}</strong>
                        {h.value_usd != null && ` — ${fmtMoney(h.value_usd)}`}
                        {h.change_direction && <span className="muted"> ({h.change_direction})</span>}
                      </li>
                    ))}
                  </ul>
                </div>
              ) : (
                <p className="muted">Institutional ownership requires Equibles — not available in this environment.</p>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
