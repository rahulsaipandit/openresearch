"""
ResearchSynthesizer — Node 5 of the stock research pipeline.

LLM agent with a senior equity strategist persona.
Reads ValuationSummary + SentimentSummary (+ optional Equibles market structure data)
and produces the final ResearchBrief.

When Equibles data is present (institutional, market_structure, technicals), it is
injected into the prompt so the LLM can write bull/bear cases that cite real ownership
changes, short pressure, insider activity, and technical signals. The Equibles objects
are also attached directly to the returned ResearchBrief as typed sub-schemas.
"""

import json
import logging
from typing import Optional

from agents.api_utils import LLMClient
from schemas.stock import (
    ResearchBrief,
    ValuationSummary,
    SentimentSummary,
    InstitutionalSnapshot,
    InstitutionalHolder,
    MarketStructureData,
    InsiderTransaction,
    TechnicalIndicators,
)

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a senior equity strategist writing a one-page research brief for a portfolio manager.
Your job is to synthesize fundamental analysis, market sentiment, and market structure data into a clear, actionable brief.

Guidelines:
- Be direct. The PM reads 50 briefs a week.
- Give a clear verdict with price target range.
- Bull case and bear case must be SPECIFIC — cite actual metrics, events, or signals from the data provided.
  When institutional ownership, short interest, insider trades, or technical signals are provided, reference them.
- Acknowledge uncertainty honestly.

Return ONLY valid JSON matching the schema — no prose, no markdown fences."""

BRIEF_SCHEMA = """{
  "ticker": "<string>",
  "company_name": "<string>",
  "as_of_date": "<YYYY-MM-DD>",
  "verdict": "<Strong Buy|Buy|Hold|Sell|Strong Sell>",
  "price_target_low": <float>,
  "price_target_high": <float>,
  "current_price": <float or null>,
  "summary": "<2-3 sentence executive summary — cite a key metric or signal>",
  "bull_case": ["<specific bull point — cite data>", ...],
  "bear_case": ["<specific bear point — cite data>", ...],
  "key_risks": ["<risk>", ...],
  "upcoming_catalysts": ["<earnings date>", "<product launch>", ...],
  "sources": ["<url or source name>", ...]
}"""


class ResearchSynthesizerAgent:
    def __init__(self, llm: LLMClient, verbose: bool = False):
        self.llm     = llm
        self.verbose = verbose

    def synthesize(
        self,
        ticker: str,
        price_data: dict,
        fundamentals: ValuationSummary,
        sentiment: SentimentSummary,
        news_data: dict,
        institutional_raw: dict | None = None,
        market_structure_raw: dict | None = None,
        technicals_raw: dict | None = None,
    ) -> ResearchBrief:
        """
        Synthesize all research signals into a ResearchBrief.

        institutional_raw, market_structure_raw, technicals_raw are the raw dicts
        returned by DataFetcherAgent when Equibles is running. They are:
          1. Injected into the LLM prompt so the brief cites real signals.
          2. Parsed into typed schema objects and attached to the returned ResearchBrief.
        """
        from datetime import date

        prompt = self._build_prompt(
            ticker, price_data, fundamentals, sentiment,
            institutional_raw, market_structure_raw, technicals_raw,
        )

        if self.verbose:
            equibles_note = " (with Equibles data)" if institutional_raw or market_structure_raw else ""
            print(f"  [ResearchSynthesizer] Writing research brief for {ticker}{equibles_note}...")

        raw = self.llm.create(
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=2000,
        )

        # Parse typed Equibles schema objects (safe — returns None on any issue)
        institutional    = self._parse_institutional(institutional_raw)
        market_structure = self._parse_market_structure(market_structure_raw)
        technicals       = self._parse_technicals(technicals_raw)

        try:
            data = json.loads(raw)
            data["fundamentals"] = fundamentals.model_dump()
            data["sentiment"]    = sentiment.model_dump()
            # Attach Equibles sub-schemas
            data["institutional"]    = institutional.model_dump() if institutional else None
            data["market_structure"] = market_structure.model_dump() if market_structure else None
            data["technicals"]       = technicals.model_dump() if technicals else None
            # Collect source URLs from news
            data.setdefault("sources", [
                h.get("url", "") for h in news_data.get("headlines", [])[:5]
                if h.get("url")
            ])
            return ResearchBrief(**data)
        except Exception as e:
            logger.warning(f"ResearchSynthesizer JSON parse failed: {e}\nRaw: {raw[:400]}")
            return self._fallback_brief(
                ticker, price_data, fundamentals, sentiment,
                institutional, market_structure, technicals,
            )

    # ── Prompt builder ─────────────────────────────────────────────────────────

    def _build_prompt(
        self,
        ticker: str,
        price_data: dict,
        fundamentals: ValuationSummary,
        sentiment: SentimentSummary,
        institutional_raw: dict | None,
        market_structure_raw: dict | None,
        technicals_raw: dict | None,
    ) -> str:
        from datetime import date

        lines = [
            f"Ticker: {ticker}",
            f"Company: {price_data.get('company_name', ticker)}",
            f"Date: {date.today().isoformat()}",
            "",
            "=== Fundamental Analysis ===",
            f"  Fair value range: ${fundamentals.fair_value_low:.2f} – ${fundamentals.fair_value_high:.2f}",
            f"  Current price: {f'${fundamentals.current_price:.2f}' if fundamentals.current_price else 'N/A'}",
            f"  P/E: {fundamentals.pe_ratio or 'N/A'}",
            f"  Forward P/E: {fundamentals.forward_pe or 'N/A'}",
            f"  Revenue growth: {f'{fundamentals.revenue_growth_yoy:.1%}' if fundamentals.revenue_growth_yoy else 'N/A'}",
            f"  Profit margin: {f'{fundamentals.profit_margin:.1%}' if fundamentals.profit_margin else 'N/A'}",
            f"  Moat: {fundamentals.moat_assessment}",
        ]

        if fundamentals.key_metrics:
            for k, v in list(fundamentals.key_metrics.items())[:6]:
                lines.append(f"  {k}: {v}")

        lines += [
            "",
            "=== Sentiment Analysis ===",
            f"  Tone: {sentiment.tone}",
            f"  Catalysts: {', '.join(sentiment.catalysts[:4]) or 'None identified'}",
            f"  Risks: {', '.join(sentiment.risks[:4]) or 'None identified'}",
        ]

        if sentiment.analyst_consensus:
            lines.append(f"  Analyst consensus: {sentiment.analyst_consensus}")

        if sentiment.sec_filings_summary:
            lines.append(f"  SEC filings: {sentiment.sec_filings_summary}")

        # ── Equibles: institutional holdings ──────────────────────────────────
        if institutional_raw:
            lines.append("\n=== Institutional Ownership (13F) ===")
            total = institutional_raw.get("total_institutional_pct")
            if total is not None:
                lines.append(f"  Total institutional ownership: {total:.1f}%")
            quarter = institutional_raw.get("quarter")
            if quarter:
                lines.append(f"  As of: {quarter}")
            holders = institutional_raw.get("holders", [])
            if holders:
                lines.append("  Top holders (recent QoQ change):")
                for h in holders[:8]:
                    name   = h.get("institution", "")
                    pct    = h.get("pct_of_outstanding")
                    change = h.get("change_pct")
                    direction = h.get("change_direction", "")
                    parts = [f"    {name}"]
                    if pct is not None:
                        parts.append(f"{pct:.1f}% of outstanding")
                    if change is not None:
                        arrow = "▲" if (change or 0) > 0 else ("▼" if (change or 0) < 0 else "—")
                        parts.append(f"{arrow} {abs(change):.1f}% QoQ ({direction})")
                    lines.append(" | ".join(parts))

        # ── Equibles: short interest + insider activity ────────────────────────
        if market_structure_raw:
            lines.append("\n=== Market Structure ===")
            short_vol = market_structure_raw.get("short_volume_pct")
            days_cover = market_structure_raw.get("short_interest_ratio")
            ftd = market_structure_raw.get("fails_to_deliver")
            trend = market_structure_raw.get("short_interest_trend")
            if short_vol is not None:
                lines.append(f"  Short volume: {short_vol:.1f}% of daily volume")
            if days_cover is not None:
                lines.append(f"  Days-to-cover (short interest ratio): {days_cover:.1f}")
            if ftd is not None:
                lines.append(f"  SEC fails-to-deliver: {ftd:,}")
            if trend:
                lines.append(f"  Short interest trend: {trend}")

            net_activity = market_structure_raw.get("insider_net_activity")
            transactions = market_structure_raw.get("insider_transactions", [])
            if net_activity or transactions:
                lines.append(f"  Insider net activity (90 days): {net_activity or 'N/A'}")
                for t in transactions[:5]:
                    name  = t.get("name", "")
                    title = t.get("title", "")
                    ttype = t.get("type", "")
                    shares = t.get("shares")
                    value  = t.get("total_value")
                    tdate  = t.get("date", "")
                    parts = [f"    {name}"]
                    if title:
                        parts[0] += f" ({title})"
                    if ttype:
                        parts.append(ttype)
                    if shares is not None:
                        parts.append(f"{shares:,} shares")
                    if value is not None:
                        parts.append(f"${value:,.0f}")
                    if tdate:
                        parts.append(tdate)
                    lines.append(" | ".join(parts))

            congress = market_structure_raw.get("congressional_trades", [])
            if congress:
                lines.append("  Congressional disclosures:")
                for c in congress[:3]:
                    lines.append(f"    {c}")

        # ── Equibles: technical indicators ────────────────────────────────────
        if technicals_raw:
            lines.append("\n=== Technical Indicators ===")
            signal = technicals_raw.get("trend_signal")
            if signal:
                lines.append(f"  Signal: {signal}")
            rsi = technicals_raw.get("rsi_14")
            if rsi is not None:
                lines.append(f"  RSI (14): {rsi:.1f}")
            sma50  = technicals_raw.get("sma_50")
            sma200 = technicals_raw.get("sma_200")
            if sma50 is not None:
                vs50 = technicals_raw.get("price_vs_sma50", "")
                lines.append(f"  50-day SMA: ${sma50:.2f} (price is {vs50})")
            if sma200 is not None:
                vs200 = technicals_raw.get("price_vs_sma200", "")
                lines.append(f"  200-day SMA: ${sma200:.2f} (price is {vs200})")
            macd = technicals_raw.get("macd")
            macd_sig = technicals_raw.get("macd_signal")
            if macd is not None and macd_sig is not None:
                crossover = "bullish" if macd > macd_sig else "bearish"
                lines.append(f"  MACD: {macd:.3f} vs signal {macd_sig:.3f} ({crossover} crossover)")

        lines.append(f"\nWrite a ResearchBrief JSON matching this schema:\n{BRIEF_SCHEMA}")
        return "\n".join(lines)

    # ── Equibles schema parsers ────────────────────────────────────────────────

    def _parse_institutional(self, raw: dict | None) -> InstitutionalSnapshot | None:
        if not raw:
            return None
        try:
            holders = [
                InstitutionalHolder(
                    institution=h.get("institution", ""),
                    shares_held=h.get("shares_held"),
                    value_usd=h.get("value_usd"),
                    pct_of_shares_outstanding=h.get("pct_of_outstanding"),
                    change_pct=h.get("change_pct"),
                    change_direction=h.get("change_direction"),
                )
                for h in raw.get("holders", [])
            ]
            return InstitutionalSnapshot(
                total_institutional_ownership_pct=raw.get("total_institutional_pct"),
                top_holders=holders,
                recent_changes_summary=raw.get("summary", ""),
                as_of_quarter=raw.get("quarter"),
            )
        except Exception as e:
            logger.debug(f"InstitutionalSnapshot parse failed (non-fatal): {e}")
            return None

    def _parse_market_structure(self, raw: dict | None) -> MarketStructureData | None:
        if not raw:
            return None
        try:
            transactions = [
                InsiderTransaction(
                    insider_name=t.get("name", ""),
                    title=t.get("title"),
                    transaction_type=t.get("type"),
                    shares=t.get("shares"),
                    price_per_share=t.get("price_per_share"),
                    total_value=t.get("total_value"),
                    transaction_date=t.get("date"),
                    form_type=t.get("form"),
                )
                for t in raw.get("insider_transactions", [])
            ]

            net = raw.get("insider_net_activity")
            if net and net not in ("net_buyer", "net_seller", "neutral"):
                net = None     # guard against unexpected values

            # Build a human-readable insider summary
            summary_parts = []
            if net:
                summary_parts.append(f"Net {net.replace('_', ' ')} over 90 days")
            if transactions:
                buys  = sum(1 for t in transactions if "buy" in (t.transaction_type or "").lower())
                sells = sum(1 for t in transactions if "sell" in (t.transaction_type or "").lower())
                summary_parts.append(f"{buys} buys, {sells} sells ({len(transactions)} total transactions)")
            insider_summary = "; ".join(summary_parts)

            return MarketStructureData(
                short_volume_pct=raw.get("short_volume_pct"),
                short_interest_ratio=raw.get("short_interest_ratio"),
                fails_to_deliver=raw.get("fails_to_deliver"),
                short_interest_trend=raw.get("short_interest_trend"),
                recent_insider_transactions=transactions,
                insider_net_activity=net,
                insider_summary=insider_summary,
                congressional_trades=raw.get("congressional_trades", []),
            )
        except Exception as e:
            logger.debug(f"MarketStructureData parse failed (non-fatal): {e}")
            return None

    def _parse_technicals(self, raw: dict | None) -> TechnicalIndicators | None:
        if not raw:
            return None
        try:
            return TechnicalIndicators(
                rsi_14=raw.get("rsi_14"),
                macd=raw.get("macd"),
                macd_signal=raw.get("macd_signal"),
                macd_histogram=raw.get("macd_histogram"),
                bb_upper=raw.get("bb_upper"),
                bb_lower=raw.get("bb_lower"),
                sma_50=raw.get("sma_50"),
                sma_200=raw.get("sma_200"),
                volume_avg_30d=raw.get("volume_avg_30d"),
                price_vs_sma50=raw.get("price_vs_sma50"),
                price_vs_sma200=raw.get("price_vs_sma200"),
                trend_signal=raw.get("trend_signal"),
            )
        except Exception as e:
            logger.debug(f"TechnicalIndicators parse failed (non-fatal): {e}")
            return None

    # ── Fallback ───────────────────────────────────────────────────────────────

    def _fallback_brief(
        self,
        ticker: str,
        price_data: dict,
        fundamentals: ValuationSummary,
        sentiment: SentimentSummary,
        institutional: InstitutionalSnapshot | None = None,
        market_structure: MarketStructureData | None = None,
        technicals: TechnicalIndicators | None = None,
    ) -> ResearchBrief:
        from datetime import date
        return ResearchBrief(
            ticker=ticker,
            company_name=price_data.get("company_name", ticker),
            as_of_date=date.today().isoformat(),
            verdict="Hold",
            price_target_low=fundamentals.fair_value_low,
            price_target_high=fundamentals.fair_value_high,
            current_price=fundamentals.current_price,
            summary="Analysis pipeline encountered an error. Manual review required.",
            bull_case=sentiment.catalysts[:3],
            bear_case=sentiment.risks[:3],
            key_risks=sentiment.risks,
            upcoming_catalysts=[],
            fundamentals=fundamentals,
            sentiment=sentiment,
            institutional=institutional,
            market_structure=market_structure,
            technicals=technicals,
            sources=[],
        )
