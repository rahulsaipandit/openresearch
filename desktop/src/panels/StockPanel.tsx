import { useState } from "react";
import { runQuery } from "../api";
import type { ClarificationResponse, QueryResponse, ResearchBrief } from "../types";
import { CitedText } from "../components/CitedText";
import { DataTable } from "../components/DataTable";
import { WatchlistPanel } from "./WatchlistPanel";
import { PortfolioPanel } from "./PortfolioPanel";
import { PairsTradingPanel } from "./PairsTradingPanel";
import { ComparisonPanel } from "./ComparisonPanel";
import { TrendPanel } from "./TrendPanel";
import { PrimerPanel } from "./PrimerPanel";
import { SECInsightsPanel } from "./SECInsightsPanel";
import { DocumentInsightsPanel } from "./DocumentInsightsPanel";
import { DashboardPanel } from "./DashboardPanel";

type SubTab =
  | "research"
  | "dashboard"
  | "watchlist"
  | "portfolio"
  | "pairs"
  | "compare"
  | "trend"
  | "primer"
  | "sec"
  | "documents";

function isClarification(r: QueryResponse): r is ClarificationResponse {
  return r.result_type === "clarification";
}

function isResearchBrief(r: QueryResponse): r is ResearchBrief & { result_type: "research_brief" } {
  return r.result_type === "research_brief";
}

// Single-shot query -> structured result view, per requirements.md's Query
// Interface Layout spec — deliberately not a multi-turn chat UI (no
// requirement calls for one, and Tolaria vault export already covers
// history — see requirements.md).
export function StockPanel() {
  const [subTab, setSubTab] = useState<SubTab>("research");
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<ResearchBrief | null>(null);
  const [clarification, setClarification] = useState<string | null>(null);

  async function handleAsk() {
    if (!query.trim()) return;
    setLoading(true);
    setError(null);
    setClarification(null);
    setResult(null);
    try {
      const res = await runQuery(query.trim());
      if (isClarification(res)) {
        setClarification(res.message);
      } else if (isResearchBrief(res)) {
        setResult(res);
      } else if (res.result_type === "watchlist") {
        setClarification("Added to your watchlist — check the Watchlist tab.");
      } else {
        setClarification("This resolved to a comparison — check the Compare tab and re-run it there.");
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="panel">
      <div className="sub-nav no-print">
        {(
          ["research", "dashboard", "watchlist", "portfolio", "pairs", "compare", "trend", "primer", "sec", "documents"] as SubTab[]
        ).map((t) => (
          <button key={t} type="button" className={subTab === t ? "active" : ""} onClick={() => setSubTab(t)}>
            {t === "sec" ? "SEC Insights" : t.charAt(0).toUpperCase() + t.slice(1)}
          </button>
        ))}
      </div>

      {subTab === "research" && (
        <div>
          <div className="query-box">
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleAsk()}
              placeholder='Ask a question, e.g. "Is it a good time to invest in Reliance Industries?"'
            />
            <button type="button" onClick={handleAsk} disabled={loading}>
              {loading ? "Analyzing..." : "Ask"}
            </button>
          </div>
          <p className="disclaimer">Research assistant — not investment advice.</p>

          {error && <div className="error-banner">{error}</div>}
          {clarification && <div className="clarification-banner">{clarification}</div>}
          {result && <ResearchBriefView brief={result} />}
        </div>
      )}

      {subTab === "dashboard" && <DashboardPanel />}
      {subTab === "watchlist" && <WatchlistPanel />}
      {subTab === "portfolio" && <PortfolioPanel />}
      {subTab === "pairs" && <PairsTradingPanel />}
      {subTab === "compare" && <ComparisonPanel />}
      {subTab === "trend" && <TrendPanel />}
      {subTab === "primer" && <PrimerPanel />}
      {subTab === "sec" && <SECInsightsPanel />}
      {subTab === "documents" && <DocumentInsightsPanel />}
    </div>
  );
}

function ResearchBriefView({ brief }: { brief: ResearchBrief }) {
  const verdictClass = `verdict-${brief.verdict.toLowerCase().replace(/\s+/g, "-")}`;

  return (
    <div className="brief-view">
      <h2>
        {brief.company_name} ({brief.ticker}) — <span className={`verdict ${verdictClass}`}>{brief.verdict}</span>
      </h2>
      <p>
        Price target: ${brief.price_target_low.toFixed(0)}–${brief.price_target_high.toFixed(0)}
        {brief.current_price != null && ` | Current: $${brief.current_price.toFixed(2)}`}
      </p>

      <CitedText text={brief.summary} sources={brief.sources} />

      <div className="two-col">
        <div>
          <h4>Bull Case</h4>
          <ul>
            {brief.bull_case.map((b, i) => (
              <li key={i}>{b}</li>
            ))}
          </ul>
        </div>
        <div>
          <h4>Bear Case</h4>
          <ul>
            {brief.bear_case.map((b, i) => (
              <li key={i}>{b}</li>
            ))}
          </ul>
        </div>
      </div>

      <h4>Fundamentals</h4>
      <DataTable
        columns={["Metric", "Value"]}
        rows={[
          ["P/E", brief.fundamentals.pe_ratio ?? "N/A"],
          ["Forward P/E", brief.fundamentals.forward_pe ?? "N/A"],
          ["EPS", brief.fundamentals.eps ?? "N/A"],
          ["Revenue Growth YoY", brief.fundamentals.revenue_growth_yoy ?? "N/A"],
          ["Profit Margin", brief.fundamentals.profit_margin ?? "N/A"],
          ["Debt/Equity", brief.fundamentals.debt_to_equity ?? "N/A"],
        ]}
        filename={`${brief.ticker}-fundamentals`}
      />

      <h4>Key Risks</h4>
      <ul>
        {brief.key_risks.map((r, i) => (
          <li key={i}>{r}</li>
        ))}
      </ul>

      <h4>Upcoming Catalysts</h4>
      <ul>
        {brief.upcoming_catalysts.map((c, i) => (
          <li key={i}>{c}</li>
        ))}
      </ul>
    </div>
  );
}
