"""
NeighborhoodAnalystAgent — hyperlocal signals at ZIP, Census tract, and address level.

Data sources:
  - ACS 5-Year Estimates (Census API) — tract demographics: income, owner-occ %, education
  - HUD USPS Residential Vacancy Data — ZIP-level vacancy by quarter
  - Walk Score API (optional) — walkability and transit score
  - Census Bureau Geocoder — ZIP → FIPS tract mapping

All external calls fail silently. Returns partial data if APIs unavailable.
"""

import json
import logging
import urllib.parse
import urllib.request
from typing import Optional

from schemas.realestate import GeoResolution, NeighborhoodSnapshot

logger = logging.getLogger(__name__)


# ── HUD USPS ZIP vacancy endpoint ─────────────────────────────────────────────
_HUD_VACANCY_URL = (
    "https://www.huduser.gov/hudapi/public/usps?type=4&query={zip}"
)

# ── Census ACS endpoint ────────────────────────────────────────────────────────
_ACS_BASE = "https://api.census.gov/data/2022/acs/acs5"

# ── Walk Score API ─────────────────────────────────────────────────────────────
_WALKSCORE_URL = "https://api.walkscore.com/score?format=json&address={addr}&lat={lat}&lon={lon}&transit=1&bike=1&wsapikey={key}"


def _safe_get(url: str, timeout: int = 10) -> Optional[dict]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return json.loads(r.read())
    except Exception as e:
        logger.debug(f"HTTP GET failed {url[:80]}: {e}")
        return None


class NeighborhoodAnalystAgent:
    """
    Fetches hyperlocal neighborhood signals for a property.
    """

    def __init__(
        self,
        census_api_key: str = "",
        walk_score_api_key: str = "",
        verbose: bool = False,
    ):
        self.census_key      = census_api_key
        self.walk_score_key  = walk_score_api_key
        self.verbose         = verbose

    def analyze(
        self,
        geo: GeoResolution,
        zip_code: Optional[str],
        city: str,
        state: str,
        address: str = "",
        depth: str = "full",
        # Walk score already fetched by HousingAnalystAgent (pass through)
        walk_score: Optional[float] = None,
        transit_score: Optional[float] = None,
    ) -> NeighborhoodSnapshot:

        snap = NeighborhoodSnapshot()

        # Carry over any walk/transit scores already fetched by HousingAnalystAgent
        snap.walkability_score = walk_score
        snap.transit_score     = transit_score

        zip_q = zip_code or (geo.input_zip if geo else None)
        county_fips = geo.county_fips if geo else None

        # ── ACS tract demographics ─────────────────────────────────────────────
        if depth == "full" and county_fips and len(county_fips) == 5:
            self._fetch_acs_tract(snap, county_fips, state, geo)

        # ── HUD USPS ZIP vacancy ───────────────────────────────────────────────
        if depth == "full" and zip_q:
            self._fetch_hud_vacancy(snap, zip_q)

        # ── Walk Score (if not already set and key available) ─────────────────
        if depth == "full" and not snap.walkability_score and self.walk_score_key:
            if geo and geo.latitude and geo.longitude:
                addr_enc = urllib.parse.quote(address or f"{city}, {state}")
                url = _WALKSCORE_URL.format(
                    addr=addr_enc,
                    lat=geo.latitude,
                    lon=geo.longitude,
                    key=self.walk_score_key,
                )
                data = _safe_get(url)
                if data:
                    snap.walkability_score = data.get("walkscore")
                    transit_data = data.get("transit", {})
                    if transit_data:
                        snap.transit_score = transit_data.get("score")

        # ── Rental demand signal (synthesize from available data) ─────────────
        self._infer_rental_demand(snap)

        # ── Neighborhood trajectory ───────────────────────────────────────────
        self._infer_trajectory(snap)

        # ── Summary ───────────────────────────────────────────────────────────
        parts = []
        if snap.tract_median_income:
            parts.append(f"Tract median income: ${snap.tract_median_income:,.0f}")
        if snap.tract_owner_occ_pct is not None:
            parts.append(f"Owner-occ: {snap.tract_owner_occ_pct:.0f}%")
        if snap.zip_rental_vacancy_rate is not None:
            parts.append(f"ZIP rental vacancy: {snap.zip_rental_vacancy_rate:.1f}%")
        if snap.rental_demand_signal:
            parts.append(f"Rental demand: {snap.rental_demand_signal}")
        if snap.walkability_score:
            parts.append(f"Walk Score: {snap.walkability_score:.0f}")
        snap.summary = "; ".join(parts) + "." if parts else "Neighborhood data limited."

        if self.verbose:
            logger.info(f"NeighborhoodAnalyst: {snap.summary}")

        return snap

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _fetch_acs_tract(
        self,
        snap: NeighborhoodSnapshot,
        county_fips: str,
        state: str,
        geo: GeoResolution,
    ) -> None:
        """Fetch tract-level ACS variables for the county."""
        try:
            state_fips  = county_fips[:2]
            county_code = county_fips[2:]

            # Variables:
            # B19013_001E = median HH income
            # B25003_001E = total tenure, B25003_002E = owner-occupied
            # B15003_022E = bachelor's degree count, B15003_023E = master's, 001E = total 25+
            # B01003_001E = total population
            variables = (
                "B19013_001E,"
                "B25003_001E,B25003_002E,"
                "B15003_001E,B15003_022E,B15003_023E,B15003_024E,B15003_025E,"
                "B01003_001E"
            )
            key_part = f"&key={self.census_key}" if self.census_key else ""
            url = (
                f"{_ACS_BASE}?get={variables}"
                f"&for=tract:*"
                f"&in=state:{state_fips}%20county:{county_code}"
                f"{key_part}"
            )
            data = _safe_get(url)
            if not data or len(data) < 2:
                return

            # Aggregate across tracts (county average weighted by population)
            header = data[0]
            rows   = data[1:]

            def col(name: str) -> int:
                return header.index(name) if name in header else -1

            total_pop = 0
            income_sum = 0.0
            tenure_owner = 0
            tenure_total = 0
            edu_total = 0
            edu_college = 0

            for row in rows:
                try:
                    pop = int(row[col("B01003_001E")] or 0)
                    total_pop += pop

                    inc = int(row[col("B19013_001E")] or -1)
                    if inc > 0:
                        income_sum += inc * pop

                    to = int(row[col("B25003_001E")] or 0)
                    oo = int(row[col("B25003_002E")] or 0)
                    tenure_total  += to
                    tenure_owner  += oo

                    et = int(row[col("B15003_001E")] or 0)
                    ec = sum(
                        int(row[col(v)] or 0)
                        for v in ("B15003_022E", "B15003_023E", "B15003_024E", "B15003_025E")
                    )
                    edu_total   += et
                    edu_college += ec
                except Exception:
                    pass

            if total_pop > 0 and income_sum > 0:
                snap.tract_median_income = round(income_sum / total_pop, 0)
            if tenure_total > 0:
                snap.tract_owner_occ_pct = round(tenure_owner / tenure_total * 100, 1)
            if edu_total > 0:
                snap.tract_college_edu_pct = round(edu_college / edu_total * 100, 1)

        except Exception as e:
            logger.debug(f"ACS fetch failed: {e}")

    def _fetch_hud_vacancy(self, snap: NeighborhoodSnapshot, zip_code: str) -> None:
        """Fetch HUD USPS residential vacancy data for a ZIP."""
        try:
            url = f"https://www.huduser.gov/hudapi/public/usps?type=4&query={zip_code}"
            data = _safe_get(url, timeout=8)
            if not data:
                return

            results = data.get("data", {}).get("results", [])
            if not results:
                return

            # Latest record
            latest = sorted(results, key=lambda r: r.get("year", 0) * 100 + r.get("quarter", 0))[-1]
            res_vac = latest.get("res_vacrte")   # residential vacancy rate (%)
            if res_vac is not None:
                snap.zip_rental_vacancy_rate = float(res_vac)

        except Exception as e:
            logger.debug(f"HUD vacancy fetch failed for {zip_code}: {e}")

    def _infer_rental_demand(self, snap: NeighborhoodSnapshot) -> None:
        """Infer rental_demand_signal from vacancy rate and owner-occupancy."""
        signals = []

        if snap.zip_rental_vacancy_rate is not None:
            if snap.zip_rental_vacancy_rate < 4.0:
                signals.append("strong")
            elif snap.zip_rental_vacancy_rate < 7.0:
                signals.append("moderate")
            else:
                signals.append("soft")

        if snap.tract_owner_occ_pct is not None:
            if snap.tract_owner_occ_pct < 40:
                signals.append("strong")   # established rental market
            elif snap.tract_owner_occ_pct < 60:
                signals.append("moderate")
            else:
                signals.append("soft")    # majority owner-occ, less rental demand

        if not signals:
            return
        from collections import Counter
        most_common = Counter(signals).most_common(1)[0][0]
        snap.rental_demand_signal = most_common   # type: ignore

    def _infer_trajectory(self, snap: NeighborhoodSnapshot) -> None:
        """Infer neighborhood trajectory from income and owner-occ trends."""
        if snap.tract_income_growth_5yr_pct is not None:
            g = snap.tract_income_growth_5yr_pct
            if g > 15:
                snap.neighborhood_trajectory = "appreciating"
            elif g > 5:
                snap.neighborhood_trajectory = "stable"
            else:
                snap.neighborhood_trajectory = "declining"
        elif snap.tract_college_edu_pct is not None:
            if snap.tract_college_edu_pct > 40:
                snap.neighborhood_trajectory = "appreciating"
            elif snap.tract_college_edu_pct > 20:
                snap.neighborhood_trajectory = "stable"
            else:
                snap.neighborhood_trajectory = "declining"
