"""
Pydantic schemas for the Real Estate Research pipeline.

Geographic scoping:
  - All migration, economic, and housing snapshots are computed at BOTH
    city/metro level and state level.
  - Climate risk is computed at property level (address + geocoding) and
    county/metro level.

Tier notation in comments:
  T1 = Tier 1 (core — every run)
  T2 = Tier 2 (depth=full)
  T3 = Tier 3 (opportunistic / when data available)
"""

from typing import Literal, Optional
from pydantic import BaseModel, Field


# ── Geographic resolution ─────────────────────────────────────────────────────

class GeoResolution(BaseModel):
    """Resolved geographic identifiers for a city/address."""
    input_city: str
    input_state: str
    input_zip: Optional[str] = None
    input_address: Optional[str] = None

    # Resolved
    state_fips: Optional[str] = None          # 2-digit FIPS e.g. "48"
    county_fips: Optional[str] = None         # 5-digit FIPS e.g. "48453"
    county_name: Optional[str] = None         # e.g. "Travis County"
    cbsa_code: Optional[str] = None           # Census CBSA code e.g. "12420"
    cbsa_name: Optional[str] = None           # e.g. "Austin-Round Rock, TX"
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    resolution_method: str = "unknown"        # "geocoder", "lookup_table", "manual"


# ── Migration snapshots ────────────────────────────────────────────────────────

class MigrationSignal(BaseModel):
    """A single data point measuring migration direction/magnitude."""
    source: str                                      # "IRS_SOI", "USPS_COA", "UHaul", "Census_ACS", "FRED_pop"
    level: Literal["city", "state"]
    direction: Literal["net_inflow", "net_outflow", "neutral", "unknown"]
    magnitude: Optional[Literal["strong", "moderate", "weak"]] = None
    value: Optional[float] = None                    # raw net migration count or rate
    period: Optional[str] = None                     # e.g. "2022–2023"
    notes: str = ""


class MigrationSnapshot(BaseModel):
    """
    Aggregated migration verdict for a city or state.
    T1 features: net_direction, confidence, irs_net_exemptions, uhaul_rank,
                 population_growth_pct_yoy, signals
    """
    location: str                                    # e.g. "Austin, TX" or "Texas (state)"
    level: Literal["city", "state"]

    # Verdict
    net_direction: Literal["net_inflow", "net_outflow", "neutral", "mixed"]
    confidence: float = Field(ge=0.0, le=1.0)       # lower when few sources available

    # T1 — Direct migration signals
    signals: list[MigrationSignal] = Field(default_factory=list)
    irs_net_exemptions: Optional[int] = None         # IRS SOI net tax filers (county-level)
    irs_net_agi_thousands: Optional[float] = None    # Net AGI of movers ($k) — income quality signal
    uhaul_rank: Optional[int] = None                 # Growth rank; lower = more inbound
    uhaul_inbound_share: Optional[float] = None      # Fraction of one-way rentals that are inbound
    population_growth_pct_yoy: Optional[float] = None  # Census PEP annual growth rate

    # T2 — Additional signals
    usps_net_coa: Optional[int] = None               # USPS COA net (positive = net inflow)
    school_enrollment_change_pct: Optional[float] = None  # YoY K-12 enrollment change

    summary: str = ""                                # 2–3 sentences on verdict + caveats


# ── Labor market ──────────────────────────────────────────────────────────────

class IndustryShare(BaseModel):
    naics_name: str                                  # e.g. "Professional & Business Services"
    employment_share_pct: float
    yoy_growth_pct: Optional[float] = None


class LaborMarketSnapshot(BaseModel):
    """
    T1: unemployment_rate, employment_growth_pct_yoy, avg_weekly_wage, real_wage
    T2: industry mix, jolts_openings_rate, prime_age_epop
    """
    # T1
    unemployment_rate: Optional[float] = None
    unemployment_trend: Optional[Literal["rising", "falling", "stable"]] = None
    unemployment_rate_change_yoy: Optional[float] = None
    employment_growth_pct_yoy: Optional[float] = None
    avg_weekly_wage: Optional[float] = None
    real_wage: Optional[float] = None               # nominal wage / regional_price_parity * 100

    # T2
    industry_mix: list[IndustryShare] = Field(default_factory=list)
    top_industries: list[str] = Field(default_factory=list)   # top 3 by employment share
    major_employers: list[str] = Field(default_factory=list)  # notable anchor employers
    jolts_openings_rate: Optional[float] = None     # job openings as % of employment
    prime_age_epop: Optional[float] = None          # employment-to-population ratio, ages 25–54

    # Data coverage
    data_as_of: Optional[str] = None
    summary: str = ""


# ── Housing market ────────────────────────────────────────────────────────────

class HousingMarketSnapshot(BaseModel):
    """
    T1: median_home_price, home_price_growth_yoy_pct, median_rent_monthly,
        rent_growth_yoy_pct, price_to_income_ratio, rent_to_income_ratio
    T2: vacancy rates, permits, days on market, inventory
    """
    # T1
    median_home_price: Optional[float] = None
    home_price_growth_yoy_pct: Optional[float] = None
    median_rent_monthly: Optional[float] = None
    rent_growth_yoy_pct: Optional[float] = None
    price_to_income_ratio: Optional[float] = None
    rent_to_income_ratio: Optional[float] = None

    # T2
    rental_vacancy_rate: Optional[float] = None
    homeowner_vacancy_rate: Optional[float] = None
    building_permits_per_capita: Optional[float] = None
    building_permits_yoy_pct: Optional[float] = None
    days_on_market_median: Optional[float] = None
    active_listings_trend: Optional[Literal["rising", "falling", "stable"]] = None
    months_supply_inventory: Optional[float] = None
    list_to_sale_ratio: Optional[float] = None
    supply_elasticity: Optional[Literal["constrained", "moderate", "elastic"]] = None

    data_sources_used: list[str] = Field(default_factory=list)
    data_as_of: Optional[str] = None
    summary: str = ""


# ── Cost of living ─────────────────────────────────────────────────────────────

class CostOfLivingSnapshot(BaseModel):
    """
    T1: regional_price_parity, state_income_tax_top_rate
    T1/T2: sales_tax_rate, property_tax_rate_effective
    """
    regional_price_parity: Optional[float] = None   # BEA RPP; 100 = national avg
    state_income_tax_top_rate: Optional[float] = None
    state_income_tax_effective: Optional[float] = None  # for median household
    state_sales_tax_rate: Optional[float] = None
    property_tax_rate_effective: Optional[float] = None  # % of home value
    overall_tax_burden_rank: Optional[int] = None   # Tax Foundation rank (1 = lowest burden)
    overall_assessment: Optional[Literal["low", "below_avg", "avg", "above_avg", "high"]] = None
    summary: str = ""


# ── Demand / quality-of-life factors ─────────────────────────────────────────

class DemandFactorsSnapshot(BaseModel):
    """
    T2: crime, air quality, walkability, broadband, demographics, commute
    """
    # Safety (T2)
    violent_crime_per_100k: Optional[float] = None
    property_crime_per_100k: Optional[float] = None
    crime_trend: Optional[Literal["improving", "stable", "worsening"]] = None

    # Quality of life (T2)
    air_quality_index_median: Optional[float] = None
    pm25_annual_avg: Optional[float] = None
    walkability_score: Optional[float] = None        # Walk Score 0–100
    transit_score: Optional[float] = None
    broadband_coverage_pct: Optional[float] = None

    # Climate basics (T1 — Jan temp is strong predictor)
    avg_jan_temp_f: Optional[float] = None
    avg_july_temp_f: Optional[float] = None
    annual_precipitation_inches: Optional[float] = None

    # Demographics (T2)
    population_total: Optional[int] = None
    share_age_20_34: Optional[float] = None          # % of population
    share_age_65_plus: Optional[float] = None
    share_college_educated: Optional[float] = None
    median_household_income: Optional[float] = None

    # Infrastructure (T2)
    avg_commute_time_minutes: Optional[float] = None
    has_international_airport: Optional[bool] = None
    university_count: Optional[int] = None

    # Political (T2)
    governor_party: Optional[Literal["R", "D", "I"]] = None

    summary: str = ""


# ── Climate and flood risk ─────────────────────────────────────────────────────

class FloodRiskDetail(BaseModel):
    """Property-level and county-level flood risk."""
    # FEMA NFHL (property-level)
    fema_flood_zone: Optional[str] = None            # "X", "AE", "A", "VE", "AO", etc.
    fema_zone_description: Optional[str] = None      # plain English
    base_flood_elevation_ft: Optional[float] = None  # BFE in feet above NAVD88
    is_sfha: Optional[bool] = None                   # Special Flood Hazard Area (zone A or V)

    # First Street (property-level)
    first_street_flood_factor: Optional[int] = None  # 1–10; 10 = extreme
    first_street_30yr_risk_pct: Optional[float] = None  # probability of flooding in 30 years

    # County-level historical
    fema_disaster_flood_count_10yr: Optional[int] = None   # flood disaster declarations, last 10yr
    noaa_flood_events_annual_avg: Optional[float] = None   # avg flood storm events/year (county)


class ClimateRiskSnapshot(BaseModel):
    """
    Property-level (when address provided) + county/metro level climate risks.
    Populated by HousingAnalystAgent from FEMA NFHL, OpenFEMA, NOAA CDO,
    FEMA National Risk Index, and First Street Foundation APIs.
    """
    # Flood
    flood: Optional[FloodRiskDetail] = None
    flood_risk_overall: Optional[Literal["minimal", "low", "moderate", "high", "very_high"]] = None

    # Wildfire
    wildfire_risk_score: Optional[float] = None      # FEMA NRI normalized 0–100
    wildfire_risk_label: Optional[Literal["minimal", "low", "moderate", "high", "very_high"]] = None

    # Hurricane / wind
    hurricane_risk_score: Optional[float] = None     # FEMA NRI normalized 0–100
    hurricane_risk_label: Optional[Literal["minimal", "low", "moderate", "high", "very_high"]] = None

    # General extreme weather (county)
    fema_total_disaster_declarations_10yr: Optional[int] = None
    noaa_storm_events_annual_avg: Optional[float] = None
    noaa_storm_damage_annual_avg_usd: Optional[float] = None

    # Climate normals
    extreme_heat_days_per_year: Optional[float] = None  # days > 95°F

    summary: str = ""


# ── Rental analysis schemas ───────────────────────────────────────────────────

class RentalUnderwritingSnapshot(BaseModel):
    """
    Full financial model for a rental property.
    Computed by RentalUnderwriterAgent — no LLM, pure arithmetic.
    """
    # Rent estimate
    estimated_monthly_rent: Optional[float] = None
    rent_low: Optional[float] = None
    rent_high: Optional[float] = None
    rent_estimate_source: str = ""          # "RentCast", "HUD_FMR", "Zillow_ZORI_metro"
    rent_estimate_confidence: Optional[Literal["high", "medium", "low"]] = None

    # Property value basis
    purchase_price: Optional[float] = None
    estimated_market_value: Optional[float] = None   # from Zillow ZHVI if price not given

    # T1 income ratios
    gross_rent_yield_pct: Optional[float] = None     # annual rent / price × 100
    gross_rent_multiplier: Optional[float] = None    # price / annual rent
    price_to_rent_ratio: Optional[float] = None      # price / annual rent (Shiller)

    # Annual operating expenses
    est_annual_property_tax: Optional[float] = None
    est_annual_insurance_base: Optional[float] = None   # landlord policy
    nfip_required: bool = False                          # True if FEMA zone A or V
    est_nfip_annual_premium: Optional[float] = None
    est_annual_insurance_total: Optional[float] = None
    vacancy_allowance_pct: float = 0.05
    est_annual_vacancy_loss: Optional[float] = None
    mgmt_fee_pct: float = 0.09                           # 9% of collected rent
    est_annual_mgmt_fee: Optional[float] = None
    maintenance_reserve_pct: float = 0.01                # 1% of property value
    est_annual_maintenance: Optional[float] = None
    est_annual_capex_reserve: Optional[float] = None     # additional CapEx reserve
    est_annual_total_expenses: Optional[float] = None

    # NOI and cap rate
    est_annual_gross_rent: Optional[float] = None
    est_annual_noi: Optional[float] = None
    cap_rate_pct: Optional[float] = None

    # Financing (with assumptions: 20% down, 30yr fixed)
    down_payment_pct: float = 0.20
    interest_rate_pct: float = 0.07
    loan_term_years: int = 30
    down_payment_amount: Optional[float] = None
    loan_amount: Optional[float] = None
    monthly_mortgage_payment: Optional[float] = None
    annual_debt_service: Optional[float] = None

    # Cash flow
    annual_cash_flow: Optional[float] = None
    monthly_cash_flow: Optional[float] = None
    cash_on_cash_return_pct: Optional[float] = None
    dscr: Optional[float] = None                         # NOI / debt service; ≥ 1.25 = bankable
    break_even_occupancy_pct: Optional[float] = None     # occupancy needed to cover all costs

    # Verdict
    cash_flow_verdict: Optional[Literal["positive", "marginal", "negative"]] = None
    underwriting_notes: list[str] = Field(default_factory=list)   # warnings & flags


class RegulatoryRiskSnapshot(BaseModel):
    """
    Landlord law, rent control, STR rules, and insurance market stress.
    Sourced from static 50-state/major-city lookup tables — no external API.
    """
    # Eviction process
    state_eviction_timeline_days: Optional[int] = None   # median filing → lockout
    eviction_process_notes: str = ""
    eviction_friendliness: Optional[Literal["landlord_friendly", "neutral", "tenant_friendly"]] = None

    # Rent control
    rent_control_exposure: Optional[bool] = None
    rent_control_type: Optional[str] = None              # "stabilisation", "control", "none"
    rent_control_exemption: Optional[str] = None         # e.g. "exempt if built after 1979"
    rent_control_details: str = ""

    # Short-term rentals
    str_generally_permitted: Optional[bool] = None
    str_permit_required: Optional[bool] = None
    str_primary_residence_only: Optional[bool] = None
    str_notes: str = ""

    # Insurance market
    insurance_market_stress: Optional[Literal["normal", "elevated", "severe"]] = None
    insurance_stress_notes: str = ""

    # Other
    landlord_license_required: Optional[bool] = None
    just_cause_eviction_required: Optional[bool] = None  # limits grounds for non-renewal

    overall_regulatory_risk: Optional[Literal["low", "moderate", "high", "very_high"]] = None
    summary: str = ""


class NeighborhoodSnapshot(BaseModel):
    """
    Hyperlocal signals at ZIP, Census tract, and address level.
    Sourced from ACS, HUD USPS vacancy, GreatSchools API, Walk Score.
    """
    # Schools (GreatSchools or NCES)
    school_district_name: Optional[str] = None
    school_district_rating: Optional[float] = None       # 1–10
    nearby_elementary_rating: Optional[float] = None
    school_data_source: str = ""

    # Rental market (ZIP level)
    zip_rental_vacancy_rate: Optional[float] = None
    zip_active_rental_listings: Optional[int] = None
    estimated_days_to_lease: Optional[int] = None
    rental_demand_signal: Optional[Literal["strong", "moderate", "soft"]] = None

    # Census tract demographics
    tract_median_income: Optional[float] = None
    tract_income_growth_5yr_pct: Optional[float] = None
    tract_owner_occ_pct: Optional[float] = None          # < 40% → strong rental market
    tract_college_edu_pct: Optional[float] = None
    tract_population_density: Optional[float] = None     # per sq mile

    # Walkability (Walk Score — already fetched by HousingAnalystAgent, reused here)
    walkability_score: Optional[float] = None
    transit_score: Optional[float] = None

    # Trajectory
    permit_activity_trend: Optional[Literal["increasing", "stable", "decreasing"]] = None
    neighborhood_trajectory: Optional[Literal["appreciating", "stable", "declining"]] = None

    summary: str = ""


class RentalAnalysis(BaseModel):
    """
    Rental feasibility analysis — present when property details are provided.
    (bedrooms, bathrooms, and/or purchase_price supplied in input)
    Groups all rental-specific outputs together on RealEstateBrief.
    """
    # Input echo
    bedrooms: int = 3
    bathrooms: float = 2.0
    sqft: Optional[int] = None
    property_type: str = "single_family"
    year_built: Optional[int] = None

    # The three analysis nodes
    underwriting: RentalUnderwritingSnapshot
    regulatory: RegulatoryRiskSnapshot
    neighborhood: NeighborhoodSnapshot

    # LLM synthesis
    feasibility_verdict: Literal["highly_viable", "viable", "marginal", "not_viable"]
    rental_summary: str = ""
    pros: list[str] = Field(default_factory=list)        # quantified investment positives
    cons: list[str] = Field(default_factory=list)        # quantified risks/negatives
    recommended_actions: list[str] = Field(default_factory=list)   # due-diligence checklist


# ── Document intelligence — type-specific extract schemas ─────────────────────

DocumentType = Literal[
    "appraisal", "inspection", "hoa", "tax_record", "lease_rent_roll",
    "flood_cert", "listing_mls", "cma_comps", "environmental",
    "zoning_permit", "other",
]


class AppraisalExtract(BaseModel):
    """Facts extracted from a formal property appraisal report."""
    appraised_value: Optional[float] = None               # final appraised value in USD
    appraisal_date: Optional[str] = None                  # e.g. "2024-11-15"
    appraiser_name: Optional[str] = None
    effective_age_years: Optional[int] = None             # appraisers' "effective age"
    condition_rating: Optional[str] = None                # e.g. "C3 — Average"
    quality_rating: Optional[str] = None                  # e.g. "Q4 — Good"
    gross_living_area_sqft: Optional[int] = None
    neighborhood_trend: Optional[str] = None              # "Increasing / Stable / Declining"
    comparable_sales: list[str] = Field(default_factory=list)   # comp addresses + prices
    price_vs_purchase_note: Optional[str] = None          # appraisal vs. contract price


class InspectionExtract(BaseModel):
    """Facts extracted from a home inspection report."""
    inspection_date: Optional[str] = None
    inspector_name: Optional[str] = None
    overall_condition: Optional[str] = None               # "Good", "Fair", "Poor"
    major_defects: list[str] = Field(default_factory=list)      # items needing immediate repair
    safety_issues: list[str] = Field(default_factory=list)      # safety hazards noted
    deferred_maintenance: list[str] = Field(default_factory=list)  # not urgent but noted
    estimated_repair_cost_low: Optional[float] = None     # inspector's cost range, low
    estimated_repair_cost_high: Optional[float] = None    # inspector's cost range, high
    # Key systems
    roof_condition: Optional[str] = None
    roof_age_years: Optional[int] = None
    roof_remaining_life_years: Optional[int] = None
    hvac_condition: Optional[str] = None
    hvac_age_years: Optional[int] = None
    water_heater_age_years: Optional[int] = None
    foundation_condition: Optional[str] = None
    electrical_condition: Optional[str] = None
    plumbing_condition: Optional[str] = None
    mold_moisture_noted: Optional[bool] = None
    pest_damage_noted: Optional[bool] = None


class HOAExtract(BaseModel):
    """Facts extracted from HOA CC&Rs, financial statements, or bylaws."""
    monthly_hoa_fee: Optional[float] = None
    annual_hoa_fee: Optional[float] = None
    special_assessments_pending: list[str] = Field(default_factory=list)   # description + amount
    reserve_fund_pct_funded: Optional[float] = None       # % of recommended reserves held
    reserve_fund_adequate: Optional[bool] = None          # per reserve study
    rental_restrictions: Optional[str] = None             # e.g. "min 12-month lease"
    rental_cap_pct: Optional[float] = None                # % of units allowed to rent (e.g. 20%)
    str_prohibited: Optional[bool] = None                 # short-term rentals banned
    minimum_rental_term_days: Optional[int] = None
    pets_allowed: Optional[bool] = None
    management_company: Optional[str] = None
    litigation_noted: Optional[bool] = None               # active or pending litigation


class TaxRecordExtract(BaseModel):
    """Facts extracted from county tax records or property tax bills."""
    actual_annual_tax: Optional[float] = None             # the real tax bill in USD
    assessed_value: Optional[float] = None
    tax_year: Optional[str] = None
    tax_rate_pct: Optional[float] = None                  # effective rate %
    homestead_exemption_applied: Optional[bool] = None
    homestead_exemption_savings: Optional[float] = None   # amount saved (lost when renting)
    parcel_id: Optional[str] = None
    special_assessments: list[str] = Field(default_factory=list)  # MUD, CDD, etc.


class LeaseExtract(BaseModel):
    """Facts extracted from a lease agreement or rent roll."""
    current_monthly_rent: Optional[float] = None
    gross_annual_rent_roll: Optional[float] = None        # total rent across all units
    unit_count: Optional[int] = None                      # for multi-family
    lease_start_date: Optional[str] = None
    lease_expiration_date: Optional[str] = None
    month_to_month: Optional[bool] = None
    security_deposit: Optional[float] = None
    rent_increase_clause: Optional[str] = None            # e.g. "3% annually"
    late_fee_policy: Optional[str] = None
    pets_allowed_per_lease: Optional[bool] = None
    tenant_pays_utilities: Optional[bool] = None
    occupancy_history_note: Optional[str] = None          # any notes on payment history


class FloodCertExtract(BaseModel):
    """Facts extracted from a FEMA flood determination or elevation certificate."""
    fema_flood_zone: Optional[str] = None                 # "AE", "X", "VE", etc.
    community_panel_number: Optional[str] = None
    base_flood_elevation_ft: Optional[float] = None
    property_elevation_ft: Optional[float] = None         # from elevation certificate
    flood_cert_date: Optional[str] = None
    nfip_required: Optional[bool] = None
    actual_nfip_premium: Optional[float] = None           # actual quoted/paid premium
    flood_insurance_carrier: Optional[str] = None


class ListingExtract(BaseModel):
    """Facts extracted from an MLS listing sheet or listing agreement."""
    list_price: Optional[float] = None
    original_list_price: Optional[float] = None
    price_per_sqft: Optional[float] = None
    days_on_market: Optional[int] = None
    price_reduction_count: Optional[int] = None
    total_price_reduction: Optional[float] = None
    seller_concessions: Optional[float] = None
    listing_date: Optional[str] = None
    listing_agent: Optional[str] = None
    hoa_fee_per_listing: Optional[float] = None           # listed HOA fee
    taxes_per_listing: Optional[float] = None             # listed annual taxes


class CMAExtract(BaseModel):
    """Facts extracted from a Comparative Market Analysis / comp report."""
    subject_value_estimate_low: Optional[float] = None
    subject_value_estimate_high: Optional[float] = None
    median_comp_price: Optional[float] = None
    median_comp_price_per_sqft: Optional[float] = None
    avg_days_on_market: Optional[float] = None
    comparable_count: Optional[int] = None
    market_trend: Optional[str] = None                    # "appreciating", "flat", "declining"
    comps_summary: list[str] = Field(default_factory=list)


class ZoningExtract(BaseModel):
    """Facts extracted from zoning letters, permit records, or municipal reports."""
    zoning_classification: Optional[str] = None           # e.g. "R-1", "MF-2"
    permitted_uses: list[str] = Field(default_factory=list)
    str_permitted_by_zoning: Optional[bool] = None
    accessory_dwelling_permitted: Optional[bool] = None
    open_permits: list[str] = Field(default_factory=list)   # unresolved permits
    violations_noted: list[str] = Field(default_factory=list)
    setback_notes: Optional[str] = None
    lot_coverage_pct: Optional[float] = None


class DocumentInsight(BaseModel):
    """
    Intelligence extracted from a single property-related document.
    Classified into a document type, then type-specific facts are extracted.
    """
    source_file: str
    file_type: Literal["pdf_text", "pdf_ocr", "markdown", "txt", "docx"]

    # Classification
    document_type: str = "other"                           # one of DocumentType literals
    classification_confidence: float = 0.0                 # 0.0–1.0

    # Generic extraction (always populated regardless of type)
    key_facts: list[str] = Field(default_factory=list)
    property_mentions: list[str] = Field(default_factory=list)
    market_mentions: list[str] = Field(default_factory=list)

    # Conflicts detected between document data and other sources/estimates
    conflicts: list[str] = Field(default_factory=list)

    # Type-specific extracts — only the matching type is populated; others are None
    appraisal:   Optional[AppraisalExtract]  = None
    inspection:  Optional[InspectionExtract] = None
    hoa:         Optional[HOAExtract]        = None
    tax_record:  Optional[TaxRecordExtract]  = None
    lease:       Optional[LeaseExtract]      = None
    flood_cert:  Optional[FloodCertExtract]  = None
    listing:     Optional[ListingExtract]    = None
    cma:         Optional[CMAExtract]        = None
    zoning:      Optional[ZoningExtract]     = None


class DocumentFactsBundle(BaseModel):
    """
    Aggregated, de-duplicated facts from all ingested documents.
    The underwriter reads from here to override estimates with real data.
    Fields present here take precedence over formula-based estimates.
    """
    # From appraisal
    appraised_value: Optional[float] = None

    # From tax record
    actual_annual_property_tax: Optional[float] = None
    homestead_exemption_note: Optional[str] = None     # tax will increase when renting

    # From flood cert
    fema_zone_confirmed: Optional[str] = None
    actual_nfip_premium: Optional[float] = None

    # From lease/rent roll
    current_monthly_rent: Optional[float] = None       # in-place rent — most accurate estimate
    lease_expiration_date: Optional[str] = None
    gross_annual_rent_roll: Optional[float] = None

    # From HOA
    monthly_hoa_fee: Optional[float] = None
    hoa_rental_restrictions: Optional[str] = None
    hoa_str_prohibited: Optional[bool] = None
    hoa_minimum_rental_term_days: Optional[int] = None

    # From inspection
    estimated_repair_cost_low: Optional[float] = None
    estimated_repair_cost_high: Optional[float] = None
    major_defects_summary: list[str] = Field(default_factory=list)

    # From listing
    list_price: Optional[float] = None
    days_on_market: Optional[int] = None

    # From CMA
    cma_value_low: Optional[float] = None
    cma_value_high: Optional[float] = None

    # From zoning
    str_permitted_by_zoning: Optional[bool] = None
    open_permits: list[str] = Field(default_factory=list)
    violations: list[str] = Field(default_factory=list)

    # Cross-document conflicts flagged
    conflicts: list[str] = Field(default_factory=list)

    # Which documents contributed to this bundle
    source_documents: list[str] = Field(default_factory=list)


# ── Top-level brief ────────────────────────────────────────────────────────────

class RealEstateBrief(BaseModel):
    """
    Final output of the RealEstatePipeline.
    All migration, economic, and housing snapshots include both city and state level.
    Climate risk is property-level (when address provided) + county/metro.
    """
    # Location
    address: str = ""
    city: str
    state: str
    zip_code: Optional[str] = None
    geo: Optional[GeoResolution] = None
    as_of_date: str

    # Top-line verdict
    demand_verdict: Literal["strong_inflow", "moderate_inflow", "neutral",
                             "moderate_outflow", "strong_outflow"]
    investment_signal: Literal["Strong Buy", "Buy", "Hold", "Sell", "Strong Sell"]
    confidence: float = Field(ge=0.0, le=1.0)

    # Migration — both geographic levels always present
    city_migration: MigrationSnapshot
    state_migration: MigrationSnapshot
    migration_divergence: Optional[str] = None      # set when city vs state disagree

    # Economic fundamentals
    labor_market: LaborMarketSnapshot
    housing_market: HousingMarketSnapshot
    cost_of_living: CostOfLivingSnapshot
    demand_factors: DemandFactorsSnapshot

    # Climate & flood risk
    climate_risk: Optional[ClimateRiskSnapshot] = None

    # Rental feasibility analysis (present when property details are supplied)
    rental_analysis: Optional[RentalAnalysis] = None

    # Document intelligence (empty when documents_dir not provided)
    document_insights: list[DocumentInsight] = Field(default_factory=list)

    # Synthesized analysis
    summary: str
    dominant_pull_factors: list[str] = Field(default_factory=list)  # top 3–5 (Pareto)
    dominant_push_factors: list[str] = Field(default_factory=list)
    key_risks: list[str] = Field(default_factory=list)
    upcoming_catalysts: list[str] = Field(default_factory=list)
    data_gaps: list[str] = Field(default_factory=list)  # factors not sourced

    sources: list[str] = Field(default_factory=list)


# ── Pipeline input ─────────────────────────────────────────────────────────────

class RealEstatePipelineInput(BaseModel):
    city: str
    state: str                                       # 2-letter abbreviation e.g. "TX"
    address: str = ""                                # optional; enables property-level flood lookup
    zip_code: Optional[str] = None
    depth: Literal["quick", "full"] = "full"
    documents_dir: Optional[str] = None             # folder of PDFs/MDs/TXTs to ingest
    export_to_tolaria: bool = False

    # ── Property details — triggers rental feasibility analysis when provided ──
    bedrooms: Optional[int] = None                   # e.g. 3
    bathrooms: Optional[float] = None                # e.g. 2.5
    sqft: Optional[int] = None                       # interior living area
    property_type: str = "single_family"             # single_family | condo | townhouse | multi_family
    year_built: Optional[int] = None                 # affects CapEx reserves and insurance
    purchase_price: Optional[float] = None           # asking/offer price in USD

    # Financing assumptions (defaults: 20% down, 7% rate, 30yr)
    down_payment_pct: float = 0.20
    interest_rate_pct: float = 0.07
    loan_term_years: int = 30

    # RentCast API key — optional; enables property-specific rent estimates
    rentcast_api_key: str = ""
