"""
RentalUnderwriterAgent — pure-math financial model for rental property analysis.

No LLM call — all arithmetic.

Rent estimation priority:
  1. RentCast API (property-specific, most accurate) — requires rentcast_api_key
  2. HUD Fair Market Rents (county-level by bedroom count) — free, no key
  3. Metro median rent from HousingMarketSnapshot (Zillow ZORI) as fallback

Financial model:
  - Gross rent → vacancy loss → effective gross income
  - Operating expenses: property tax, insurance, vacancy, management, maintenance, CapEx
  - NOI = EGI − operating expenses
  - Cap rate = NOI / purchase price
  - Mortgage payment (standard amortization formula)
  - Cash flow = NOI − annual debt service
  - Cash-on-cash = annual cash flow / total cash invested
  - DSCR = NOI / annual debt service
  - Break-even occupancy = (expenses + debt service) / gross rent
"""

import logging
import math
from typing import Optional

from schemas.realestate import (
    GeoResolution, HousingMarketSnapshot, ClimateRiskSnapshot,
    RentalUnderwritingSnapshot, CostOfLivingSnapshot, DocumentFactsBundle,
)

logger = logging.getLogger(__name__)


# ── HUD Fair Market Rents (FY2024, selected metros + national fallback) ────────
# Keyed by state abbreviation → (0BR, 1BR, 2BR, 3BR, 4BR) monthly FMR
# Source: HUD FY2024 FMR  https://www.huduser.gov/portal/datasets/fmr.html
_HUD_STATE_FMR: dict[str, tuple[int, int, int, int, int]] = {
    "AL": (680,  820,  990, 1280, 1410),
    "AK": (980, 1180, 1480, 2060, 2310),
    "AZ": (980, 1100, 1370, 1890, 2210),
    "AR": (620,  730,  910, 1190, 1340),
    "CA": (1510, 1730, 2170, 2980, 3290),
    "CO": (1120, 1270, 1580, 2160, 2480),
    "CT": (1130, 1290, 1620, 2060, 2310),
    "DC": (1760, 1980, 2300, 2940, 3280),
    "DE": (1020, 1160, 1400, 1800, 2030),
    "FL": (1060, 1200, 1480, 1980, 2260),
    "GA": (900,  1030, 1260, 1660, 1910),
    "HI": (1710, 1990, 2470, 3380, 3820),
    "ID": (790,  900, 1110, 1520, 1750),
    "IL": (870,  990, 1230, 1600, 1810),
    "IN": (700,  800,  990, 1300, 1480),
    "IA": (700,  800,  990, 1300, 1480),
    "KS": (700,  800,  980, 1280, 1450),
    "KY": (690,  790,  970, 1270, 1430),
    "LA": (750,  860, 1060, 1390, 1570),
    "ME": (870,  990, 1220, 1590, 1800),
    "MD": (1330, 1510, 1850, 2400, 2690),
    "MA": (1490, 1690, 2080, 2640, 2980),
    "MI": (780,  890, 1090, 1430, 1620),
    "MN": (900, 1030, 1280, 1690, 1920),
    "MS": (590,  680,  840, 1100, 1250),
    "MO": (720,  820, 1010, 1330, 1500),
    "MT": (750,  860, 1060, 1410, 1610),
    "NE": (730,  840, 1040, 1370, 1560),
    "NV": (1020, 1170, 1460, 2010, 2310),
    "NH": (1070, 1220, 1510, 1960, 2200),
    "NJ": (1340, 1530, 1880, 2440, 2740),
    "NM": (800,  910, 1130, 1490, 1710),
    "NY": (1340, 1530, 1870, 2430, 2740),
    "NC": (830,  950, 1170, 1540, 1750),
    "ND": (710,  820, 1010, 1330, 1510),
    "OH": (720,  820, 1010, 1330, 1510),
    "OK": (660,  760,  940, 1240, 1400),
    "OR": (1050, 1200, 1500, 2050, 2360),
    "PA": (870,  990, 1220, 1600, 1810),
    "RI": (1100, 1250, 1560, 1990, 2250),
    "SC": (820,  940, 1150, 1520, 1730),
    "SD": (680,  780,  960, 1270, 1440),
    "TN": (800,  920, 1130, 1490, 1700),
    "TX": (890, 1020, 1260, 1670, 1920),
    "UT": (910, 1040, 1290, 1770, 2050),
    "VT": (950, 1080, 1340, 1730, 1960),
    "VA": (1110, 1270, 1570, 2070, 2340),
    "WA": (1200, 1360, 1690, 2310, 2650),
    "WV": (600,  690,  850, 1110, 1260),
    "WI": (770,  880, 1090, 1430, 1630),
    "WY": (750,  860, 1070, 1420, 1620),
}
_NATIONAL_FMR = (850, 975, 1220, 1600, 1820)   # national fallback


def _hud_fmr(state: str, bedrooms: int) -> Optional[float]:
    """Look up HUD FMR for state + bedroom count (0–4). Returns None if unavailable."""
    row = _HUD_STATE_FMR.get(state.upper(), _NATIONAL_FMR)
    idx = max(0, min(bedrooms, 4))
    return float(row[idx])


def _rentcast_estimate(
    address: str,
    bedrooms: int,
    bathrooms: float,
    sqft: Optional[int],
    property_type: str,
    api_key: str,
) -> Optional[tuple[float, float, float]]:
    """
    Call RentCast /avm/rent/property endpoint.
    Returns (estimate, rentLow, rentHigh) or None on failure.
    """
    if not api_key or not address:
        return None
    try:
        import urllib.parse
        import urllib.request
        import json

        params = {
            "address":      address,
            "bedrooms":     bedrooms,
            "bathrooms":    bathrooms,
            "propertyType": property_type,
        }
        if sqft:
            params["squareFootage"] = sqft

        url = "https://api.rentcast.io/v1/avm/rent/property?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers={"X-Api-Key": api_key, "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        rent      = data.get("rent")
        rent_low  = data.get("rentRangeLow")
        rent_high = data.get("rentRangeHigh")
        if rent:
            return float(rent), float(rent_low or rent * 0.9), float(rent_high or rent * 1.1)
    except Exception as e:
        logger.debug(f"RentCast API failed: {e}")
    return None


def _monthly_payment(principal: float, annual_rate: float, term_years: int) -> float:
    """Standard fixed-rate mortgage payment formula."""
    if annual_rate <= 0:
        return principal / (term_years * 12)
    r = annual_rate / 12.0
    n = term_years * 12
    return principal * r * (1 + r) ** n / ((1 + r) ** n - 1)


class RentalUnderwriterAgent:
    """
    Pure-math financial model. No LLM calls.

    Inputs come from:
      - RealEstatePipelineInput (property specs, purchase_price, financing assumptions)
      - HousingMarketSnapshot (metro median home price and rent as fallback values)
      - CostOfLivingSnapshot (property tax effective rate)
      - ClimateRiskSnapshot (flood zone → NFIP requirement)
    """

    def __init__(
        self,
        rentcast_api_key: str = "",
        verbose: bool = False,
    ):
        self.rentcast_key = rentcast_api_key
        self.verbose = verbose

    def underwrite(
        self,
        # Property specs
        address: str,
        state: str,
        bedrooms: int,
        bathrooms: float,
        sqft: Optional[int],
        property_type: str,
        year_built: Optional[int],
        purchase_price: Optional[float],
        down_payment_pct: float,
        interest_rate_pct: float,
        loan_term_years: int,
        # Context snapshots
        housing: HousingMarketSnapshot,
        col: CostOfLivingSnapshot,
        climate: Optional[ClimateRiskSnapshot],
        # Document-extracted facts (override estimates when present)
        doc_facts: Optional[DocumentFactsBundle] = None,
    ) -> RentalUnderwritingSnapshot:

        snap = RentalUnderwritingSnapshot()
        df = doc_facts  # shorthand

        # ── Determine purchase price basis ─────────────────────────────────────
        price = purchase_price
        # If document has an appraised value and no explicit purchase price, use it
        if not price and df and df.appraised_value:
            price = df.appraised_value
            snap.estimated_market_value = price
            snap.underwriting_notes.append(
                f"No purchase price provided — using appraised value ${price:,.0f} from documents."
            )
        elif not price and housing.median_home_price:
            price = housing.median_home_price
            snap.estimated_market_value = price
        elif price:
            snap.purchase_price = price
            # Use appraised value for market value if available
            if df and df.appraised_value:
                snap.estimated_market_value = df.appraised_value
            elif housing.median_home_price:
                snap.estimated_market_value = housing.median_home_price

        snap.down_payment_pct   = down_payment_pct
        snap.interest_rate_pct  = interest_rate_pct
        snap.loan_term_years    = loan_term_years

        # ── Rent estimate — document lease data is most accurate ──────────────
        # Priority: (1) lease rent roll from docs, (2) RentCast API,
        #           (3) Zillow ZORI metro, (4) HUD FMR
        if df and df.current_monthly_rent:
            snap.estimated_monthly_rent   = df.current_monthly_rent
            snap.rent_low                 = df.current_monthly_rent * 0.95
            snap.rent_high                = df.current_monthly_rent * 1.10
            snap.rent_estimate_source     = "lease_rent_roll_document"
            snap.rent_estimate_confidence = "high"
            snap.underwriting_notes.append(
                f"Rent ${df.current_monthly_rent:,.0f}/mo taken from lease document "
                + (f"(expires {df.lease_expiration_date})" if df.lease_expiration_date else "(in-place).")
            )
        else:
            rent_result = None
            if address and self.rentcast_key:
                rent_result = _rentcast_estimate(
                    address, bedrooms, bathrooms, sqft, property_type, self.rentcast_key
                )

            if rent_result:
                snap.estimated_monthly_rent   = rent_result[0]
                snap.rent_low                 = rent_result[1]
                snap.rent_high                = rent_result[2]
                snap.rent_estimate_source     = "RentCast"
                snap.rent_estimate_confidence = "high"
            elif housing.median_rent_monthly:
                snap.estimated_monthly_rent   = housing.median_rent_monthly
                snap.rent_low                 = housing.median_rent_monthly * 0.88
                snap.rent_high                = housing.median_rent_monthly * 1.12
                snap.rent_estimate_source     = "Zillow_ZORI_metro"
                snap.rent_estimate_confidence = "medium"
            else:
                hud = _hud_fmr(state, bedrooms)
                snap.estimated_monthly_rent   = hud
                snap.rent_low                 = hud * 0.85 if hud else None
                snap.rent_high                = hud * 1.15 if hud else None
                snap.rent_estimate_source     = "HUD_FMR"
                snap.rent_estimate_confidence = "low"

        if self.verbose:
            logger.info(
                f"RentalUnderwriter: rent=${snap.estimated_monthly_rent:,.0f}/mo "
                f"({snap.rent_estimate_source})"
            )

        rent = snap.estimated_monthly_rent
        if not rent or not price:
            snap.underwriting_notes.append(
                "Insufficient data (no rent estimate or price) — financial model incomplete."
            )
            return snap

        # ── Income ratios ──────────────────────────────────────────────────────
        annual_rent = rent * 12
        snap.est_annual_gross_rent     = annual_rent
        snap.gross_rent_yield_pct      = round(annual_rent / price * 100, 2)
        snap.gross_rent_multiplier     = round(price / annual_rent, 1)
        snap.price_to_rent_ratio       = round(price / annual_rent, 1)

        # ── Operating expenses ─────────────────────────────────────────────────

        # Property tax — use actual bill from documents if available
        if df and df.actual_annual_property_tax:
            snap.est_annual_property_tax = df.actual_annual_property_tax
            snap.underwriting_notes.append(
                f"Property tax ${df.actual_annual_property_tax:,.0f}/yr from tax document."
                + (" Note: homestead exemption currently applied — tax may increase when renting."
                   if df.homestead_exemption_note else "")
            )
        else:
            prop_tax_rate = (col.property_tax_rate_effective or 1.1) / 100.0
            snap.est_annual_property_tax = round(price * prop_tax_rate, 0)

        # HOA fee — add to expenses if present in documents
        monthly_hoa = (df.monthly_hoa_fee if df else None) or 0.0
        annual_hoa  = monthly_hoa * 12
        if monthly_hoa > 0:
            snap.underwriting_notes.append(
                f"HOA fee ${monthly_hoa:,.0f}/mo (${annual_hoa:,.0f}/yr) from HOA documents."
            )
            # Check rental restrictions
            if df and df.hoa_str_prohibited:
                snap.underwriting_notes.append(
                    "⚠ HOA documents prohibit short-term rentals (Airbnb/VRBO)."
                )
            if df and df.hoa_rental_restrictions:
                snap.underwriting_notes.append(
                    f"HOA rental restriction: {df.hoa_rental_restrictions}"
                )

        # Insurance
        base_insurance_rate = 0.005
        snap.est_annual_insurance_base = round(price * base_insurance_rate, 0)

        # NFIP (flood insurance) — prefer document data, then FEMA API, then zone estimate
        nfip_required = False
        nfip_premium  = 0.0
        sfha_zones_set = {"A", "AE", "AO", "AH", "AR", "A99", "V", "VE", "VO"}

        # Check flood cert document first
        doc_zone = df.fema_zone_confirmed if df else None
        if doc_zone:
            if any(doc_zone.upper().startswith(z) for z in sfha_zones_set):
                nfip_required = True
                if df and df.actual_nfip_premium:
                    nfip_premium = df.actual_nfip_premium
                    snap.underwriting_notes.append(
                        f"NFIP premium ${nfip_premium:,.0f}/yr from flood certificate document."
                    )
                else:
                    nfip_premium = 1200.0 if doc_zone.upper() in ("AE", "VE") else 900.0
                    snap.underwriting_notes.append(
                        f"FEMA zone {doc_zone} confirmed in documents — NFIP required "
                        f"(est. ${nfip_premium:,.0f}/yr; obtain actual quote)."
                    )
        elif climate and climate.flood:
            zone = (climate.flood.fema_flood_zone or "").upper()
            if zone and any(zone.startswith(z) for z in sfha_zones_set):
                nfip_required = True
                nfip_premium  = 1200.0 if zone in ("AE", "VE") else 900.0
                snap.underwriting_notes.append(
                    f"Property is in FEMA SFHA flood zone {zone} — "
                    f"NFIP flood insurance required (est. ${nfip_premium:,.0f}/yr)."
                )

        snap.nfip_required            = nfip_required
        snap.est_nfip_annual_premium  = nfip_premium if nfip_required else None
        snap.est_annual_insurance_total = round(
            snap.est_annual_insurance_base + (nfip_premium if nfip_required else 0), 0
        )

        # Vacancy
        snap.est_annual_vacancy_loss = round(annual_rent * snap.vacancy_allowance_pct, 0)

        # Management fee
        egi = annual_rent - snap.est_annual_vacancy_loss
        snap.est_annual_mgmt_fee = round(egi * snap.mgmt_fee_pct, 0)

        # Maintenance — adjust upward if inspection found major defects
        maint_rate = snap.maintenance_reserve_pct
        if year_built and year_built < 1980:
            maint_rate = 0.015
            snap.underwriting_notes.append(
                "Year built pre-1980 — maintenance reserve bumped to 1.5% of value."
            )
        if df and df.major_defects_summary:
            maint_rate = max(maint_rate, 0.02)   # bump to 2% when defects noted
            snap.underwriting_notes.append(
                f"Inspection defects noted — maintenance reserve bumped to "
                f"{maint_rate*100:.1f}% of value."
            )
        snap.est_annual_maintenance = round(price * maint_rate, 0)

        # CapEx reserve — bump if inspection flagged aging systems
        capex_rate = 0.01
        if year_built and year_built < 1990:
            capex_rate = 0.015
        if df and df.estimated_repair_cost_high and df.estimated_repair_cost_high > price * 0.05:
            capex_rate = max(capex_rate, 0.02)
            snap.underwriting_notes.append(
                f"Large repair estimate (${df.estimated_repair_cost_high:,.0f}) from inspection "
                "— CapEx reserve increased to 2% of value."
            )
        snap.est_annual_capex_reserve = round(price * capex_rate, 0)

        snap.est_annual_total_expenses = round(
            snap.est_annual_property_tax
            + snap.est_annual_insurance_total
            + snap.est_annual_vacancy_loss
            + snap.est_annual_mgmt_fee
            + snap.est_annual_maintenance
            + snap.est_annual_capex_reserve
            + annual_hoa,    # HOA included here
            0,
        )

        # ── NOI and cap rate ───────────────────────────────────────────────────
        snap.est_annual_noi = round(annual_rent - snap.est_annual_total_expenses, 0)
        snap.cap_rate_pct   = round(snap.est_annual_noi / price * 100, 2)

        # ── Financing ──────────────────────────────────────────────────────────
        snap.down_payment_amount    = round(price * down_payment_pct, 0)
        snap.loan_amount            = round(price - snap.down_payment_amount, 0)
        monthly_pmt = _monthly_payment(snap.loan_amount, interest_rate_pct / 100.0, loan_term_years)
        snap.monthly_mortgage_payment = round(monthly_pmt, 0)
        snap.annual_debt_service      = round(monthly_pmt * 12, 0)

        # ── Cash flow ──────────────────────────────────────────────────────────
        snap.annual_cash_flow   = round(snap.est_annual_noi - snap.annual_debt_service, 0)
        snap.monthly_cash_flow  = round(snap.annual_cash_flow / 12, 0)
        total_cash_in = snap.down_payment_amount + (price * 0.03)   # +3% closing cost estimate
        snap.cash_on_cash_return_pct = round(snap.annual_cash_flow / total_cash_in * 100, 2) \
            if total_cash_in > 0 else None

        snap.dscr = round(snap.est_annual_noi / snap.annual_debt_service, 2) \
            if snap.annual_debt_service > 0 else None

        snap.break_even_occupancy_pct = round(
            (snap.est_annual_total_expenses + snap.annual_debt_service) / annual_rent * 100, 1
        ) if annual_rent > 0 else None

        # ── Verdict ────────────────────────────────────────────────────────────
        cf = snap.annual_cash_flow
        if cf is not None:
            if cf >= 2400:      # $200+/mo
                snap.cash_flow_verdict = "positive"
            elif cf >= -1200:   # -$100/mo to +$200/mo
                snap.cash_flow_verdict = "marginal"
            else:
                snap.cash_flow_verdict = "negative"

        if snap.cap_rate_pct is not None and snap.cap_rate_pct < 4.0:
            snap.underwriting_notes.append(
                f"Cap rate {snap.cap_rate_pct:.1f}% is below 4% — appreciation-dependent play."
            )
        if snap.dscr is not None and snap.dscr < 1.0:
            snap.underwriting_notes.append(
                f"DSCR {snap.dscr:.2f} < 1.0 — NOI does not cover mortgage payment."
            )
        if snap.break_even_occupancy_pct is not None and snap.break_even_occupancy_pct > 90:
            snap.underwriting_notes.append(
                f"Break-even occupancy {snap.break_even_occupancy_pct:.0f}% — very thin margin."
            )

        return snap
