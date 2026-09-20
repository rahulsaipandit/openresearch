// Thin fetch wrapper over the OpenResearch FastAPI backend (server.py,
// localhost:7842). No auth/session handling — this is a local desktop app
// talking to a local server.

import type {
  AlertsResponse,
  BoardBriefing,
  ComparisonBrief,
  DocumentInsightAnswer,
  DocumentListResponse,
  DocumentType,
  DocumentUploadResult,
  InterviewAnswerResult,
  InterviewPrepBrief,
  PortfolioOptimizationResult,
  PortfolioOptimizeRequest,
  PortfolioResponse,
  QueryResponse,
  QuestionListResponse,
  QuotesResponse,
  RealEstateBrief,
  ResearchBrief,
  ResearchPrimer,
  SECAnswer,
  TrendData,
  WatchlistResponse,
} from "./types";

const BASE_URL = "http://127.0.0.1:7842";

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`${res.status} ${res.statusText}: ${text}`);
  }
  return res.json() as Promise<T>;
}

// ── Stock Research ───────────────────────────────────────────────────────────

export function runStockResearch(ticker: string, depth: "quick" | "full" = "full") {
  return request<ResearchBrief>("/api/stock-research", {
    method: "POST",
    body: JSON.stringify({ ticker, depth }),
  });
}

export function runQuery(query: string, depth?: "quick" | "full") {
  return request<QueryResponse>("/api/query", {
    method: "POST",
    body: JSON.stringify({ query, depth }),
  });
}

export function compareStocks(tickerA: string, tickerB: string, depth: "quick" | "full" = "full") {
  return request<ComparisonBrief>("/api/stock-compare", {
    method: "POST",
    body: JSON.stringify({ ticker_a: tickerA, ticker_b: tickerB, depth }),
  });
}

export function runStockPrimer(ticker: string, depth: "quick" | "full" = "full") {
  return request<ResearchPrimer>("/api/stock-primer", {
    method: "POST",
    body: JSON.stringify({ ticker, depth }),
  });
}

export async function askDocumentInsights(ticker: string, file: File): Promise<DocumentInsightAnswer> {
  const formData = new FormData();
  formData.append("ticker", ticker);
  formData.append("file", file);

  const res = await fetch(`${BASE_URL}/api/stock-document-insights`, {
    method: "POST",
    body: formData, // no Content-Type header — browser sets the multipart boundary
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`${res.status} ${res.statusText}: ${text}`);
  }
  return res.json() as Promise<DocumentInsightAnswer>;
}

export function askSECInsights(ticker: string, question: string, forceRefresh = false) {
  return request<SECAnswer>("/api/sec-insights", {
    method: "POST",
    body: JSON.stringify({ ticker, question, force_refresh: forceRefresh }),
  });
}

export function getTrend(ticker: string) {
  return request<TrendData>(`/api/stock-trend/${encodeURIComponent(ticker)}`);
}

export function getWatchlist() {
  return request<WatchlistResponse>("/api/watchlist");
}

export function addToWatchlist(ticker: string, notes?: string) {
  return request<WatchlistResponse>("/api/watchlist", {
    method: "POST",
    body: JSON.stringify({ ticker, notes }),
  });
}

export function removeFromWatchlist(ticker: string) {
  return request<WatchlistResponse>(`/api/watchlist/${encodeURIComponent(ticker)}`, {
    method: "DELETE",
  });
}

export function getWatchlistQuotes() {
  return request<QuotesResponse>("/api/watchlist/quotes");
}

// ── Price Alerts ──────────────────────────────────────────────────────────────

export function getAlerts() {
  return request<AlertsResponse>("/api/alerts");
}

export function createAlert(ticker: string, condition: "ABOVE" | "BELOW", targetPrice: number) {
  return request<AlertsResponse>("/api/alerts", {
    method: "POST",
    body: JSON.stringify({ ticker, condition, target_price: targetPrice }),
  });
}

export function deleteAlert(alertId: string) {
  return request<AlertsResponse>(`/api/alerts/${encodeURIComponent(alertId)}`, {
    method: "DELETE",
  });
}

export function getHealth() {
  return request<{ status: string }>("/api/health");
}

// ── Portfolio ─────────────────────────────────────────────────────────────────

export function getPortfolio() {
  return request<PortfolioResponse>("/api/portfolio");
}

export function upsertPortfolioHolding(ticker: string, shares: number, costBasis?: number) {
  return request<PortfolioResponse>("/api/portfolio", {
    method: "POST",
    body: JSON.stringify({ ticker, shares, cost_basis: costBasis }),
  });
}

export function removePortfolioHolding(ticker: string) {
  return request<PortfolioResponse>(`/api/portfolio/${encodeURIComponent(ticker)}`, {
    method: "DELETE",
  });
}

export function optimizePortfolio(options: PortfolioOptimizeRequest = {}) {
  return request<PortfolioOptimizationResult>("/api/portfolio-optimize", {
    method: "POST",
    body: JSON.stringify(options),
  });
}

// ── Other verticals — thin passthroughs, no stock-specific logic needed ────

export function runBoardSession(payload: Record<string, unknown>) {
  return request<{ session_id: string }>("/api/board-session", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function getBoardStatus(sessionId: string) {
  return request<{ status: string; result: BoardBriefing | null; error: string | null }>(
    `/api/board-status/${sessionId}`
  );
}

export function runInterviewPrep(payload: Record<string, unknown>) {
  return request<InterviewPrepBrief>("/api/interview-prep", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function getInterviewQuestions(candidateId: string) {
  return request<QuestionListResponse>(`/v1/interview/questions/${encodeURIComponent(candidateId)}`);
}

export function deleteInterviewQuestion(candidateId: string, questionId: string) {
  return request<{ deleted: string }>(
    `/v1/interview/questions/${encodeURIComponent(candidateId)}/${encodeURIComponent(questionId)}`,
    { method: "DELETE" }
  );
}

// ── Document RAG ingestion (docs/designInterviewTool.md) ────────────────────

export function getInterviewDocuments(candidateId: string) {
  return request<DocumentListResponse>(`/v1/interview/documents/${encodeURIComponent(candidateId)}`);
}

export async function uploadInterviewDocument(
  candidateId: string,
  file: File,
  docType: DocumentType
): Promise<DocumentUploadResult> {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("doc_type", docType);

  const res = await fetch(`${BASE_URL}/v1/interview/documents/${encodeURIComponent(candidateId)}`, {
    method: "POST",
    body: formData, // no Content-Type header — browser sets the multipart boundary
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`${res.status} ${res.statusText}: ${text}`);
  }
  return res.json() as Promise<DocumentUploadResult>;
}

export function deleteInterviewDocument(candidateId: string, docId: string) {
  return request<{ deleted: string }>(
    `/v1/interview/documents/${encodeURIComponent(candidateId)}/${encodeURIComponent(docId)}`,
    { method: "DELETE" }
  );
}

// POST /v1/interview/answer is an SSE stream (Pluely's live-coaching
// contract) — there's no non-streaming variant. For the desktop app's
// grounding-scope tester (not a full chat surface — see
// docs/designInterviewTool.md's "Desktop UI" section) we consume the whole
// stream here and hand back one assembled result, rather than teaching the
// UI to render incremental SSE frames for what's meant to be a quick check.
export async function askInterviewAnswer(payload: {
  candidate_id: string;
  session_id: string;
  question: string;
  document_ids?: string[];
}): Promise<InterviewAnswerResult> {
  const res = await fetch(`${BASE_URL}/v1/interview/answer`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok || !res.body) {
    const text = await res.text().catch(() => "");
    throw new Error(`${res.status} ${res.statusText}: ${text}`);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let answerText = "";
  let final: { matched_sources: unknown[]; images_ignored: boolean; citations: unknown[] } | null = null;

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    let boundary: number;
    while ((boundary = buffer.indexOf("\n\n")) !== -1) {
      const frame = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      const line = frame.startsWith("data: ") ? frame.slice(6) : frame;
      if (!line.trim()) continue;
      const parsed = JSON.parse(line);
      answerText += parsed.answer_chunk ?? "";
      if (parsed.done) final = parsed.metadata;
    }
  }

  return {
    answer_text: answerText,
    matched_sources: (final?.matched_sources ?? []) as InterviewAnswerResult["matched_sources"],
    images_ignored: final?.images_ignored ?? false,
    citations: (final?.citations ?? []) as InterviewAnswerResult["citations"],
  };
}

export function runRealEstateResearch(payload: Record<string, unknown>) {
  return request<RealEstateBrief>("/api/real-estate-research", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}
