"""
RegulatoryAnalystAgent — static 50-state + major-city tables for:
  - Eviction timeline and landlord-friendliness
  - Rent control exposure (state preemption + major-city ordinances)
  - Short-term rental (Airbnb/VRBO) regulations
  - Insurance market stress (states with carrier withdrawals)

All data comes from static lookup tables — no external API calls, no LLM.
Sources: NOLO eviction guides, Apartment List rent control database,
         Airbnb city regulations, Insurance Information Institute.
Last updated: 2024.
"""

import logging
from typing import Optional

from schemas.realestate import GeoResolution, RegulatoryRiskSnapshot

logger = logging.getLogger(__name__)


# ── Eviction timeline ─────────────────────────────────────────────────────────
# (state, median_days_filing_to_lockout, friendliness)
# "landlord_friendly" < 45 days; "neutral" 45–90; "tenant_friendly" > 90
_EVICTION: dict[str, tuple[int, str, str]] = {
    "AL": (45,  "landlord_friendly", "14-day notice, expedited hearing available."),
    "AK": (60,  "neutral",           "30-day notice; no eviction moratorium history."),
    "AZ": (30,  "landlord_friendly", "5-day notice for non-payment; swift court process."),
    "AR": (30,  "landlord_friendly", "Unlawful detainer heard within 10 days."),
    "CA": (120, "tenant_friendly",   "3-day notice + court; LA/SF add just-cause requirements."),
    "CO": (60,  "neutral",           "3-day notice; no statewide just-cause requirement."),
    "CT": (75,  "tenant_friendly",   "Summary process but overburdened courts slow it."),
    "DC": (150, "tenant_friendly",   "Just-cause required; lengthy administrative process."),
    "DE": (60,  "neutral",           "5-day notice; Justice of Peace Court handles cases."),
    "FL": (30,  "landlord_friendly", "3-day notice; no rent control statewide."),
    "GA": (30,  "landlord_friendly", "7-day dispossessory; courts typically 2–3 weeks."),
    "HI": (75,  "tenant_friendly",   "5-day notice; court backlogs common."),
    "ID": (30,  "landlord_friendly", "3-day notice; simple filing process."),
    "IL": (75,  "tenant_friendly",   "5-day notice; Cook County (Chicago) adds burdens."),
    "IN": (30,  "landlord_friendly", "10-day notice; small claims court within 2 weeks."),
    "IA": (30,  "landlord_friendly", "3-day notice; swift process."),
    "KS": (30,  "landlord_friendly", "3-day notice; simple court process."),
    "KY": (30,  "landlord_friendly", "7-day notice; district court within 3 weeks."),
    "LA": (45,  "landlord_friendly", "5-day notice; Rule for Possession swift."),
    "ME": (75,  "neutral",           "7-day notice; 30-day for month-to-month."),
    "MD": (60,  "neutral",           "4-day notice; District Court typically 3–4 weeks."),
    "MA": (90,  "tenant_friendly",   "14-day notice; Housing Court process extensive."),
    "MI": (45,  "neutral",           "7-day notice; District Court 2–4 weeks."),
    "MN": (60,  "neutral",           "14-day notice; Hennepin/Ramsey slower."),
    "MS": (30,  "landlord_friendly", "3-day notice; Justice Court swift."),
    "MO": (30,  "landlord_friendly", "Rent & Possession hearing within 2 weeks."),
    "MT": (30,  "landlord_friendly", "3-day notice; simple process."),
    "NE": (30,  "landlord_friendly", "3-day notice; County Court swift."),
    "NV": (45,  "neutral",           "7-day notice; summary eviction available."),
    "NH": (45,  "neutral",           "7-day notice; District Court 3–4 weeks."),
    "NJ": (120, "tenant_friendly",   "Anti-eviction Act; just cause required for all tenants."),
    "NM": (60,  "neutral",           "3-day notice; court hearing in 1–2 months."),
    "NY": (150, "tenant_friendly",   "Lengthy court process; HSTPA adds protections."),
    "NC": (30,  "landlord_friendly", "10-day notice; small claims swift."),
    "ND": (30,  "landlord_friendly", "3-day notice; District Court swift."),
    "OH": (30,  "landlord_friendly", "3-day notice; Municipal Court swift."),
    "OK": (30,  "landlord_friendly", "5-day notice; swift small claims."),
    "OR": (75,  "tenant_friendly",   "72-hour notice; Portland and statewide just-cause law."),
    "PA": (45,  "neutral",           "10-day notice; Magisterial District Court 3–4 weeks."),
    "RI": (60,  "neutral",           "5-day notice; District Court 4–6 weeks."),
    "SC": (30,  "landlord_friendly", "5-day notice; Magistrate Court swift."),
    "SD": (30,  "landlord_friendly", "3-day notice; swift process."),
    "TN": (30,  "landlord_friendly", "14-day notice; Sessions Court swift."),
    "TX": (30,  "landlord_friendly", "3-day notice; JP Court often within 2 weeks."),
    "UT": (30,  "landlord_friendly", "3-day notice; swift process."),
    "VT": (75,  "neutral",           "14-day notice; court process moderate."),
    "VA": (45,  "neutral",           "5-day notice; General District Court 3–4 weeks."),
    "WA": (90,  "tenant_friendly",   "Just-cause required (2019 law); 14-day notice minimum."),
    "WV": (30,  "landlord_friendly", "5-day notice; Magistrate Court swift."),
    "WI": (30,  "landlord_friendly", "5-day notice; small claims swift."),
    "WY": (30,  "landlord_friendly", "3-day notice; simple process."),
}


# ── Rent control ──────────────────────────────────────────────────────────────
# State-level preemption and major-city ordinances
# Format: (state_preempts, notes, major_city_controls)
# major_city_controls: list of (city_keyword, type, exemption)
_RENT_CONTROL: dict[str, tuple[bool, str, list]] = {
    "CA": (False, "No statewide preemption; AB 1482 caps increases at 5%+CPI for units 15+ yrs old.",
           [
               ("Los Angeles",   "rent stabilization", "Built after 10/1/78 exempt; SFRs with certain exceptions."),
               ("San Francisco",  "rent control",       "Pre-1979 buildings; Costa-Hawkins exempts newer units."),
               ("Oakland",        "rent control",       "Pre-1983 buildings; must pay just cause."),
               ("San Jose",       "rent stabilization", "Pre-9/7/79 units; 5% cap annually."),
               ("Berkeley",       "rent control",       "Pre-1980; very strict with just cause."),
               ("Santa Monica",   "rent control",       "Pre-1979; some of strictest regulations in state."),
               ("Sacramento",     "rent stabilization", "AB 1482 applies; no additional local control."),
               ("San Diego",      "rent stabilization", "AB 1482 applies; city added local protections 2023."),
           ]),
    "NY": (False, "Statewide rent stabilisation under HSTPA 2019; regulated units across NYC and Nassau/Westchester.",
           [
               ("New York City",  "rent stabilization", "Pre-1974 buildings with 6+ units. Preferential rent eliminated."),
               ("Albany",         "rent stabilization", "Emergency Tenant Protection Act (ETPA) coverage."),
               ("Buffalo",        "rent stabilization", "ETPA coverage opted in 2020."),
           ]),
    "NJ": (False, "PREEMPTION PARTIAL: municipalities may enact. Many towns have ordinances.",
           [
               ("Jersey City",    "rent stabilization", "Pre-1987 units with 5+ rooms; 4% annual cap."),
               ("Newark",         "rent control",       "Pre-1987 buildings; strict."),
               ("Hoboken",        "rent control",       "All residential; 5% cap."),
               ("Fort Lee",       "rent stabilization", "Applies to multi-family buildings."),
           ]),
    "OR": (False, "SB 608 (2019): statewide rent stabilization — max increase 7%+CPI annually; just cause required.",
           [
               ("Portland",       "rent control",       "Statewide law + local just cause; 90-day notice for no-fault."),
           ]),
    "MD": (False, "No statewide preemption; local governments may enact.",
           [
               ("Takoma Park",    "rent stabilization", "CPI-based; very strict local ordinance."),
               ("Hyattsville",    "rent stabilization", "5% cap on residential units."),
           ]),
    "DC": (False, "Comprehensive rent stabilization; most pre-1976 units covered.",
           [
               ("Washington",     "rent stabilization", "CPI+2% cap; units after 12/31/75 or with 5+ units."),
           ]),
    "WA": (False, "Statewide preemption repealed 2021; no statewide cap but local jurisdictions may act. Seattle studying.",
           []),
    "MN": (False, "Minneapolis and St. Paul enacted rent stabilisation (3% and 8% caps); state preemption contested.",
           [
               ("Saint Paul",     "rent stabilization", "3% annual cap; older ordinance being revised."),
               ("Minneapolis",    "rent stabilization", "Ordinance passed but legal challenges ongoing."),
           ]),
    "CO": (False, "Statewide preemption repealed 2021; Denver and others may now enact local rules.",
           []),
    # States with strong preemption (no local rent control permitted)
    "TX": (True, "State law preempts all local rent control ordinances (Tex. Prop. Code §214.902).", []),
    "FL": (True, "Preemption statute §125.0103; no local rent control.", []),
    "AZ": (True, "A.R.S. §33-1329 preempts all local rent control.", []),
    "GA": (True, "OCGA §44-7-19 preempts local rent control.", []),
    "NC": (True, "G.S. §42-14.1 preempts local rent control.", []),
    "TN": (True, "T.C.A. §66-35-101 preempts local rent control.", []),
    "OH": (True, "R.C. §5321.07 preempts local ordinances.", []),
    "IN": (True, "I.C. §32-31-1-20 preempts rent control.", []),
    "IL": (False, "Chicago does NOT have rent control; state preemption in place for most jurisdictions.", []),
}


# ── Short-term rental rules ───────────────────────────────────────────────────
# Format: (generally_permitted, permit_required, primary_residence_only, notes)
_STR_RULES: dict[str, tuple[bool, bool, bool, str]] = {
    "New York City": (False, False, False,
        "Local Law 18 (2023): must register, host must be present during stay, max 2 guests. "
        "Effectively bans most Airbnb. Applies NYC-wide."),
    "San Francisco": (True, True, True,
        "Permit required; must be primary residence; max 90 nights/yr if host absent."),
    "Los Angeles": (True, True, True,
        "Home-sharing ordinance: primary residence only; 120-night cap if unhosted; permit required."),
    "San Diego": (True, True, False,
        "Tier-1 (primary): unlimited. Tier-2 (non-primary): requires permit, capped per district."),
    "Seattle": (True, True, True,
        "Primary residence only; annual permit required ($75); must pay lodging tax."),
    "Portland": (True, True, True,
        "Owner-occupied primary residence required; annual permit $178; lodging tax applies."),
    "Denver": (True, True, True,
        "Short-term rental license required; primary residence only."),
    "Austin": (True, True, False,
        "License required; non-owner-occupied permits capped and grandfathered — hard to get new ones."),
    "Nashville": (True, True, False,
        "Owner-occupied: unlimited permits. Non-owner-occupied: moratorium on new permits since 2022."),
    "New Orleans": (True, True, True,
        "Temporary permit; must be primary residence; enforcement strict post-COVID."),
    "Miami Beach": (False, False, False,
        "Airbnb largely banned in residential zones; heavy fines for violations."),
    "Miami": (True, True, False,
        "Allowed in certain zones; permit required; 30-day minimum in some areas."),
    "Chicago": (True, True, False,
        "Shared housing ordinance; license required; 2-unit buildings restricted."),
    "Boston": (True, True, True,
        "Owner-occupied only; annual permit $100; insurance requirement."),
    "Phoenix": (True, False, False,
        "State preempts local bans; no primary residence requirement statewide (ARS §9-500.39)."),
    "Las Vegas": (True, True, False,
        "Clark County permit required; inspections; no primary residence restriction."),
    "Orlando": (True, True, False,
        "Orange County permit; annual inspection; no primary residence restriction."),
    "Tampa": (True, True, False,
        "Business tax receipt required; state preemption protects STR rights broadly."),
    "Dallas": (True, False, False,
        "State preemption (HB 4072, 2023): cities cannot ban STRs; no permit required statewide."),
    "Houston": (True, False, False,
        "No city permit required; state preemption since 2023."),
    "Charlotte": (True, True, False,
        "City permit required; inspection; zoning overlay determines eligibility."),
    "Atlanta": (True, True, False,
        "License required; primary or non-primary both allowed with permit."),
    "Minneapolis": (True, True, False,
        "License required; annual renewal; unlimited nights."),
}


# ── Insurance market stress by state ─────────────────────────────────────────
# "severe" = major carriers exiting, hard to insure; "elevated" = rising rates/some exits
_INSURANCE_STRESS: dict[str, tuple[str, str]] = {
    "CA": ("severe",   "State Farm, Allstate, Farmers pausing/exiting. Wildfire exposure. "
                       "FAIR Plan backstop overloaded. Rates +50–150% in high-risk zones."),
    "FL": ("severe",   "Multiple insurers insolvent 2022–2024. Hurricane + litigation risk. "
                       "Average premium >$6,000/yr. Citizens (state insurer) of last resort."),
    "LA": ("severe",   "Hurricane frequency + litigation; many carriers exited after Ida (2021)."),
    "TX": ("elevated", "Hail and wind claims; some carriers restricting coastal coverage. "
                       "Interior markets more manageable but rates rising."),
    "CO": ("elevated", "Wildfire and hail; Marshall Fire prompted some carrier pullbacks."),
    "OR": ("elevated", "Wildfire risk; some non-renewals in Eastern Oregon/Cascades."),
    "WA": ("elevated", "Western WA: normal; Eastern WA/Cascades: wildfire risk elevated."),
    "NC": ("elevated", "Coastal hurricane exposure; some rate increases but market functional."),
    "SC": ("elevated", "Coastal flood/hurricane; Myrtle Beach market elevated."),
    "GA": ("normal",   "No systemic stress; standard market available."),
    "AZ": ("normal",   "No systemic stress; premiums moderate."),
    "TX_COAST": ("severe", "Coastal Texas (Galveston, Houston) — Wind pool required; very high premiums."),
}


class RegulatoryAnalystAgent:
    """
    Returns a RegulatoryRiskSnapshot from static lookup tables.
    No external calls, no LLM.
    """

    def __init__(self, verbose: bool = False):
        self.verbose = verbose

    def analyze(
        self,
        geo: GeoResolution,
        city: str,
        state: str,
    ) -> RegulatoryRiskSnapshot:
        snap = RegulatoryRiskSnapshot()
        state_upper = state.upper()
        city_lower  = city.lower()

        # ── Eviction ──────────────────────────────────────────────────────────
        ev = _EVICTION.get(state_upper)
        if ev:
            snap.state_eviction_timeline_days = ev[0]
            snap.eviction_friendliness        = ev[1]   # type: ignore
            snap.eviction_process_notes       = ev[2]

        # ── Rent control ──────────────────────────────────────────────────────
        rc = _RENT_CONTROL.get(state_upper)
        if rc:
            state_preempts, rc_note, city_controls = rc
            if state_preempts:
                snap.rent_control_exposure  = False
                snap.rent_control_type      = "none"
                snap.rent_control_details   = rc_note
            else:
                # Check if this specific city has rent control
                matched_city_rc = None
                for city_kw, rc_type, rc_exempt in city_controls:
                    if city_kw.lower() in city_lower or city_lower in city_kw.lower():
                        matched_city_rc = (city_kw, rc_type, rc_exempt)
                        break

                if matched_city_rc:
                    snap.rent_control_exposure  = True
                    snap.rent_control_type      = matched_city_rc[1]
                    snap.rent_control_exemption = matched_city_rc[2]
                    snap.rent_control_details   = (
                        f"{matched_city_rc[0]}: {matched_city_rc[1].replace('_', ' ').title()}. "
                        f"{matched_city_rc[2]}"
                    )
                else:
                    snap.rent_control_exposure = False
                    snap.rent_control_type     = "none"
                    snap.rent_control_details  = rc_note

        else:
            # Default: no rent control data, assume no control
            snap.rent_control_exposure = False
            snap.rent_control_type     = "none"

        # ── STR rules ─────────────────────────────────────────────────────────
        str_matched = None
        for city_kw, str_tuple in _STR_RULES.items():
            if city_kw.lower() in city_lower or city_lower in city_kw.lower():
                str_matched = str_tuple
                break

        if str_matched:
            snap.str_generally_permitted   = str_matched[0]
            snap.str_permit_required       = str_matched[1]
            snap.str_primary_residence_only = str_matched[2]
            snap.str_notes                 = str_matched[3]
        else:
            # State-level default
            if state_upper in ("TX", "FL", "AZ", "TN"):
                snap.str_generally_permitted    = True
                snap.str_permit_required        = False
                snap.str_primary_residence_only = False
                snap.str_notes = f"{state_upper} has state preemption protecting STR rights; check local ordinances."
            else:
                snap.str_generally_permitted    = True
                snap.str_permit_required        = True
                snap.str_primary_residence_only = False
                snap.str_notes = "No specific city data — verify local permit requirements."

        # ── Insurance stress ──────────────────────────────────────────────────
        ins = _INSURANCE_STRESS.get(state_upper, ("normal", "No known systemic insurance market stress."))
        snap.insurance_market_stress = ins[0]    # type: ignore
        snap.insurance_stress_notes  = ins[1]

        # ── Just cause and landlord license ───────────────────────────────────
        just_cause_states = {"CA", "OR", "WA", "NJ", "DC", "NY", "MD", "NH"}
        snap.just_cause_eviction_required = state_upper in just_cause_states

        license_states = {"CA", "NY", "DC", "MD", "NJ", "IL", "PA", "MA", "HI", "NC", "WI", "CT"}
        snap.landlord_license_required = state_upper in license_states

        # ── Overall regulatory risk score ─────────────────────────────────────
        risk_score = 0
        if snap.eviction_friendliness == "tenant_friendly":   risk_score += 3
        elif snap.eviction_friendliness == "neutral":          risk_score += 1
        if snap.rent_control_exposure:                         risk_score += 3
        if snap.just_cause_eviction_required:                  risk_score += 2
        if snap.insurance_market_stress == "severe":           risk_score += 2
        elif snap.insurance_market_stress == "elevated":       risk_score += 1
        if snap.str_generally_permitted is False:              risk_score += 1
        if snap.landlord_license_required:                     risk_score += 1

        if risk_score <= 2:
            snap.overall_regulatory_risk = "low"
        elif risk_score <= 4:
            snap.overall_regulatory_risk = "moderate"
        elif risk_score <= 7:
            snap.overall_regulatory_risk = "high"
        else:
            snap.overall_regulatory_risk = "very_high"

        # Build summary
        parts = []
        if snap.eviction_friendliness:
            parts.append(f"Eviction: {snap.eviction_friendliness.replace('_', ' ')} "
                         f"(~{snap.state_eviction_timeline_days} days)")
        if snap.rent_control_exposure:
            parts.append(f"Rent control: YES — {snap.rent_control_type}")
        else:
            parts.append("Rent control: none")
        if snap.insurance_market_stress in ("elevated", "severe"):
            parts.append(f"Insurance: {snap.insurance_market_stress}")
        if snap.just_cause_eviction_required:
            parts.append("Just-cause eviction required")
        snap.summary = ". ".join(parts) + f". Overall regulatory risk: {snap.overall_regulatory_risk}."

        if self.verbose:
            logger.info(f"RegulatoryAnalyst: {snap.summary}")

        return snap
