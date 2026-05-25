"""
RealEstateSynthesizerAgent — Node 5 of the real estate research pipeline.

Combines all upstream snapshots (migration, labor, housing, cost-of-living,
demand factors, climate risk, document insights) into a final RealEstateBrief.

Applies Pareto-style reasoning: identifies the 3–5 dominant push/pull factors,
explicitly surfaces city-vs-state divergence, flags data gaps.
"""

import json
import logging
from datetime import date
from typing import Optional

from agents.api_utils import LLMClient
from schemas.realestate import (
    ClimateRiskSnapshot,
    CostOfLivingSnapshot,
    DemandFactorsSnapshot,
    DocumentInsight,
    GeoResolution,
    HousingMarketSnapshot,
    LaborMarketSnapshot,
    MigrationSnapshot,
    RealEstateBrief,
)

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a senior real estate market analyst and migration economist.

You combine labor market data, housing market signals, migration flows, cost-of-living
metrics, climate risk, and any property-specific documents to produce a concise, actionable
real estate demand brief.

Principles:
1. PARETO FOCUS: Identify the 3–5 dominant factors (out of all available signals)
   that drive 80% of the demand verdict. Label these clearly.
2. DIVERGENCE: If city-level and state-level migration signals disagree, call it out
   explicitly — do not paper over it.
3. DATA GAPS: If a signal is missing, name it in data_gaps rather than pretending
   it does not matter.
4. QUANTIFY: Every claim must reference a specific number from the data.
   "Unemployment 3.4%" not "low unemployment". "Flood zone AE" not "flood risk present".
5. NO FILLER: No "exciting opportunity", "great investment", or vague adjectives.
   Verdict language: strong_inflow / moderate_inflow / neutral / moderate_outflow / strong_outflow.

Return ONLY valid JSON — no markdown fences, no prose outside the JSON."""

BRIEF_SCHEMA = """{
  "demand_verdict": "<strong_inflow|moderate_inflow|neutral|moderate_outflow|strong_outflow>",
  "investment_signal": "<Strong Buy|Buy|Hold|Sell|Strong Sell>",
  "confidence": <0.0–1.0>,
  "migration_divergence": "<null or 1-2 sentence description of city-vs-state disagreement>",
  "summary": "<3–4 sentences: verdict + top driver + key risk + confidence note>",
  "dominant_pull_factors": [
    "<specific quantified factor driving IN-migration/demand — e.g. 'Employment growth 3.8% YoY vs national 1.9%'>",
    ...
  ],
  "dominant_push_factors": [
    "<specific quantified factor driving OUT-migration/risk — e.g. 'Median home price $685k; price/income ratio 9.2x'>",
    ...
  ],
  "key_risks": [
    "<risk with specific number or event>",
    ...
  ],
  "upcoming_catalysts": [
    "<event or trend that could shift demand in next 12–24 months>",
    ...
  ],
  "data_gaps": [
    "<factor that was not available — e.g. 'USPS COA ZIP-level flows not fetched'>",
    ...
  ]
}"""


class RealEstateSynthesizerAgent:
    def __init__(self, llm: LLMClient, verbose: bool = True):
        self.llm     = llm
        self.verbose = verbose

    def synthesize(
        self,
        geo: GeoResolution,
        city_migration: MigrationSnapshot,
        state_migration: MigrationSnapshot,
        labor: LaborMarketSnapshot,
        housing: HousingMarketSnapshot,
        col: CostOfLivingSnapshot,
        demand: DemandFactorsSnapshot,
        climate: Optional[ClimateRiskSnapshot],
        doc_insights: list[DocumentInsight],
        depth: str = "full",
    ) -> RealEstateBrief:

        # ── Build the data digest for the LLM ────────────────────────────────
        digest = self._build_digest(
            geo, city_migration, state_migration,
            labor, housing, col, demand, climate, doc_insights
        )

        prompt = f"""Location: {geo.input_city}, {geo.input_state}
{f'Address: {geo.input_address}' if geo.input_address else ''}

=== DATA DIGEST ===
{digest}

=== OUTPUT SCHEMA ===
{BRIEF_SCHEMA}

Analyse the data above and return a complete RealEstateBrief JSON.
Pull-factors = reasons people are moving IN or demand is rising.
Push-factors = reasons people are leaving or demand is falling.
Limit pull_factors and push_factors to 3–5 items each — Pareto focus.
"""

        try:
            raw = self.llm.create(
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=2000,
            )
            data = json.loads(raw.strip())
        except (json.JSONDecodeError, Exception) as e:
            logger.warning(f"RealEstateSynthesizer LLM parse failed: {e}")
            data = self._fallback_verdict(city_migration, state_migration, housing, climate)

        return RealEstateBrief(
            address       = geo.input_address or "",
            city          = geo.input_city,
            state         = geo.input_state,
            zip_code      = geo.input_zip,
            geo           = geo,
            as_of_date    = date.today().isoformat(),

            demand_verdict    = data.get("demand_verdict", "neutral"),
            investment_signal = data.get("investment_signal", "Hold"),
            confidence        = float(data.get("confidence", 0.5)),
            migration_divergence = data.get("migration_divergence") or None,

            city_migration  = city_migration,
            state_migration = state_migration,

            labor_market    = labor,
            housing_market  = housing,
            cost_of_living  = col,
            demand_factors  = demand,
            climate_risk    = climate,

            document_insights = doc_insights,

            summary               = data.get("summary", ""),
            dominant_pull_factors = data.get("dominant_pull_factors", []),
            dominant_push_factors = data.get("dominant_push_factors", []),
            key_risks             = data.get("key_risks", []),
            upcoming_catalysts    = data.get("upcoming_catalysts", []),
            data_gaps             = data.get("data_gaps", []),

            sources = self._collect_sources(housing, city_migration, state_migration),
        )

    # ── Data digest builder ───────────────────────────────────────────────────

    def _build_digest(
        self,
        geo: GeoResolution,
        city_mig: MigrationSnapshot,
        state_mig: MigrationSnapshot,
        labor: LaborMarketSnapshot,
        housing: HousingMarketSnapshot,
        col: CostOfLivingSnapshot,
        demand: DemandFactorsSnapshot,
        climate: Optional[ClimateRiskSnapshot],
        docs: list[DocumentInsight],
    ) -> str:
        lines: list[str] = []

        # Migration
        lines.append("--- MIGRATION ---")
        lines.append(f"City ({geo.input_city}): {city_mig.net_direction} "
                     f"(confidence {city_mig.confidence:.0%})")
        lines.append(city_mig.summary)
        lines.append(f"State ({geo.input_state}): {state_mig.net_direction} "
                     f"(confidence {state_mig.confidence:.0%})")
        lines.append(state_mig.summary)
        if city_mig.net_direction != state_mig.net_direction:
            lines.append(f"⚠ DIVERGENCE: city={city_mig.net_direction}, "
                         f"state={state_mig.net_direction}")
        if city_mig.uhaul_rank:
            lines.append(f"U-Haul state rank: #{city_mig.uhaul_rank}/50 "
                         f"(inbound share {city_mig.uhaul_inbound_share:.2%})")
        if city_mig.population_growth_pct_yoy is not None:
            lines.append(f"Population growth: {city_mig.population_growth_pct_yoy:.2%}/yr")
        if city_mig.irs_net_exemptions is not None:
            lines.append(f"IRS net exemptions: {city_mig.irs_net_exemptions:+,}")

        # Labor market
        lines.append("\n--- LABOR MARKET ---")
        lines.append(labor.summary)
        if labor.unemployment_rate is not None:
            lines.append(f"Unemployment: {labor.unemployment_rate:.1f}% "
                         f"({labor.unemployment_trend or 'n/a'})")
        if labor.employment_growth_pct_yoy is not None:
            lines.append(f"Employment growth YoY: {labor.employment_growth_pct_yoy:+.2%}")
        if labor.avg_weekly_wage:
            lines.append(f"Avg weekly wage: ${labor.avg_weekly_wage:,.0f}")
        if labor.real_wage:
            lines.append(f"Real wage index: {labor.real_wage:.1f}")
        if labor.top_industries:
            lines.append(f"Top industries: {', '.join(labor.top_industries)}")

        # Housing
        lines.append("\n--- HOUSING MARKET ---")
        lines.append(housing.summary)
        if housing.median_home_price:
            lines.append(f"Median home price: ${housing.median_home_price:,.0f} "
                         f"({housing.home_price_growth_yoy_pct:+.1%} YoY)"
                         if housing.home_price_growth_yoy_pct is not None
                         else f"Median home price: ${housing.median_home_price:,.0f}")
        if housing.median_rent_monthly:
            lines.append(f"Median rent: ${housing.median_rent_monthly:,.0f}/mo "
                         f"({housing.rent_growth_yoy_pct:+.1%} YoY)"
                         if housing.rent_growth_yoy_pct is not None
                         else f"Median rent: ${housing.median_rent_monthly:,.0f}/mo")
        if housing.price_to_income_ratio:
            lines.append(f"Price/income: {housing.price_to_income_ratio:.1f}x")
        if housing.days_on_market_median:
            lines.append(f"Days on market: {housing.days_on_market_median:.0f}")
        if housing.months_supply_inventory:
            lines.append(f"Months supply: {housing.months_supply_inventory:.1f}")
        if housing.building_permits_yoy_pct is not None:
            lines.append(f"Permits YoY: {housing.building_permits_yoy_pct:+.1%}")
        if housing.supply_elasticity:
            lines.append(f"Supply elasticity: {housing.supply_elasticity}")

        # Cost of living
        lines.append("\n--- COST OF LIVING ---")
        lines.append(col.summary)
        if col.regional_price_parity:
            lines.append(f"Regional Price Parity: {col.regional_price_parity:.1f} (100=national avg)")
        if col.state_income_tax_top_rate is not None:
            lines.append(f"State income tax (top rate): {col.state_income_tax_top_rate:.1%}")
        if col.property_tax_rate_effective is not None:
            lines.append(f"Effective property tax: {col.property_tax_rate_effective:.1%}")
        if col.overall_tax_burden_rank:
            lines.append(f"Overall tax burden rank: #{col.overall_tax_burden_rank}/50 (1=lowest)")

        # Demand factors
        lines.append("\n--- DEMAND FACTORS ---")
        if demand.violent_crime_per_100k:
            lines.append(f"Violent crime: {demand.violent_crime_per_100k:.0f}/100k "
                         f"({demand.crime_trend or ''})")
        if demand.air_quality_index_median:
            lines.append(f"AQI median: {demand.air_quality_index_median:.0f}")
        if demand.pm25_annual_avg:
            lines.append(f"PM2.5: {demand.pm25_annual_avg:.1f} µg/m³")
        if demand.walkability_score:
            lines.append(f"Walk Score: {demand.walkability_score:.0f}/100")
        if demand.avg_jan_temp_f:
            lines.append(f"Avg Jan temp: {demand.avg_jan_temp_f:.0f}°F "
                         f"| Jul: {demand.avg_july_temp_f:.0f}°F"
                         if demand.avg_july_temp_f else f"Avg Jan temp: {demand.avg_jan_temp_f:.0f}°F")
        if demand.share_college_educated:
            lines.append(f"College-educated share: {demand.share_college_educated:.1%}")
        if demand.avg_commute_time_minutes:
            lines.append(f"Avg commute: {demand.avg_commute_time_minutes:.1f} min")

        # Climate risk
        if climate:
            lines.append("\n--- CLIMATE & FLOOD RISK ---")
            lines.append(climate.summary)
            if climate.flood and climate.flood.fema_flood_zone:
                lines.append(f"FEMA flood zone: {climate.flood.fema_flood_zone} — "
                             f"{climate.flood.fema_zone_description or ''}")
            if climate.flood and climate.flood.first_street_flood_factor:
                lines.append(f"First Street Flood Factor: {climate.flood.first_street_flood_factor}/10")
            if climate.flood_risk_overall:
                lines.append(f"Overall flood risk: {climate.flood_risk_overall}")
            if climate.wildfire_risk_label:
                lines.append(f"Wildfire risk: {climate.wildfire_risk_label}")
            if climate.hurricane_risk_label:
                lines.append(f"Hurricane risk: {climate.hurricane_risk_label}")
            if climate.fema_total_disaster_declarations_10yr:
                lines.append(f"FEMA disaster declarations (10yr): "
                             f"{climate.fema_total_disaster_declarations_10yr}")

        # Document insights
        if docs:
            lines.append("\n--- DOCUMENT INSIGHTS ---")
            for d in docs[:3]:
                lines.append(f"[{d.source_file}]")
                for fact in d.key_facts[:3]:
                    lines.append(f"  • {fact}")

        return "\n".join(lines)

    def _fallback_verdict(
        self,
        city_mig: MigrationSnapshot,
        state_mig: MigrationSnapshot,
        housing: HousingMarketSnapshot,
        climate: Optional[ClimateRiskSnapshot],
    ) -> dict:
        """Rule-based fallback when LLM parse fails."""
        inflow_votes  = sum(1 for s in [city_mig, state_mig] if s.net_direction == "net_inflow")
        outflow_votes = sum(1 for s in [city_mig, state_mig] if s.net_direction == "net_outflow")

        if inflow_votes > outflow_votes:
            verdict = "moderate_inflow"
            signal  = "Buy"
        elif outflow_votes > inflow_votes:
            verdict = "moderate_outflow"
            signal  = "Sell"
        else:
            verdict = "neutral"
            signal  = "Hold"

        return {
            "demand_verdict":         verdict,
            "investment_signal":      signal,
            "confidence":             0.4,
            "migration_divergence":   None,
            "summary":                f"Rule-based verdict (LLM parse failed). "
                                      f"City migration: {city_mig.net_direction}. "
                                      f"State migration: {state_mig.net_direction}.",
            "dominant_pull_factors":  [],
            "dominant_push_factors":  [],
            "key_risks":              [],
            "upcoming_catalysts":     [],
            "data_gaps":              ["LLM synthesis failed — fallback used"],
        }

    def _collect_sources(
        self,
        housing: HousingMarketSnapshot,
        city_mig: MigrationSnapshot,
        state_mig: MigrationSnapshot,
    ) -> list[str]:
        sources = set()
        sources.update(housing.data_sources_used)
        for snap in [city_mig, state_mig]:
            for sig in snap.signals:
                sources.add(sig.source)
        return sorted(sources)
