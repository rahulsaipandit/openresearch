import { useRef, useState } from "react";
import { askDocumentInsights } from "../api";
import type { DocumentInsightAnswer } from "../types";

// Document Insights — upload one or more PDFs (earnings-call transcripts,
// analyst reports, filing excerpts), or a whole folder of them, and get a
// cited summary per document. Citations are page-level (LiteParse
// bounding-box anchors), not a full PDF-viewer highlight overlay — that's a
// larger UI investment not attempted in this pass. See requirements.md for
// the LiteParse integration scoping note.
export function DocumentInsightsPanel() {
  const [ticker, setTicker] = useState("");
  const [loading, setLoading] = useState(false);
  const [progress, setProgress] = useState<{ done: number; total: number } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [answers, setAnswers] = useState<DocumentInsightAnswer[]>([]);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const folderInputRef = useRef<HTMLInputElement | null>(null);

  async function handleUpload() {
    const files = [
      ...Array.from(fileInputRef.current?.files ?? []),
      ...Array.from(folderInputRef.current?.files ?? []),
    ].filter((f) => f.name.toLowerCase().endsWith(".pdf"));
    if (!ticker.trim() || files.length === 0) return;

    setLoading(true);
    setError(null);
    setAnswers([]);
    setProgress({ done: 0, total: files.length });
    const results: DocumentInsightAnswer[] = [];
    for (let i = 0; i < files.length; i++) {
      try {
        results.push(await askDocumentInsights(ticker.trim(), files[i]));
      } catch (e) {
        setError(`${files[i].name}: ${e instanceof Error ? e.message : String(e)}`);
      }
      setProgress({ done: i + 1, total: files.length });
      setAnswers([...results]);
    }
    setLoading(false);
    setProgress(null);
    if (fileInputRef.current) fileInputRef.current.value = "";
    if (folderInputRef.current) folderInputRef.current.value = "";
  }

  return (
    <div>
      <h3>Document Insights</h3>
      <p className="muted">
        Upload one or more earnings-call transcripts, analyst reports, or filing excerpts (PDF) —
        or a whole folder of them — to get a cited summary per document. Page-level citations,
        not a full highlight overlay.
      </p>
      <div className="query-box">
        <input value={ticker} onChange={(e) => setTicker(e.target.value)} placeholder="Ticker, e.g. DKNG" />
      </div>
      <div className="query-box">
        <label className="muted">
          Files{" "}
          <input ref={fileInputRef} type="file" accept="application/pdf" multiple />
        </label>
        <label className="muted">
          Folder{" "}
          <input
            ref={(el) => {
              folderInputRef.current = el;
              if (el) {
                el.setAttribute("webkitdirectory", "");
                el.setAttribute("directory", "");
              }
            }}
            type="file"
            multiple
          />
        </label>
        <button type="button" onClick={handleUpload} disabled={loading}>
          {loading
            ? `Parsing + summarizing${progress ? ` ${progress.done}/${progress.total}` : "..."}`
            : "Upload & Summarize"}
        </button>
      </div>

      {error && <div className="error-banner">{error}</div>}

      {answers.map((answer, i) => (
        <div key={i} className="brief-view">
          <p className="muted">{answer.document_name}</p>
          <p>{answer.summary}</p>

          {answer.citations.length > 0 && (
            <>
              <h4>Citations</h4>
              {answer.citations.map((c, j) => (
                <div key={j} className="card">
                  <p className="muted">
                    {c.document_name} — Page {c.page}
                  </p>
                  <p>{c.excerpt}</p>
                </div>
              ))}
            </>
          )}
        </div>
      ))}
    </div>
  );
}
