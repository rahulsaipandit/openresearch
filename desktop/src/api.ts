// Thin fetch wrapper over the OpenResearch FastAPI backend (server.py,
// localhost:7842). No auth/session handling — this is a local desktop app
// talking to a local server.

import type {
  BoardBriefing,
  ComparisonBrief,
  DocumentInsightAnswer,
  InterviewPrepBrief,
  PortfolioOptimizationResult,
  PortfolioOptimizeRequest,
  PortfolioResponse,
  QueryResponse,
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

export function runRealEstateResearch(payload: Record<string, unknown>) {
  return request<RealEstateBrief>("/api/real-estate-research", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}
