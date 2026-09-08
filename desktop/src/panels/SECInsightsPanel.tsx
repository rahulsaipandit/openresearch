import { useState } from "react";
import { askSECInsights } from "../api";
import type { SECAnswer } from "../types";

// SEC Insights — question/answer over a ticker's SEC filings, with citations
// back to filing/section (see requirements.md for the sec-insights-inspired
// scoping decision: local chromadb semantic search + EdgarTools ingestion,
// no Postgres/PGVector/S3 infra).
export function SECInsightsPanel() {
  const [ticker, setTicker] = useState("");
  const [question, setQuestion] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [answer, setAnswer] = useState<SECAnswer | null>(null);

  async function handleAsk(forceRefresh = false) {
    if (!ticker.trim() || !question.trim()) return;
    setLoading(true);
    setError(null);
    setAnswer(null);
    try {
      const res = await askSECInsights(ticker.trim(), question.trim(), forceRefresh);
      setAnswer(res);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div>
      <h3>SEC Insights</h3>
      <p className="muted">
        Ask a question about a company's 10-K/10-Q filings. The first question for a new
        ticker takes longer — filings are fetched and indexed locally on demand.
      </p>
      <div className="query-box">
        <input value={ticker} onChange={(e) => setTicker(e.target.value)} placeholder="Ticker, e.g. AAPL" />
      </div>
      <div className="query-box">
        <input
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleAsk()}
          placeholder="e.g. What are the main risk factors?"
        />
        <button type="button" onClick={() => handleAsk(false)} disabled={loading}>
          {loading ? "Searching filings..." : "Ask"}
        </button>
      </div>
      {answer && (
        <button type="button" className="link-btn" onClick={() => handleAsk(true)} disabled={loading}>
          Refresh filings and re-ask
        </button>
      )}

      {error && <div className="error-banner">{error}</div>}

      {answer && (
        <div className="brief-view">
          <p>{answer.answer}</p>

          {answer.citations.length > 0 && (
            <>
              <h4>Citations</h4>
              {answer.citations.map((c, i) => (
                <div key={i} className="card">
                  <p className="muted">
                    [{i + 1}] {c.filing_type} &middot; {c.section.replace(/_/g, " ")} &middot; {c.filing_date}
                  </p>
                  <p>{c.excerpt}</p>
                </div>
              ))}
            </>
          )}
        </div>
      )}
    </div>
  );
}
