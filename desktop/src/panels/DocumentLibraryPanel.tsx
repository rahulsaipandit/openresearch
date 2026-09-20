import { useRef, useState } from "react";
import {
  askInterviewAnswer,
  deleteInterviewDocument,
  getInterviewDocuments,
  uploadInterviewDocument,
} from "../api";
import type { Citation, DocumentRecord, DocumentType, MatchedSource } from "../types";

// Per-document RAG selection + source traceability (docs/designInterviewTool.md
// "Full Plan: Per-Document Selection + Source Traceability"). Two sections:
// a document library (list/upload/delete + staleness badge) and a grounding-
// scope tester that lets you pick documents and see exactly which page of
// which document backed the answer — there's no live chat surface in this
// app (POST /v1/interview/answer is Pluely's contract, consumed externally),
// so this is the closest thing to "RAG UI control in chat" for testing it.

const DOC_TYPE_OPTIONS: { value: DocumentType; label: string }[] = [
  { value: "resume", label: "Resume" },
  { value: "candidate_document", label: "Candidate document (write-up, incident, ...)" },
  { value: "seed_question", label: "Seed question" },
];

const ACCEPTED_DOC_EXTENSIONS = [".pdf", ".docx", ".txt", ".md"];

function isAcceptedDocument(file: File): boolean {
  const name = file.name.toLowerCase();
  return ACCEPTED_DOC_EXTENSIONS.some((ext) => name.endsWith(ext));
}

export function DocumentLibrarySection() {
  const [candidateId, setCandidateId] = useState("");
  const [documents, setDocuments] = useState<DocumentRecord[]>([]);
  const [docType, setDocType] = useState<DocumentType>("candidate_document");
  const [loading, setLoading] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState<{ done: number; total: number } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const folderInputRef = useRef<HTMLInputElement | null>(null);

  async function handleLoad() {
    if (!candidateId.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const res = await getInterviewDocuments(candidateId.trim());
      setDocuments(res.documents);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  async function handleUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const files = Array.from(e.target.files ?? []).filter(isAcceptedDocument);
    if (files.length === 0 || !candidateId.trim()) return;
    setUploading(true);
    setUploadProgress({ done: 0, total: files.length });
    setError(null);
    try {
      for (let i = 0; i < files.length; i++) {
        try {
          await uploadInterviewDocument(candidateId.trim(), files[i], docType);
        } catch (err) {
          setError(`${files[i].name}: ${err instanceof Error ? err.message : String(err)}`);
        }
        setUploadProgress({ done: i + 1, total: files.length });
      }
      await handleLoad();
    } finally {
      setUploading(false);
      setUploadProgress(null);
      if (fileInputRef.current) fileInputRef.current.value = "";
      if (folderInputRef.current) folderInputRef.current.value = "";
    }
  }

  async function handleDelete(docId: string) {
    try {
      await deleteInterviewDocument(candidateId.trim(), docId);
      setDocuments((prev) => prev.filter((d) => d.doc_id !== docId));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  return (
    <div className="panel">
      <h3>Document Library (RAG)</h3>
      <div className="query-box">
        <input
          value={candidateId}
          onChange={(e) => setCandidateId(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleLoad()}
          placeholder="Candidate ID"
        />
        <button type="button" onClick={handleLoad} disabled={loading}>
          {loading ? "Loading..." : "Load"}
        </button>
      </div>

      <div className="form-row">
        <select value={docType} onChange={(e) => setDocType(e.target.value as DocumentType)}>
          {DOC_TYPE_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>
        <label className="muted">
          Files{" "}
          <input
            ref={fileInputRef}
            type="file"
            accept=".pdf,.docx,.txt,.md"
            multiple
            disabled={!candidateId.trim() || uploading}
            onChange={handleUpload}
          />
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
            disabled={!candidateId.trim() || uploading}
            onChange={handleUpload}
          />
        </label>
        {uploading && (
          <span className="muted">
            Ingesting{uploadProgress ? ` ${uploadProgress.done}/${uploadProgress.total}` : "..."}
          </span>
        )}
      </div>

      {error && <div className="error-banner">{error}</div>}

      <ul className="watchlist-grid">
        {documents.map((d) => (
          <li key={d.doc_id} className="watchlist-row">
            <span>
              {d.filename}
              {d.stale && <span className="stat-badge score-warn"> stale — needs re-indexing</span>}
            </span>
            <span className="added-at">
              {d.doc_type} · {d.page_count} page{d.page_count === 1 ? "" : "s"} ·{" "}
              {d.ingested_at ? new Date(d.ingested_at).toLocaleString() : ""}
            </span>
            <button type="button" className="remove-btn" onClick={() => handleDelete(d.doc_id)}>
              Delete
            </button>
          </li>
        ))}
        {documents.length === 0 && <li className="empty-state">No documents ingested yet.</li>}
      </ul>
    </div>
  );
}

export function AnswerTesterSection() {
  const [candidateId, setCandidateId] = useState("");
  const [documents, setDocuments] = useState<DocumentRecord[]>([]);
  const [selectedDocIds, setSelectedDocIds] = useState<string[]>([]);
  const [question, setQuestion] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [answerText, setAnswerText] = useState("");
  const [matchedSources, setMatchedSources] = useState<MatchedSource[]>([]);
  const [citations, setCitations] = useState<Citation[]>([]);

  async function handleLoadDocs() {
    if (!candidateId.trim()) return;
    try {
      const res = await getInterviewDocuments(candidateId.trim());
      setDocuments(res.documents);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  function toggleDoc(docId: string) {
    setSelectedDocIds((prev) => (prev.includes(docId) ? prev.filter((id) => id !== docId) : [...prev, docId]));
  }

  async function handleAsk() {
    if (!candidateId.trim() || !question.trim()) return;
    setLoading(true);
    setError(null);
    setAnswerText("");
    setMatchedSources([]);
    setCitations([]);
    try {
      const result = await askInterviewAnswer({
        candidate_id: candidateId.trim(),
        session_id: `desktop-tester-${Date.now()}`,
        question: question.trim(),
        document_ids: selectedDocIds.length > 0 ? selectedDocIds : undefined,
      });
      setAnswerText(result.answer_text);
      setMatchedSources(result.matched_sources);
      setCitations(result.citations);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="panel">
      <h3>Grounding-Scope Tester</h3>
      <p className="muted">
        Ask a question grounded in this candidate's memory — optionally scope it to specific documents
        instead of the whole corpus, and see exactly which page backed each part of the answer.
      </p>
      <div className="query-box">
        <input
          value={candidateId}
          onChange={(e) => setCandidateId(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleLoadDocs()}
          placeholder="Candidate ID"
        />
        <button type="button" onClick={handleLoadDocs}>
          Load documents
        </button>
      </div>

      {documents.length > 0 && (
        <div className="form-stack">
          <span className="muted">Grounding: {selectedDocIds.length === 0 ? "all documents" : `${selectedDocIds.length} selected`}</span>
          <ul className="watchlist-grid">
            {documents.map((d) => (
              <li key={d.doc_id} className="watchlist-row">
                <label>
                  <input
                    type="checkbox"
                    checked={selectedDocIds.includes(d.doc_id)}
                    onChange={() => toggleDoc(d.doc_id)}
                  />{" "}
                  {d.filename}
                </label>
                <span className="added-at">{d.doc_type}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <textarea
        value={question}
        onChange={(e) => setQuestion(e.target.value)}
        placeholder="Ask a live-interview-style question..."
        rows={3}
      />
      <button type="button" onClick={handleAsk} disabled={loading}>
        {loading ? "Asking..." : "Ask"}
      </button>

      {error && <div className="error-banner">{error}</div>}

      {answerText && (
        <div className="brief-view">
          <h4>Answer</h4>
          <p>{answerText}</p>

          {citations.length > 0 && (
            <>
              <h5>Citations</h5>
              <ul>
                {citations.map((c, i) => (
                  <li key={i}>
                    [{i + 1}] {c.filename}
                    {c.page_number ? ` — p.${c.page_number}` : ""}
                    {c.stale && <span className="stat-badge score-warn"> source changed since cited</span>}
                    <div className="muted">{c.chunk_excerpt}</div>
                  </li>
                ))}
              </ul>
            </>
          )}

          {matchedSources.length > 0 && (
            <>
              <h5>Matched sources</h5>
              <ul>
                {matchedSources.map((s, i) => (
                  <li key={i}>
                    [{s.source_type ?? "answer_bank"}] {s.title} ({s.category}
                    {s.page_number ? `, p.${s.page_number}` : ""})
                  </li>
                ))}
              </ul>
            </>
          )}
        </div>
      )}
    </div>
  );
}
