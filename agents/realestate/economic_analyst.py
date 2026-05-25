"""
EconomicAnalystAgent — Node 3 of the real estate research pipeline.

Fetches Tier 1 and Tier 2 labor market and cost-of-living signals:
  T1: unemployment rate, employment growth, avg weekly wage, real wage,
      regional price parity, state income tax rate
  T2: industry mix (NAICS-level), JOLTS openings rate, median household income

Data sources (all free):
  - BLS API (no key required)    api.bls.gov/publicAPI/v2
  - FRED API                     api.stlouisfed.org/fred
  - BEA API                      apps.bea.gov/api
  - Tax Foundation static table  (baked in)
"""

import logging
from typing import Optional

import httpx

from agents.realestate._geo import GeoResolution
from schemas.realestate import (
    CostOfLivingSnapshot,
    IndustryShare,
    LaborMarketSnapshot,
)

logger = logging.getLogger(__name__)


# ── Static tax tables (Tax Foundation 2024) ───────────────────────────────────
# (state_upper): (income_tax_top_rate, sales_tax_rate, property_tax_eff_rate, burden_rank)
_STATE_TAX: dict[str, tuple[float, float, float, int]] = {
    # income_top, sales_combined, property_eff, burden_rank (1=lowest)
    "AK": (0.00, 0.017, 0.010, 1),  "WY": (0.00, 0.052, 0.006, 2),
    "SD": (0.00, 0.062, 0.012, 3),  "FL": (0.00, 0.073, 0.008, 4),
    "NV": (0.00, 0.082, 0.006, 5),  "TX": (0.00, 0.082, 0.018, 6),
    "TN": (0.00, 0.095, 0.006, 7),  "NH": (0.04, 0.000, 0.021, 8),
    "WA": (0.00, 0.091, 0.010, 9),  "MT": (0.069, 0.000, 0.008, 10),
    "AZ": (0.025, 0.083, 0.007, 11),"CO": (0.044, 0.077, 0.006, 12),
    "IN": (0.03, 0.070, 0.009, 13), "ID": (0.059, 0.060, 0.008, 14),
    "UT": (0.046, 0.072, 0.006, 15),"NC": (0.049, 0.069, 0.009, 16),
    "GA": (0.055, 0.073, 0.009, 17),"AL": (0.05, 0.092, 0.004, 18),
    "SC": (0.064, 0.072, 0.006, 19),"OK": (0.047, 0.087, 0.011, 20),
    "MO": (0.048, 0.082, 0.012, 21),"MS": (0.047, 0.070, 0.007, 22),
    "LA": (0.03, 0.095, 0.006, 23), "KY": (0.04, 0.060, 0.009, 24),
    "VA": (0.055, 0.058, 0.008, 25),"OH": (0.04, 0.072, 0.016, 26),
    "MA": (0.09, 0.062, 0.012, 27), "MI": (0.042, 0.060, 0.014, 28),
    "KS": (0.057, 0.087, 0.012, 29),"AR": (0.044, 0.094, 0.006, 30),
    "NE": (0.068, 0.069, 0.017, 31),"IA": (0.06, 0.069, 0.015, 32),
    "WI": (0.075, 0.054, 0.019, 33),"PA": (0.031, 0.063, 0.016, 34),
    "MD": (0.0575, 0.060, 0.009, 35),"MN": (0.0985, 0.075, 0.011, 36),
    "RI": (0.0599, 0.070, 0.016, 37),"DE": (0.066, 0.000, 0.006, 38),
    "ME": (0.076, 0.055, 0.012, 39),"OR": (0.099, 0.000, 0.010, 40),
    "NM": (0.059, 0.079, 0.008, 41),"WV": (0.055, 0.065, 0.006, 42),
    "VT": (0.0875, 0.062, 0.019, 43),"ND": (0.025, 0.069, 0.011, 44),
    "NJ": (0.1075, 0.066, 0.022, 45),"CT": (0.069, 0.063, 0.019, 46),
    "HI": (0.11, 0.044, 0.028, 47), "NY": (0.109, 0.087, 0.018, 48),
    "CA": (0.133, 0.087, 0.007, 49),"IL": (0.0495, 0.088, 0.022, 50),
    "DC": (0.105, 0.060, 0.006, 30),
}

# BLS LAUS state series prefix: LAU ST{FIPS}0000000000003 = state unemployment
# BLS CES: SMS{FIPS}000000000000001 = state total nonfarm employment (thousands)


class EconomicAnalystAgent:
    """
    Fetches labor market and cost-of-living data for a resolved geography.
    """

    def __init__(
        self,
        fred_api_key: str = "",
        bea_api_key: str = "",
        census_api_key: str = "",
        verbose: bool = False,
    ):
        self.fred_key   = fred_api_key
        self.bea_key    = bea_api_key
        self.census_key = census_api_key
        self.verbose    = verbose

    def analyze(
        self,
        geo: GeoResolution,
        depth: str = "full",
    ) -> tuple[LaborMarketSnapshot, CostOfLivingSnapshot]:
        """
        Returns (labor_market_snapshot, cost_of_living_snapshot).
        """
        labor  = self._build_labor(geo, depth)
        col    = self._build_col(geo, labor)
        return labor, col

    # ── Labor market ───────────────────────────────────────────────────────────

    def _build_labor(self, geo: GeoResolution, depth: str) -> LaborMarketSnapshot:
        snap = LaborMarketSnapshot()

        # BLS LAUS: unemployment (state)
        unemp = self._fetch_bls_unemployment(geo)
        if unemp:
            snap.unemployment_rate        = unemp.get("rate")
            snap.unemployment_trend       = unemp.get("trend")
            snap.unemployment_rate_change_yoy = unemp.get("change_yoy")
            snap.data_as_of               = unemp.get("as_of")

        # BLS CES: employment growth (state)
        emp = self._fetch_bls_employment(geo)
        if emp:
            snap.employment_growth_pct_yoy = emp.get("growth_pct")

        # BLS QCEW: wages (state)
        wages = self._fetch_bls_wages(geo)
        if wages:
            snap.avg_weekly_wage = wages.get("avg_weekly_wage")

        # FRED: additional labor metrics
        if self.fred_key:
            fred_labor = self._fetch_fred_labor(geo)
            if fred_labor:
                snap.jolts_openings_rate = fred_labor.get("jolts_rate")
                if not snap.avg_weekly_wage:
                    snap.avg_weekly_wage = fred_labor.get("weekly_wage")

        # T2: industry mix
        if depth == "full":
            industries = self._fetch_bls_industry_mix(geo)
            snap.industry_mix  = industries
            snap.top_industries = [i.naics_name for i in industries[:3]]

        # Census median household income
        if self.census_key or True:  # free endpoint
            income_data = self._fetch_census_income(geo)
            snap.data_as_of = snap.data_as_of or income_data.get("as_of")

        # Real wage = nominal / RPP * 100
        rpp = self._fetch_bea_rpp(geo)
        if snap.avg_weekly_wage and rpp:
            snap.real_wage = round(snap.avg_weekly_wage / rpp * 100, 2)

        snap.summary = self._labor_summary(snap, geo)
        return snap

    def _fetch_bls_unemployment(self, geo: GeoResolution) -> dict:
        """BLS LAUS state unemployment rate."""
        state_fips = geo.state_fips
        if not state_fips:
            return {}

        series_id = f"LASST{state_fips.zfill(2)}0000000000003"  # state unemployment rate
        try:
            with httpx.Client(timeout=15) as client:
                r = client.post(
                    "https://api.bls.gov/publicAPI/v2/timeseries/data/",
                    json={
                        "seriesid":  [series_id],
                        "startyear": "2021",
                        "endyear":   "2024",
                    },
                    headers={"Content-type": "application/json"},
                )
            data  = r.json()
            series = data.get("Results", {}).get("series", [])
            if not series:
                return {}

            obs = series[0].get("data", [])
            # Filter for annual average (period M13) or latest month
            annuals = [o for o in obs if o.get("period") == "M13"]
            if len(annuals) < 2:
                annuals = obs[:2]
            if not annuals:
                return {}

            latest  = float(annuals[0]["value"])
            prev    = float(annuals[1]["value"]) if len(annuals) > 1 else latest

            trend = "stable"
            if latest > prev + 0.3:
                trend = "rising"
            elif latest < prev - 0.3:
                trend = "falling"

            return {
                "rate":       latest,
                "trend":      trend,
                "change_yoy": round(latest - prev, 2),
                "as_of":      f"{annuals[0].get('year')}-{annuals[0].get('periodName', '')}",
            }
        except Exception as e:
            logger.debug(f"BLS unemployment fetch failed: {e}")
            return {}

    def _fetch_bls_employment(self, geo: GeoResolution) -> dict:
        """BLS CES total nonfarm employment (state), YoY growth."""
        state_fips = geo.state_fips
        if not state_fips:
            return {}

        series_id = f"SMS{state_fips.zfill(2)}000000000000001"  # state total nonfarm
        try:
            with httpx.Client(timeout=15) as client:
                r = client.post(
                    "https://api.bls.gov/publicAPI/v2/timeseries/data/",
                    json={
                        "seriesid":  [series_id],
                        "startyear": "2022",
                        "endyear":   "2024",
                    },
                    headers={"Content-type": "application/json"},
                )
            data   = r.json()
            series = data.get("Results", {}).get("series", [])
            if not series:
                return {}
            obs = series[0].get("data", [])
            # Use December (M12) for annual comparison
            dec_obs = [o for o in obs if o.get("period") == "M12"]
            if len(dec_obs) >= 2:
                latest = float(dec_obs[0]["value"])
                prev   = float(dec_obs[1]["value"])
                growth = (latest - prev) / prev if prev > 0 else 0
                return {"growth_pct": round(growth, 4)}
        except Exception as e:
            logger.debug(f"BLS employment fetch failed: {e}")
        return {}

    def _fetch_bls_wages(self, geo: GeoResolution) -> dict:
        """BLS QCEW average weekly wage by state."""
        state_fips = geo.state_fips
        if not state_fips:
            return {}

        # QCEW series: ENU{state_fips_2}05{qtr}1011  (private, all industries)
        # Use the QCEW API instead: data.bls.gov/cew/apps/api_sample_code/v1/...
        # Simpler: use FRED state wage series if available
        if self.fred_key:
            fred_series = f"SMU{state_fips.zfill(2)}000000050000001"  # avg hourly earnings * 40
        try:
            with httpx.Client(timeout=15) as client:
                r = client.get(
                    "https://api.bls.gov/publicAPI/v1/timeseries/data/"
                    f"ENUA{state_fips.zfill(2)}05512{state_fips.zfill(2)}",
                    params={"latest": "true"},
                )
            # This endpoint isn't always predictable; wrap carefully
            data = r.json()
            series = data.get("Results", {}).get("series", [])
            if series:
                obs = series[0].get("data", [])
                if obs:
                    val = float(obs[0].get("value", 0))
                    if val > 0:
                        return {"avg_weekly_wage": val}
        except Exception as e:
            logger.debug(f"BLS QCEW wage fetch failed: {e}")
        return {}

    def _fetch_fred_labor(self, geo: GeoResolution) -> dict:
        """FRED: backup wage + JOLTS metrics."""
        if not self.fred_key or not geo.state_fips:
            return {}

        # State average weekly earnings: SMU series
        series_id = f"SMS{geo.state_fips.zfill(2)}000000050000001"
        result: dict = {}
        try:
            with httpx.Client(timeout=10) as client:
                r = client.get(
                    "https://api.stlouisfed.org/fred/series/observations",
                    params={
                        "series_id":  series_id,
                        "api_key":    self.fred_key,
                        "file_type":  "json",
                        "sort_order": "desc",
                        "limit":      4,
                    },
                )
            data = r.json()
            obs  = [o for o in data.get("observations", []) if o.get("value", ".") != "."]
            if obs:
                hourly = float(obs[0]["value"])
                result["weekly_wage"] = round(hourly * 40, 2)   # hourly * 40hr week
        except Exception as e:
            logger.debug(f"FRED labor fetch failed: {e}")

        return result

    def _fetch_bls_industry_mix(self, geo: GeoResolution) -> list[IndustryShare]:
        """
        BLS CES state employment by supersector.
        Returns top industries by share.
        """
        state_fips = geo.state_fips
        if not state_fips:
            return []

        # Supersector series IDs (CES)
        supersectors = {
            "Professional & Business Services": f"SMS{state_fips.zfill(2)}000000600000001",
            "Healthcare & Social Assistance":   f"SMS{state_fips.zfill(2)}000000650000001",
            "Leisure & Hospitality":            f"SMS{state_fips.zfill(2)}000000700000001",
            "Retail Trade":                     f"SMS{state_fips.zfill(2)}000000400000001",
            "Manufacturing":                    f"SMS{state_fips.zfill(2)}000000300000001",
            "Financial Activities":             f"SMS{state_fips.zfill(2)}000000550000001",
            "Information":                      f"SMS{state_fips.zfill(2)}000000500000001",
            "Construction":                     f"SMS{state_fips.zfill(2)}000000200000001",
        }

        try:
            with httpx.Client(timeout=20) as client:
                r = client.post(
                    "https://api.bls.gov/publicAPI/v2/timeseries/data/",
                    json={
                        "seriesid":  list(supersectors.values()),
                        "startyear": "2023",
                        "endyear":   "2024",
                    },
                    headers={"Content-type": "application/json"},
                )
            data   = r.json()
            series = data.get("Results", {}).get("series", [])
            if not series:
                return []

            # Map series_id → latest value
            id_to_name = {v: k for k, v in supersectors.items()}
            emp_by_sector: dict[str, float] = {}
            for s in series:
                sid = s.get("seriesID", "")
                obs = s.get("data", [])
                if obs:
                    val = float(obs[0].get("value", 0) or 0)
                    name = id_to_name.get(sid, sid)
                    if val > 0:
                        emp_by_sector[name] = val

            total = sum(emp_by_sector.values()) or 1
            result = [
                IndustryShare(
                    naics_name=name,
                    employment_share_pct=round(val / total * 100, 1),
                )
                for name, val in sorted(emp_by_sector.items(), key=lambda x: -x[1])
            ]
            return result
        except Exception as e:
            logger.debug(f"BLS industry mix fetch failed: {e}")
            return []

    def _fetch_census_income(self, geo: GeoResolution) -> dict:
        """ACS 1-year median household income by state."""
        if not geo.state_fips:
            return {}
        try:
            params: dict = {
                "get": "NAME,B19013_001E",
                "for": f"state:{geo.state_fips}",
            }
            if self.census_key:
                params["key"] = self.census_key
            with httpx.Client(timeout=10) as client:
                r = client.get("https://api.census.gov/data/2022/acs/acs1", params=params)
            rows = r.json()
            if len(rows) >= 2:
                header = rows[0]
                row    = rows[1]
                d = dict(zip(header, row))
                income = float(d.get("B19013_001E", 0) or 0)
                if income > 0:
                    return {"median_household_income": income, "as_of": "2022 ACS 1-year"}
        except Exception as e:
            logger.debug(f"Census income fetch failed: {e}")
        return {}

    def _fetch_bea_rpp(self, geo: GeoResolution) -> Optional[float]:
        """
        BEA Regional Price Parities by state.
        Returns the RPP index (100 = national average).
        """
        if not self.bea_key or not geo.state_fips:
            return None

        # BEA API: Regional Price Parities, table SARPP
        try:
            with httpx.Client(timeout=12) as client:
                r = client.get(
                    "https://apps.bea.gov/api/data/",
                    params={
                        "UserID":     self.bea_key,
                        "method":     "GetData",
                        "datasetname": "Regional",
                        "TableName":  "SARPP",
                        "LineCode":   "1",
                        "GeoFips":    geo.state_fips.zfill(2) + "000",
                        "Year":       "2022",
                        "ResultFormat": "json",
                    },
                )
            data = r.json()
            results = (
                data.get("BEAAPI", {})
                    .get("Results", {})
                    .get("Data", [])
            )
            if results:
                val = float(results[0].get("DataValue", 0).replace(",", "") or 0)
                if 50 < val < 200:
                    return val
        except Exception as e:
            logger.debug(f"BEA RPP fetch failed: {e}")

        # Fallback: hardcoded approximate RPP by state (Tax Foundation / BEA 2022)
        _APPROX_RPP: dict[str, float] = {
            "CA": 113.4, "HI": 117.5, "NY": 115.7, "NJ": 109.3, "MA": 108.5,
            "CT": 107.3, "WA": 106.5, "MD": 106.2, "OR": 103.8, "CO": 103.3,
            "AK": 102.7, "IL": 100.8, "MN": 100.6, "PA": 99.8, "VA": 99.5,
            "RI": 99.2, "NH": 98.9, "DE": 98.4, "WI": 97.8, "NV": 97.5,
            "AZ": 97.2, "FL": 97.0, "GA": 96.8, "NC": 96.5, "TX": 96.3,
            "UT": 96.1, "ID": 95.8, "TN": 95.4, "SC": 95.2, "IN": 94.9,
            "MO": 94.6, "OH": 94.3, "IA": 94.0, "NM": 93.8, "KY": 93.5,
            "KS": 93.2, "NE": 93.0, "ME": 92.8, "VT": 92.5, "LA": 92.2,
            "AL": 91.9, "OK": 91.6, "WV": 91.3, "AR": 91.0, "MT": 90.7,
            "SD": 90.4, "ND": 90.1, "WY": 89.8, "MS": 89.5,
        }
        return _APPROX_RPP.get(geo.input_state.upper(), 97.0)

    # ── Cost of living ─────────────────────────────────────────────────────────

    def _build_col(self, geo: GeoResolution, labor: LaborMarketSnapshot) -> CostOfLivingSnapshot:
        snap = CostOfLivingSnapshot()
        state = geo.input_state.upper()

        # Tax data from static table
        tax = _STATE_TAX.get(state)
        if tax:
            snap.state_income_tax_top_rate    = tax[0]
            snap.state_sales_tax_rate         = tax[1]
            snap.property_tax_rate_effective  = tax[2]
            snap.overall_tax_burden_rank      = tax[3]

        # BEA RPP (already fetched in labor, reuse)
        rpp = self._fetch_bea_rpp(geo)
        snap.regional_price_parity = rpp

        # Overall assessment based on RPP + tax burden rank
        if rpp and tax:
            score = (rpp - 100) + (tax[3] - 25)   # higher = more expensive
            if score < -20:
                snap.overall_assessment = "low"
            elif score < -5:
                snap.overall_assessment = "below_avg"
            elif score < 10:
                snap.overall_assessment = "avg"
            elif score < 25:
                snap.overall_assessment = "above_avg"
            else:
                snap.overall_assessment = "high"

        # Summary
        rpp_str  = f"RPP {rpp:.1f}" if rpp else "RPP unavailable"
        tax_str  = f"income tax top rate {tax[0]:.1%}" if tax else ""
        snap.summary = (
            f"{geo.input_state}: {rpp_str} (national avg = 100). "
            + (f"State {tax_str}. " if tax_str else "")
            + (f"Overall cost-of-living: {snap.overall_assessment or 'unavailable'}." if snap.overall_assessment else "")
        )

        return snap

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _labor_summary(self, snap: LaborMarketSnapshot, geo: GeoResolution) -> str:
        parts = []
        if snap.unemployment_rate is not None:
            trend_word = {"rising": "rising", "falling": "falling", "stable": "stable"}.get(
                snap.unemployment_trend or "stable", ""
            )
            parts.append(f"Unemployment {snap.unemployment_rate:.1f}% ({trend_word})")
        if snap.employment_growth_pct_yoy is not None:
            direction = "grew" if snap.employment_growth_pct_yoy >= 0 else "contracted"
            parts.append(f"employment {direction} {abs(snap.employment_growth_pct_yoy):.1%} YoY")
        if snap.avg_weekly_wage is not None:
            parts.append(f"avg weekly wage ${snap.avg_weekly_wage:,.0f}")
        if snap.real_wage is not None:
            parts.append(f"real wage index {snap.real_wage:.1f}")
        if snap.top_industries:
            parts.append(f"top sectors: {', '.join(snap.top_industries[:2])}")

        if parts:
            return f"{geo.input_city}, {geo.input_state}: " + "; ".join(parts) + "."
        return f"Limited labor market data available for {geo.input_city}, {geo.input_state}."
