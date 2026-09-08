import { useRef, useState } from "react";
import { askDocumentInsights } from "../api";
import type { DocumentInsightAnswer } from "../types";

// Document Insights — upload a PDF (earnings-call transcript, analyst
// report, filing excerpt) and get a cited summary. Citations are page-level
// (LiteParse bounding-box anchors), not a full PDF-viewer highlight overlay
// — that's a larger UI investment not attempted in this pass. See
// requirements.md for the LiteParse integration scoping note.
export function DocumentInsightsPanel() {
  const [ticker, setTicker] = useState("");
  const [fileName, setFileName] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [answer, setAnswer] = useState<DocumentInsightAnswer | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  async function handleUpload() {
    const file = fileInputRef.current?.files?.[0];
    if (!ticker.trim() || !file) return;

    setLoading(true);
    setError(null);
    setAnswer(null);
    setFileName(file.name);
    try {
      const res = await askDocumentInsights(ticker.trim(), file);
      setAnswer(res);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div>
      <h3>Document Insights</h3>
      <p className="muted">
        Upload an earnings-call transcript, analyst report, or filing excerpt (PDF) to get a
        cited summary — page-level citations, not a full highlight overlay.
      </p>
      <div className="query-box">
        <input value={ticker} onChange={(e) => setTicker(e.target.value)} placeholder="Ticker, e.g. DKNG" />
      </div>
      <div className="query-box">
        <input ref={fileInputRef} type="file" accept="application/pdf" />
        <button type="button" onClick={handleUpload} disabled={loading}>
          {loading ? "Parsing + summarizing..." : "Upload &amp; Summarize"}
        </button>
      </div>

      {error && <div className="error-banner">{error}</div>}

      {answer && (
        <div className="brief-view">
          <p className="muted">{fileName}</p>
          <p>{answer.summary}</p>

          {answer.citations.length > 0 && (
            <>
              <h4>Citations</h4>
              {answer.citations.map((c, i) => (
                <div key={i} className="card">
                  <p className="muted">
                    {c.document_name} — Page {c.page}
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
