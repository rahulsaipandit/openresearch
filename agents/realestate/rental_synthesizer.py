"""
RentalSynthesizerAgent — LLM synthesis of all rental analysis data.

Ingests:
  - RentalUnderwritingSnapshot (financial model)
  - RegulatoryRiskSnapshot (landlord law, rent control, STR, insurance)
  - NeighborhoodSnapshot (schools, vacancy, tract demographics, walkability)
  - City-level context (migration, labor, housing, climate)

Produces RentalAnalysis with:
  - feasibility_verdict: highly_viable | viable | marginal | not_viable
  - rental_summary: 3–5 sentence narrative
  - pros: quantified investment positives
  - cons: quantified risks/negatives
  - recommended_actions: due-diligence checklist
"""

import json
import logging
from typing import Optional

from agents.api_utils import LLMClient
from schemas.realestate import (
    GeoResolution, MigrationSnapshot, LaborMarketSnapshot,
    HousingMarketSnapshot, CostOfLivingSnapshot, ClimateRiskSnapshot,
    RentalUnderwritingSnapshot, RegulatoryRiskSnapshot, NeighborhoodSnapshot,
    RentalAnalysis,
)

logger = logging.getLogger(__name__)


RENTAL_SYSTEM = """You are a professional real estate investment analyst specialising in rental property feasibility.

You will receive a structured digest of financial, regulatory, neighborhood, and market data for a rental property.

Your job:
1. Assess rental investment feasibility with precision — use actual numbers, not vague claims.
2. Issue a clear verdict: highly_viable | viable | marginal | not_viable
3. Write a 3–5 sentence summary that quantifies the key investment case.
4. List 3–5 quantified PROS (e.g. "Cap rate 7.2% — above 6% target")
5. List 3–5 quantified CONS / RISKS (e.g. "Negative cash flow: -$230/mo at 93% occupancy")
6. List 5–8 recommended actions for due diligence before closing.

Verdict guide:
- highly_viable: positive cash flow, cap rate ≥ 6%, DSCR ≥ 1.25, low regulatory risk
- viable: slight positive or break-even cash flow, DSCR ≥ 1.0, manageable risks
- marginal: negative cash flow but strong appreciation signal or high cap rate; or moderate regulatory risk
- not_viable: significantly negative cash flow, DSCR < 0.8, very high regulatory risk, or severe climate risk

Return ONLY valid JSON — no markdown fences, no prose outside JSON.
"""

RENTAL_SCHEMA = """{
  "feasibility_verdict": "<highly_viable|viable|marginal|not_viable>",
  "rental_summary": "<3-5 sentence quantified investment narrative>",
  "pros": [
    "<quantified positive — include actual numbers>",
    "..."
  ],
  "cons": [
    "<quantified risk — include actual numbers>",
    "..."
  ],
  "recommended_actions": [
    "<specific due-diligence action>",
    "..."
  ]
}"""


class RentalSynthesizerAgent:
    """LLM-driven synthesis of rental feasibility."""

    def __init__(self, llm: LLMClient, verbose: bool = False):
        self.llm     = llm
        self.verbose = verbose

    def synthesize(
        self,
        geo: GeoResolution,
        city: str,
        state: str,
        bedrooms: int,
        bathrooms: float,
        sqft: Optional[int],
        property_type: str,
        year_built: Optional[int],
        underwriting: RentalUnderwritingSnapshot,
        regulatory: RegulatoryRiskSnapshot,
        neighborhood: NeighborhoodSnapshot,
        city_migration: MigrationSnapshot,
        labor: LaborMarketSnapshot,
        housing: HousingMarketSnapshot,
        col: CostOfLivingSnapshot,
        climate: Optional[ClimateRiskSnapshot],
    ) -> RentalAnalysis:

        digest = self._build_digest(
            city, state, bedrooms, bathrooms, sqft, property_type, year_built,
            underwriting, regulatory, neighborhood,
            city_migration, labor, housing, col, climate,
        )

        user_msg = f"""Property Rental Analysis Digest:

{digest}

Based on the above data, produce a rental feasibility assessment.
Return ONLY JSON matching:

{RENTAL_SCHEMA}"""

        try:
            raw = self.llm.create(
                system   = RENTAL_SYSTEM,
                messages = [{"role": "user", "content": user_msg}],
                max_tokens = 1500,
            )
            data = json.loads(raw.strip())
            verdict  = data.get("feasibility_verdict", "marginal")
            summary  = data.get("rental_summary", "")
            pros     = data.get("pros", [])
            cons     = data.get("cons", [])
            actions  = data.get("recommended_actions", [])
        except Exception as e:
            logger.warning(f"RentalSynthesizer LLM failed: {e}")
            verdict, summary, pros, cons, actions = self._fallback(underwriting, regulatory, climate)

        return RentalAnalysis(
            bedrooms       = bedrooms,
            bathrooms      = bathrooms,
            sqft           = sqft,
            property_type  = property_type,
            year_built     = year_built,
            underwriting   = underwriting,
            regulatory     = regulatory,
            neighborhood   = neighborhood,
            feasibility_verdict  = verdict,   # type: ignore
            rental_summary       = summary,
            pros                 = pros,
            cons                 = cons,
            recommended_actions  = actions,
        )

    # ── Digest builder ─────────────────────────────────────────────────────────

    def _build_digest(
        self,
        city, state, bedrooms, bathrooms, sqft, property_type, year_built,
        uw: RentalUnderwritingSnapshot,
        reg: RegulatoryRiskSnapshot,
        nbhd: NeighborhoodSnapshot,
        mig: MigrationSnapshot,
        labor: LaborMarketSnapshot,
        housing: HousingMarketSnapshot,
        col: CostOfLivingSnapshot,
        climate: Optional[ClimateRiskSnapshot],
    ) -> str:

        def fmt(v, fmt_str=".0f", suffix=""):
            return f"{v:{fmt_str}}{suffix}" if v is not None else "n/a"

        lines = [
            "=== PROPERTY ===",
            f"Location: {city}, {state}",
            f"Type: {property_type} | {bedrooms}bd/{bathrooms}ba"
            + (f" | {sqft:,} sqft" if sqft else "")
            + (f" | Built {year_built}" if year_built else ""),
            "",
            "=== FINANCIAL MODEL ===",
            f"Purchase price:       ${fmt(uw.purchase_price)}",
            f"Est. market value:    ${fmt(uw.estimated_market_value)}",
            f"Monthly rent est.:    ${fmt(uw.estimated_monthly_rent)} "
            f"(range ${fmt(uw.rent_low)}–${fmt(uw.rent_high)}) "
            f"[source: {uw.rent_estimate_source}, confidence: {uw.rent_estimate_confidence or 'n/a'}]",
            f"Gross rent yield:     {fmt(uw.gross_rent_yield_pct, '.2f')}%",
            f"Gross Rent Multiplier:{fmt(uw.gross_rent_multiplier, '.1f')}x",
            f"Price-to-rent ratio:  {fmt(uw.price_to_rent_ratio, '.1f')}x",
            "",
            "Annual Expenses:",
            f"  Property tax:       ${fmt(uw.est_annual_property_tax)}",
            f"  Insurance:          ${fmt(uw.est_annual_insurance_total)}"
            + (" (incl. NFIP flood)" if uw.nfip_required else ""),
            f"  Vacancy (5%):       ${fmt(uw.est_annual_vacancy_loss)}",
            f"  Mgmt fee (9%):      ${fmt(uw.est_annual_mgmt_fee)}",
            f"  Maintenance:        ${fmt(uw.est_annual_maintenance)}",
            f"  CapEx reserve:      ${fmt(uw.est_annual_capex_reserve)}",
            f"  Total expenses:     ${fmt(uw.est_annual_total_expenses)}",
            "",
            f"Annual gross rent:    ${fmt(uw.est_annual_gross_rent)}",
            f"NOI:                  ${fmt(uw.est_annual_noi)}",
            f"Cap rate:             {fmt(uw.cap_rate_pct, '.2f')}%",
            "",
            f"Down payment ({uw.down_payment_pct*100:.0f}%): ${fmt(uw.down_payment_amount)}",
            f"Loan amount:          ${fmt(uw.loan_amount)}",
            f"Rate/term:            {uw.interest_rate_pct:.2f}% / {uw.loan_term_years}yr",
            f"Monthly mortgage:     ${fmt(uw.monthly_mortgage_payment)}",
            f"Annual debt service:  ${fmt(uw.annual_debt_service)}",
            "",
            f"Annual cash flow:     ${fmt(uw.annual_cash_flow)} "
            f"(${fmt(uw.monthly_cash_flow)}/mo) → {uw.cash_flow_verdict or 'n/a'}",
            f"Cash-on-cash return:  {fmt(uw.cash_on_cash_return_pct, '.2f')}%",
            f"DSCR:                 {fmt(uw.dscr, '.2f')}",
            f"Break-even occ.:      {fmt(uw.break_even_occupancy_pct, '.1f')}%",
        ]
        if uw.underwriting_notes:
            lines += ["", "Underwriting flags:"] + [f"  ⚠ {n}" for n in uw.underwriting_notes]

        lines += [
            "",
            "=== REGULATORY ===",
            f"Eviction: {reg.eviction_friendliness or 'unknown'} (~{reg.state_eviction_timeline_days or '?'} days). "
            + reg.eviction_process_notes,
            f"Rent control: {'YES — ' + (reg.rent_control_type or '') if reg.rent_control_exposure else 'No'}. "
            + reg.rent_control_details,
            f"STR (Airbnb): {'permitted' if reg.str_generally_permitted else 'NOT permitted'}. {reg.str_notes}",
            f"Insurance market: {reg.insurance_market_stress or 'normal'}. {reg.insurance_stress_notes}",
            f"Just-cause eviction required: {reg.just_cause_eviction_required}",
            f"Overall regulatory risk: {reg.overall_regulatory_risk}",
        ]

        lines += [
            "",
            "=== NEIGHBORHOOD ===",
            f"Tract median income:  ${fmt(nbhd.tract_median_income)} "
            + (f"(+{nbhd.tract_income_growth_5yr_pct:.1f}% 5yr)" if nbhd.tract_income_growth_5yr_pct else ""),
            f"Owner-occupancy:      {fmt(nbhd.tract_owner_occ_pct, '.1f')}%",
            f"College educated:     {fmt(nbhd.tract_college_edu_pct, '.1f')}%",
            f"ZIP rental vacancy:   {fmt(nbhd.zip_rental_vacancy_rate, '.1f')}%",
            f"Rental demand signal: {nbhd.rental_demand_signal or 'n/a'}",
            f"Walkability:          {fmt(nbhd.walkability_score, '.0f')}/100 | "
            f"Transit: {fmt(nbhd.transit_score, '.0f')}/100",
            f"Neighborhood trajectory: {nbhd.neighborhood_trajectory or 'unknown'}",
        ]

        lines += [
            "",
            "=== MARKET CONTEXT ===",
            f"City migration:   {mig.net_direction} (confidence {mig.confidence:.0%}). {mig.summary[:150]}",
            f"Unemployment:     {fmt(labor.unemployment_rate, '.1f')}% ({labor.unemployment_trend or 'n/a'})",
            f"Employment growth:{fmt(labor.employment_growth_pct_yoy, '.1f')}% YoY",
            f"Median home price:${fmt(housing.median_home_price)} "
            f"({fmt(housing.home_price_growth_yoy_pct, '.1f')}% YoY)",
            f"Metro median rent:${fmt(housing.median_rent_monthly)}/mo "
            f"({fmt(housing.rent_growth_yoy_pct, '.1f')}% YoY)",
            f"Rental vacancy:   {fmt(housing.rental_vacancy_rate, '.1f')}%",
            f"Property tax rate:{fmt(col.property_tax_rate_effective, '.2f')}%",
            f"RPP:              {fmt(col.regional_price_parity, '.1f')} (100 = US avg)",
        ]

        if climate:
            lines += ["", "=== CLIMATE RISK ===",
                      f"Flood risk: {climate.flood_risk_overall or 'n/a'}"]
            if climate.flood:
                lines.append(f"FEMA zone: {climate.flood.fema_flood_zone or 'n/a'} "
                             f"({'SFHA — flood insurance required' if climate.flood.is_sfha else 'no NFIP requirement'})")
            lines += [
                f"Wildfire: {climate.wildfire_risk_label or 'n/a'}",
                f"Hurricane: {climate.hurricane_risk_label or 'n/a'}",
                climate.summary or "",
            ]

        return "\n".join(lines)

    # ── Rule-based fallback ────────────────────────────────────────────────────

    def _fallback(
        self,
        uw: RentalUnderwritingSnapshot,
        reg: RegulatoryRiskSnapshot,
        climate: Optional[ClimateRiskSnapshot],
    ) -> tuple:
        """Rule-based verdict when LLM fails."""
        score = 0

        # Cash flow
        cf = uw.annual_cash_flow
        if cf is not None:
            if cf >= 2400:   score += 3
            elif cf >= 0:    score += 1
            else:            score -= 2

        # Cap rate
        cr = uw.cap_rate_pct
        if cr is not None:
            if cr >= 7:  score += 2
            elif cr >= 5: score += 1
            elif cr < 3:  score -= 2

        # DSCR
        if uw.dscr is not None:
            if uw.dscr >= 1.25:  score += 2
            elif uw.dscr >= 1.0: score += 1
            elif uw.dscr < 0.9:  score -= 2

        # Regulatory
        if reg.overall_regulatory_risk == "very_high":  score -= 3
        elif reg.overall_regulatory_risk == "high":     score -= 1
        elif reg.overall_regulatory_risk == "low":      score += 1

        # Climate
        if climate and climate.flood_risk_overall in ("high", "very_high"):
            score -= 1

        if score >= 6:
            verdict = "highly_viable"
        elif score >= 3:
            verdict = "viable"
        elif score >= 0:
            verdict = "marginal"
        else:
            verdict = "not_viable"

        summary = (
            f"Rental feasibility: {verdict.replace('_', ' ')}. "
            f"Cap rate: {uw.cap_rate_pct:.1f}% | "
            f"Cash flow: ${uw.monthly_cash_flow:+.0f}/mo | "
            f"DSCR: {uw.dscr:.2f}. "
            f"Regulatory risk: {reg.overall_regulatory_risk or 'unknown'}."
            if uw.cap_rate_pct and uw.monthly_cash_flow and uw.dscr
            else "Insufficient data for full analysis."
        )

        pros  = [n for n in [
            f"Cap rate {uw.cap_rate_pct:.1f}%" if uw.cap_rate_pct and uw.cap_rate_pct >= 5 else None,
            f"Positive cash flow ${uw.annual_cash_flow:+.0f}/yr" if cf and cf > 0 else None,
            f"DSCR {uw.dscr:.2f} — lender-bankable" if uw.dscr and uw.dscr >= 1.25 else None,
        ] if n]

        cons  = [n for n in [
            f"Negative cash flow ${cf:+.0f}/yr" if cf is not None and cf < 0 else None,
            f"Cap rate {uw.cap_rate_pct:.1f}% below 5%" if uw.cap_rate_pct and uw.cap_rate_pct < 5 else None,
            f"DSCR {uw.dscr:.2f} — below lender threshold" if uw.dscr and uw.dscr < 1.25 else None,
            f"Regulatory risk: {reg.overall_regulatory_risk}" if reg.overall_regulatory_risk in ("high", "very_high") else None,
        ] if n]

        actions = [
            "Get full property inspection (roof, HVAC, electrical, plumbing, foundation).",
            "Obtain landlord insurance quotes (including flood if SFHA zone).",
            "Call local property manager to verify achievable rent range.",
            "Verify actual property tax bill with county assessor.",
            "Run title search for liens and encumbrances.",
            "Check zoning for permitted uses and planned developments nearby.",
            "Review HOA docs if applicable (rules, reserves, upcoming assessments).",
        ]

        return verdict, summary, pros, cons, actions
