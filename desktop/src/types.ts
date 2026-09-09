// Mirrors the pydantic schemas in schemas/stock.py, schemas/comparison.py,
// schemas/watchlist.py on the OpenResearch FastAPI backend.

export interface ValuationSummary {
  fair_value_low: number;
  fair_value_high: number;
  current_price?: number | null;
  pe_ratio?: number | null;
  forward_pe?: number | null;
  eps?: number | null;
  revenue_growth_yoy?: number | null;
  profit_margin?: number | null;
  debt_to_equity?: number | null;
  market_cap?: number | null;
  moat_assessment: string;
  key_metrics: Record<string, string>;
}

export interface SentimentSummary {
  tone: "bullish" | "neutral" | "bearish";
  catalysts: string[];
  risks: string[];
  analyst_consensus?: string | null;
  recent_headlines: string[];
  sec_filings_summary?: string | null;
}

export interface InstitutionalHolder {
  institution: string;
  shares_held?: number | null;
  value_usd?: number | null;
  pct_of_shares_outstanding?: number | null;
  change_pct?: number | null;
  change_direction?: "increased" | "decreased" | "new" | "unchanged" | null;
}

export interface InstitutionalSnapshot {
  total_institutional_ownership_pct?: number | null;
  top_holders: InstitutionalHolder[];
  recent_changes_summary: string;
  as_of_quarter?: string | null;
}

export interface InsiderTransaction {
  insider_name: string;
  title?: string | null;
  transaction_type?: string | null;
  shares?: number | null;
  price_per_share?: number | null;
  total_value?: number | null;
  transaction_date?: string | null;
  form_type?: string | null;
}

export interface MarketStructureData {
  short_volume_pct?: number | null;
  short_interest_ratio?: number | null;
  fails_to_deliver?: number | null;
  short_interest_trend?: string | null;
  recent_insider_transactions: InsiderTransaction[];
  insider_net_activity?: "net_buyer" | "net_seller" | "neutral" | null;
  insider_summary: string;
  congressional_trades: string[];
}

export interface TechnicalIndicators {
  rsi_14?: number | null;
  macd?: number | null;
  macd_signal?: number | null;
  macd_histogram?: number | null;
  bb_upper?: number | null;
  bb_lower?: number | null;
  sma_50?: number | null;
  sma_200?: number | null;
  volume_avg_30d?: number | null;
  price_vs_sma50?: string | null;
  price_vs_sma200?: string | null;
  trend_signal?: string | null;
}

export interface ResearchBrief {
  ticker: string;
  company_name: string;
  as_of_date: string;
  verdict: "Strong Buy" | "Buy" | "Hold" | "Sell" | "Strong Sell";
  price_target_low: number;
  price_target_high: number;
  current_price?: number | null;
  summary: string;
  bull_case: string[];
  bear_case: string[];
  key_risks: string[];
  upcoming_catalysts: string[];
  fundamentals: ValuationSummary;
  sentiment: SentimentSummary;
  institutional?: InstitutionalSnapshot | null;
  market_structure?: MarketStructureData | null;
  technicals?: TechnicalIndicators | null;
  sources: string[];
}

export interface ComparisonVerdict {
  category: string;
  winner: string;
  rationale: string;
}

export interface ComparisonBrief {
  ticker_a: string;
  ticker_b: string;
  overall_lean: string;
  summary: string;
  categories: ComparisonVerdict[];
  brief_a: ResearchBrief;
  brief_b: ResearchBrief;
}

export interface TrendPoint {
  date: string;
  close?: number | null;
  revenue?: number | null;
  net_income?: number | null;
}

export interface VolatilityMetrics {
  ewma_annualized_pct?: number | null;
  garch_forecast_annualized_pct?: number | null;
  garch_long_run_annualized_pct?: number | null;
  interpretation: string;
}

export interface TrendData {
  ticker: string;
  price_history: TrendPoint[];
  annual_financials: TrendPoint[];
  previous_year_summary: string;
  volatility?: VolatilityMetrics | null;
}

export interface WatchlistItem {
  ticker: string;
  added_at: string;
  notes?: string | null;
}

export interface ClarificationResponse {
  result_type: "clarification";
  clarification_needed: true;
  message: string;
}

export interface WatchlistResponse {
  result_type: "watchlist";
  watchlist: WatchlistItem[];
}

// ── Portfolio (schemas/portfolio.py, store/portfolio_store.py) ──────────────

export interface PortfolioHolding {
  ticker: string;
  shares: number;
  cost_basis?: number | null;
  added_at: string;
}

export interface PortfolioResponse {
  portfolio: PortfolioHolding[];
}

export interface PortfolioOptimizeRequest {
  risk_aversion?: number;
  market_impact_coeff?: number;
  short_borrow_rate?: number;
  max_position_weight?: number;
  allow_short?: boolean;
}

export interface TradeRecommendation {
  ticker: string;
  current_weight: number;
  target_weight: number;
  trade_weight: number;
  action: "buy" | "sell" | "hold";
  est_market_impact_cost: number;
  est_holding_cost: number;
}

export interface PortfolioOptimizationResult {
  as_of_date: string;
  tickers: string[];
  expected_annual_return: number;
  expected_annual_volatility: number;
  total_est_cost: number;
  trades: TradeRecommendation[];
  notes: string[];
}

// /api/query's four possible shapes, discriminated by an explicit
// `result_type` field the backend adds only on this endpoint's responses
// (server.py's stock_query()) — not part of ResearchBrief/ComparisonBrief's
// own schemas, which stay unchanged for /api/stock-research and
// /api/stock-compare. Switch on `result_type`, not on which fields happen
// to be present (see StockPanel.tsx's queryResultType()).
export type QueryResponse =
  | ClarificationResponse
  | (ResearchBrief & { result_type: "research_brief" })
  | (ComparisonBrief & { result_type: "comparison_brief" })
  | WatchlistResponse;

// ── Document Insights (schemas/document_insights.py) ────────────────────────

export interface DocumentCitation {
  document_name: string;
  page: number;
  x: number;
  y: number;
  width: number;
  height: number;
  excerpt: string;
}

export interface DocumentInsightAnswer {
  ticker: string;
  document_name: string;
  summary: string;
  citations: DocumentCitation[];
}

// ── SEC Insights (schemas/sec_insights.py) ──────────────────────────────────

export interface SECCitation {
  filing_type: string;
  section: string;
  filing_date: string;
  excerpt: string;
}

export interface SECAnswer {
  ticker: string;
  question: string;
  answer: string;
  citations: SECCitation[];
}

// ── Research Primer (schemas/primer.py) ─────────────────────────────────────

export interface BusinessFoundation {
  overview: string;
  revenue_model: string;
  key_segments: string[];
  unit_economics_notes: string;
}

export interface DriverTreeItem {
  driver: string;
  direction: "tailwind" | "headwind" | "mixed";
  confidence: "high" | "medium" | "low";
  note: string;
}

export interface DebateItem {
  question: string;
  bull_view: string;
  bear_view: string;
  what_would_resolve_it: string;
}

export interface AdversarialReview {
  integrated_bear_case: string;
  reconciliation_notes: string[];
  numeric_sanity_checks: string[];
}

export interface ResearchPrimer {
  ticker: string;
  company_name: string;
  as_of_date: string;
  research_brief: ResearchBrief;
  trend: TrendData;
  business_foundation: BusinessFoundation;
  driver_tree: DriverTreeItem[];
  debate_map: DebateItem[];
  adversarial_review: AdversarialReview;
  underwriting_summary: string;
}

// ── Executive Board (schemas/board.py) ──────────────────────────────────────

export interface BoardRisk {
  description: string;
  severity: "low" | "medium" | "high" | "critical";
  owner?: string | null;
  mitigation?: string | null;
}

export interface BoardConflict {
  description: string;
  parties: string[];
  severity: "low" | "medium" | "high";
  suggested_resolution?: string | null;
}

export interface ActionItem {
  description: string;
  owner: string;
  due_date?: string | null;
  priority: "low" | "medium" | "high";
}

export interface BoardMemberView {
  agent_id: string;
  role: string;
  key_findings: string[];
  risks: BoardRisk[];
  recommendations: string[];
  questions_for_ceo: string[];
  confidence: number;
}

export interface BoardDecision {
  title: string;
  description: string;
  owner?: string | null;
  due_date?: string | null;
  options: string[];
  recommended?: string | null;
}

export interface BoardBriefing {
  session_date: string;
  mode: "weekly_review" | "decision_advisory" | "health_scan";
  executive_summary: string;
  org_health_score: number;
  red_flags: string[];
  cross_team_conflicts: BoardConflict[];
  top_priorities: string[];
  action_items: ActionItem[];
  board_member_views: BoardMemberView[];
  decisions_recommended: BoardDecision[];
}

// ── Interview Prep (schemas/interview.py) ───────────────────────────────────

export interface FitVerdict {
  overall_score: number;
  match_strengths: string[];
  gaps: string[];
  deal_breakers: string[];
  recommendation: "strong_fit" | "worth_pursuing" | "stretch" | "not_recommended";
  summary: string;
}

export interface CompanyProfile {
  culture_summary: string;
  interview_style: string;
  known_values: string[];
  prep_priorities: string[];
  red_flags: string[];
}

export interface QuestionSet {
  behavioural: string[];
  technical: string[];
  culture_fit: string[];
  curveball: string[];
}

export interface STARAnswer {
  question: string;
  situation: string;
  task: string;
  action: string;
  result: string;
  tailoring_note: string;
}

export interface AnswerSet {
  answers: STARAnswer[];
}

export interface TailoredResume {
  target_role: string;
  target_company: string;
  summary: string;
  highlighted_skills: string[];
  experience_bullets: string[];
  cover_letter_opener: string;
  full_resume_md: string;
  tailoring_notes: string[];
}

export interface InterviewPrepBrief {
  role_title: string;
  company_name: string;
  as_of_date: string;
  fit: FitVerdict;
  company: CompanyProfile;
  questions: QuestionSet;
  answers: AnswerSet;
  top_3_priorities: string[];
  tailored_resume?: TailoredResume | null;
}

// ── Real Estate Research (schemas/realestate.py) ────────────────────────────
// Nested snapshots (migration/labor/housing/etc.) are numerous and deep —
// rendered generically via KeyValueList rather than hand-typed field by field.

export interface RealEstateBrief {
  address: string;
  city: string;
  state: string;
  zip_code?: string | null;
  as_of_date: string;
  demand_verdict: "strong_inflow" | "moderate_inflow" | "neutral" | "moderate_outflow" | "strong_outflow";
  investment_signal: "Strong Buy" | "Buy" | "Hold" | "Sell" | "Strong Sell";
  confidence: number;
  city_migration: Record<string, unknown>;
  state_migration: Record<string, unknown>;
  migration_divergence?: string | null;
  labor_market: Record<string, unknown>;
  housing_market: Record<string, unknown>;
  cost_of_living: Record<string, unknown>;
  demand_factors: Record<string, unknown>;
  climate_risk?: Record<string, unknown> | null;
  rental_analysis?: Record<string, unknown> | null;
  document_insights: Record<string, unknown>[];
  summary: string;
  dominant_pull_factors: string[];
  dominant_push_factors: string[];
  key_risks: string[];
  upcoming_catalysts: string[];
  data_gaps: string[];
  sources: string[];
}
