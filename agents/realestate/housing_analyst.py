"""
HousingAnalystAgent — Node 4 of the real estate research pipeline.

Fetches housing market metrics, demand/quality-of-life factors, and
property-level + county-level climate/flood risk.

Data sources (all free):
  - Zillow Research CSV    zillow.com/research/data (cached locally)
  - Redfin Data Center     redfin.com/news/data-center (cached locally)
  - Census Building Permits api.census.gov/data/eits/bps
  - HUD Fair Market Rents  huduser.gov/portal/datasets/fmr.html
  - FBI NIBRS/UCR          api.usa.gov/crime/fbi/sapi
  - EPA AQS                aqs.epa.gov/ata/api
  - Walk Score             api.walkscore.com
  - FEMA NFHL (flood zone) hazards.fema.gov (ArcGIS REST — property level)
  - FEMA National Risk Index hazards.fema.gov/nri (county level)
  - FEMA OpenFEMA          fema.gov/api/open — disaster declarations
  - NOAA CDO               ncei.noaa.gov/cdo-web/api/v2 — storm events + climate normals
  - First Street Foundation api.firststreet.org (optional key)
"""

import csv
import io
import logging
import math
import os
from pathlib import Path
from typing import Optional

import httpx

from agents.realestate._geo import GeoResolution
from schemas.realestate import (
    ClimateRiskSnapshot,
    DemandFactorsSnapshot,
    FloodRiskDetail,
    HousingMarketSnapshot,
)

logger = logging.getLogger(__name__)

# FEMA flood zone descriptions
_FEMA_ZONE_DESC: dict[str, str] = {
    "X":  "Minimal flood hazard (outside 500-year floodplain)",
    "X500": "Moderate flood hazard (500-year floodplain)",
    "AE": "High risk — 1% annual chance flood; Base Flood Elevation established",
    "A":  "High risk — 1% annual chance flood; BFE not determined",
    "AO": "High risk — shallow flooding (sheet flow), depth 1–3 ft",
    "AH": "High risk — shallow flooding (ponding), depth 1–3 ft",
    "AR": "High risk — special flood hazard area with reduced risk from flood control",
    "VE": "Coastal high hazard — 1% annual chance with wave action; BFE established",
    "V":  "Coastal high hazard — 1% annual chance with wave action",
    "D":  "Undetermined flood hazard",
    "SHADED X": "Moderate flood hazard (500-year floodplain)",
}

_SFHA_ZONES = {"AE", "A", "AO", "AH", "AR", "VE", "V", "AE FLOODWAY"}


class HousingAnalystAgent:
    """
    Fetches housing, demand, and climate risk data for a given geography.
    """

    def __init__(
        self,
        zillow_cache_dir: str = "",
        redfin_cache_dir: str = "",
        walk_score_api_key: str = "",
        noaa_cdo_token: str = "",
        first_street_api_key: str = "",
        census_api_key: str = "",
        verbose: bool = False,
    ):
        self.zillow_cache  = zillow_cache_dir
        self.redfin_cache  = redfin_cache_dir
        self.walk_score_key = walk_score_api_key
        self.noaa_token    = noaa_cdo_token
        self.first_street_key = first_street_api_key
        self.census_key    = census_api_key
        self.verbose       = verbose

    def analyze(
        self,
        geo: GeoResolution,
        depth: str = "full",
    ) -> tuple[HousingMarketSnapshot, DemandFactorsSnapshot, Optional[ClimateRiskSnapshot]]:
        """
        Returns (housing_snapshot, demand_snapshot, climate_risk_snapshot).
        climate_risk is None when no address was provided and FEMA API unavailable.
        """
        housing = self._build_housing(geo, depth)
        demand  = self._build_demand(geo, depth)
        climate = self._build_climate_risk(geo, depth) if depth == "full" else None
        return housing, demand, climate

    # ── Housing market ─────────────────────────────────────────────────────────

    def _build_housing(self, geo: GeoResolution, depth: str) -> HousingMarketSnapshot:
        snap = HousingMarketSnapshot()
        sources: list[str] = []

        # Zillow ZHVI / ZORI (from local cache or download)
        zillow = self._fetch_zillow(geo)
        if zillow:
            snap.median_home_price          = zillow.get("zhvi")
            snap.home_price_growth_yoy_pct  = zillow.get("zhvi_yoy")
            snap.median_rent_monthly        = zillow.get("zori")
            snap.rent_growth_yoy_pct        = zillow.get("zori_yoy")
            snap.data_as_of                 = zillow.get("as_of")
            sources.append("Zillow Research")

        # Redfin data (from local cache or download)
        if depth == "full":
            redfin = self._fetch_redfin(geo)
            if redfin:
                snap.days_on_market_median    = redfin.get("median_dom")
                snap.months_supply_inventory  = redfin.get("months_supply")
                snap.list_to_sale_ratio       = redfin.get("list_to_sale")
                if not snap.median_home_price:
                    snap.median_home_price    = redfin.get("median_price")
                if snap.months_supply_inventory is not None:
                    if snap.months_supply_inventory < 3:
                        snap.active_listings_trend = "falling"
                    elif snap.months_supply_inventory > 6:
                        snap.active_listings_trend = "rising"
                    else:
                        snap.active_listings_trend = "stable"
                sources.append("Redfin Data Center")

            # Census building permits
            permits = self._fetch_permits(geo)
            if permits:
                snap.building_permits_yoy_pct    = permits.get("yoy_pct")
                snap.building_permits_per_capita  = permits.get("per_capita")
                sources.append("Census Building Permits")

            # HUD vacancy
            hud = self._fetch_hud_vacancy(geo)
            if hud:
                snap.rental_vacancy_rate = hud.get("rental_vacancy")
                sources.append("HUD")

        # ACS: median income (for price-to-income ratio)
        income = self._fetch_acs_income(geo)
        if income and snap.median_home_price:
            snap.price_to_income_ratio = round(snap.median_home_price / income, 1)
        if income and snap.median_rent_monthly:
            snap.rent_to_income_ratio = round(snap.median_rent_monthly * 12 / income, 2)

        # Supply elasticity heuristic
        if snap.building_permits_yoy_pct is not None and snap.home_price_growth_yoy_pct is not None:
            if snap.building_permits_yoy_pct > 5 and snap.home_price_growth_yoy_pct > 8:
                snap.supply_elasticity = "moderate"
            elif snap.building_permits_yoy_pct < 0:
                snap.supply_elasticity = "constrained"
            else:
                snap.supply_elasticity = "elastic"

        snap.data_sources_used = sources
        snap.summary = self._housing_summary(snap, geo)
        return snap

    def _fetch_zillow(self, geo: GeoResolution) -> dict:
        """
        Try to read Zillow ZHVI + ZORI from local cache.
        If cache is absent, try to download the Metro-level CSV.
        Returns dict with zhvi, zhvi_yoy, zori, zori_yoy, as_of.
        """
        result: dict = {}
        city_key = geo.input_city.lower()

        # Check local cache
        if self.zillow_cache:
            for fname in ["Metro_zhvi_uc_sfrcondo_tier_0.33_0.67_sm_sa_month.csv",
                          "Metro_zori_sm_month.csv"]:
                fpath = Path(self.zillow_cache) / fname
                if fpath.exists():
                    try:
                        data = self._parse_zillow_csv(str(fpath), geo)
                        result.update(data)
                    except Exception as e:
                        logger.debug(f"Zillow cache parse failed {fname}: {e}")

        # Live download of Metro ZHVI (Zillow Research public CSV)
        if "zhvi" not in result:
            try:
                zhvi_url = (
                    "https://files.zillowstatic.com/research/public_csvs/zhvi/"
                    "Metro_zhvi_uc_sfrcondo_tier_0.33_0.67_sm_sa_month.csv"
                )
                with httpx.Client(timeout=30, follow_redirects=True) as client:
                    r = client.get(zhvi_url)
                if r.status_code == 200:
                    data = self._parse_zillow_csv_content(r.text, geo, metric="zhvi")
                    result.update(data)
            except Exception as e:
                logger.debug(f"Zillow ZHVI download failed: {e}")

        # Live download of Metro ZORI
        if "zori" not in result:
            try:
                zori_url = (
                    "https://files.zillowstatic.com/research/public_csvs/zori/"
                    "Metro_zori_uc_sfrcondomfr_sm_month.csv"
                )
                with httpx.Client(timeout=30, follow_redirects=True) as client:
                    r = client.get(zori_url)
                if r.status_code == 200:
                    data = self._parse_zillow_csv_content(r.text, geo, metric="zori")
                    result.update(data)
            except Exception as e:
                logger.debug(f"Zillow ZORI download failed: {e}")

        return result

    def _parse_zillow_csv(self, filepath: str, geo: GeoResolution) -> dict:
        with open(filepath, newline="", encoding="utf-8-sig") as f:
            content = f.read()
        metric = "zhvi" if "zhvi" in filepath.lower() else "zori"
        return self._parse_zillow_csv_content(content, geo, metric)

    def _parse_zillow_csv_content(self, content: str, geo: GeoResolution, metric: str) -> dict:
        """Parse Zillow Metro CSV and find matching row for city."""
        result: dict = {}
        city_lower = geo.input_city.lower()
        state_upper = geo.input_state.upper()

        try:
            reader = csv.DictReader(io.StringIO(content))
            for row in reader:
                region_name = (row.get("RegionName") or row.get("region_name") or "").lower()
                state_name  = (row.get("StateName") or row.get("state_name") or "").upper()

                # Match on city name (partial) and state
                if (city_lower in region_name or
                    (geo.cbsa_name and geo.cbsa_name.split(",")[0].lower() in region_name)):
                    if state_upper and state_name and state_upper not in region_name:
                        if state_upper != state_name[:2] and state_upper not in state_name:
                            continue

                    # Get date columns (last two years of monthly data)
                    date_cols = [k for k in row.keys()
                                 if len(k) == 10 and k.startswith(("20", "19"))]
                    date_cols.sort()
                    if len(date_cols) >= 13:
                        latest_val = self._safe_float(row.get(date_cols[-1]))
                        year_ago   = self._safe_float(row.get(date_cols[-13]))
                        if latest_val:
                            result[metric]            = round(latest_val, 0)
                            result["as_of"]           = date_cols[-1]
                            if year_ago and year_ago > 0:
                                yoy = (latest_val - year_ago) / year_ago
                                result[f"{metric}_yoy"] = round(yoy, 4)
                    break
        except Exception as e:
            logger.debug(f"Zillow CSV parse error: {e}")

        return result

    def _fetch_redfin(self, geo: GeoResolution) -> dict:
        """Redfin Metro Market Tracker CSV."""
        result: dict = {}

        # Check local cache
        if self.redfin_cache:
            fpath = Path(self.redfin_cache) / "redfin_metro_market_tracker.tsv000.gz"
            if fpath.exists():
                try:
                    return self._parse_redfin_file(str(fpath), geo)
                except Exception as e:
                    logger.debug(f"Redfin cache parse failed: {e}")

        # Live download (Redfin public S3)
        try:
            url = (
                "https://redfin-public-data.s3.us-west-2.amazonaws.com/"
                "redfin_market_tracker/redfin_metro_market_tracker.tsv000.gz"
            )
            with httpx.Client(timeout=45, follow_redirects=True) as client:
                r = client.get(url)
            if r.status_code == 200:
                import gzip
                content = gzip.decompress(r.content).decode("utf-8")
                return self._parse_redfin_content(content, geo)
        except Exception as e:
            logger.debug(f"Redfin download failed: {e}")

        return result

    def _parse_redfin_file(self, filepath: str, geo: GeoResolution) -> dict:
        import gzip
        with gzip.open(filepath, "rt", encoding="utf-8") as f:
            content = f.read()
        return self._parse_redfin_content(content, geo)

    def _parse_redfin_content(self, content: str, geo: GeoResolution) -> dict:
        """Parse Redfin Metro TSV — find most recent row for the target metro."""
        result: dict = {}
        city_lower  = geo.input_city.lower()
        state_upper = geo.input_state.upper()

        try:
            reader   = csv.DictReader(io.StringIO(content), delimiter="\t")
            best_row = None
            best_date = ""

            for row in reader:
                region = (row.get("region") or "").lower()
                state  = (row.get("state") or "").upper()
                period = row.get("period_end") or ""

                if state != state_upper:
                    continue
                if city_lower not in region:
                    continue
                if period > best_date:
                    best_date = period
                    best_row  = row

            if best_row:
                result["median_price"]  = self._safe_float(best_row.get("median_sale_price"))
                result["median_dom"]    = self._safe_float(best_row.get("median_days_on_market"))
                result["months_supply"] = self._safe_float(best_row.get("months_of_supply"))
                result["list_to_sale"]  = self._safe_float(best_row.get("avg_sale_to_list"))
                result["as_of"]         = best_date
        except Exception as e:
            logger.debug(f"Redfin content parse error: {e}")

        return result

    def _fetch_permits(self, geo: GeoResolution) -> dict:
        """Census Building Permits Survey — state level YoY change."""
        if not geo.state_fips:
            return {}

        # Census Building Permits API
        try:
            params: dict = {
                "get": "TOTAL_UNITS,STATE",
                "for": f"state:{geo.state_fips}",
            }
            if self.census_key:
                params["key"] = self.census_key

            results: list[dict] = []
            for year in ["2023", "2022"]:
                with httpx.Client(timeout=12) as client:
                    r = client.get(
                        f"https://api.census.gov/data/{year}/eits/bps",
                        params=params,
                    )
                rows = r.json()
                if len(rows) >= 2:
                    header = rows[0]
                    row    = rows[1]
                    d      = dict(zip(header, row))
                    total  = self._safe_float(d.get("TOTAL_UNITS"))
                    if total:
                        results.append({"year": year, "units": total})

            if len(results) >= 2:
                yoy = (results[0]["units"] - results[1]["units"]) / results[1]["units"]
                return {"yoy_pct": round(yoy, 4), "units_latest": results[0]["units"]}
        except Exception as e:
            logger.debug(f"Census permits fetch failed: {e}")

        return {}

    def _fetch_hud_vacancy(self, geo: GeoResolution) -> dict:
        """HUD state vacancy data (simplified)."""
        # HUD publishes comprehensive data via huduser.gov/portal/datasets
        # The programmatic API requires registration; use ACS as proxy
        return self._fetch_acs_vacancy(geo)

    def _fetch_acs_vacancy(self, geo: GeoResolution) -> dict:
        """ACS 1-year rental vacancy rate by state."""
        if not geo.state_fips:
            return {}
        try:
            params: dict = {
                "get": "B25004_002E,B25004_001E",  # vacant for rent, total vacant
                "for": f"state:{geo.state_fips}",
            }
            if self.census_key:
                params["key"] = self.census_key
            with httpx.Client(timeout=10) as client:
                r = client.get("https://api.census.gov/data/2022/acs/acs1", params=params)
            rows = r.json()
            if len(rows) >= 2:
                d = dict(zip(rows[0], rows[1]))
                for_rent = self._safe_float(d.get("B25004_002E"))
                total    = self._safe_float(d.get("B25004_001E"))
                if for_rent and total and total > 0:
                    return {"rental_vacancy": round(for_rent / total * 100, 1)}
        except Exception as e:
            logger.debug(f"ACS vacancy fetch failed: {e}")
        return {}

    def _fetch_acs_income(self, geo: GeoResolution) -> Optional[float]:
        """ACS 1-year median household income — county preferred, state fallback."""
        geo_params = []
        if geo.county_fips and len(geo.county_fips) == 5:
            geo_params.append({
                "for": f"county:{geo.county_fips[2:]}",
                "in":  f"state:{geo.county_fips[:2]}",
            })
        if geo.state_fips:
            geo_params.append({"for": f"state:{geo.state_fips}"})

        for gp in geo_params:
            try:
                params = {"get": "B19013_001E", **gp}
                if self.census_key:
                    params["key"] = self.census_key
                with httpx.Client(timeout=10) as client:
                    r = client.get("https://api.census.gov/data/2022/acs/acs1", params=params)
                rows = r.json()
                if len(rows) >= 2:
                    val = self._safe_float(rows[1][0])
                    if val and val > 0:
                        return val
            except Exception:
                pass
        return None

    # ── Demand / QoL factors ───────────────────────────────────────────────────

    def _build_demand(self, geo: GeoResolution, depth: str) -> DemandFactorsSnapshot:
        snap = DemandFactorsSnapshot()

        # Crime (FBI NIBRS)
        crime = self._fetch_fbi_crime(geo)
        if crime:
            snap.violent_crime_per_100k  = crime.get("violent")
            snap.property_crime_per_100k = crime.get("property")
            snap.crime_trend             = crime.get("trend")

        if depth == "full":
            # Air quality (EPA AQS)
            aqi = self._fetch_epa_aqi(geo)
            if aqi:
                snap.air_quality_index_median = aqi.get("median_aqi")
                snap.pm25_annual_avg          = aqi.get("pm25")

            # Walk Score
            if self.walk_score_key and geo.latitude and geo.longitude:
                ws = self._fetch_walk_score(geo)
                if ws:
                    snap.walkability_score = ws.get("walk")
                    snap.transit_score     = ws.get("transit")

            # NOAA climate normals (Jan/Jul temp)
            climate = self._fetch_noaa_climate_normals(geo)
            if climate:
                snap.avg_jan_temp_f                = climate.get("jan_temp")
                snap.avg_july_temp_f               = climate.get("jul_temp")
                snap.annual_precipitation_inches   = climate.get("precip")

            # ACS demographics
            demo = self._fetch_acs_demographics(geo)
            if demo:
                snap.population_total       = demo.get("population")
                snap.share_age_20_34        = demo.get("share_20_34")
                snap.share_age_65_plus      = demo.get("share_65_plus")
                snap.share_college_educated = demo.get("share_college")
                snap.median_household_income = demo.get("median_income")
                snap.avg_commute_time_minutes = demo.get("commute_time")

        snap.summary = self._demand_summary(snap, geo)
        return snap

    def _fetch_fbi_crime(self, geo: GeoResolution) -> dict:
        """FBI NIBRS/UCR crime estimates via usa.gov API."""
        state = geo.input_state.upper()
        try:
            with httpx.Client(timeout=12) as client:
                r = client.get(
                    "https://api.usa.gov/crime/fbi/cde/estimate/state",
                    params={
                        "state_abbr": state,
                        "variable":   "VIOLENT_CRIME_TOTAL,PROPERTY_CRIME_TOTAL",
                        "from":       "2020",
                        "to":         "2022",
                    },
                )
            data = r.json()
            rows = data.get("results", data if isinstance(data, list) else [])
            if not rows:
                return {}

            # Get most recent year
            sorted_rows = sorted(rows, key=lambda x: x.get("year", 0), reverse=True)
            if len(sorted_rows) >= 1:
                latest = sorted_rows[0]
                pop    = self._safe_float(latest.get("population"))
                v_cnt  = self._safe_float(latest.get("violent_crime_total"))
                p_cnt  = self._safe_float(latest.get("property_crime_total"))

                result: dict = {}
                if v_cnt and pop:
                    result["violent"] = round(v_cnt / pop * 100000, 1)
                if p_cnt and pop:
                    result["property"] = round(p_cnt / pop * 100000, 1)

                # Trend from 2 years ago
                if len(sorted_rows) >= 2:
                    prev    = sorted_rows[-1]
                    prev_v  = self._safe_float(prev.get("violent_crime_total"))
                    prev_p  = self._safe_float(prev.get("population"))
                    if prev_v and prev_p and result.get("violent"):
                        prev_rate = prev_v / prev_p * 100000
                        if result["violent"] < prev_rate * 0.95:
                            result["trend"] = "improving"
                        elif result["violent"] > prev_rate * 1.05:
                            result["trend"] = "worsening"
                        else:
                            result["trend"] = "stable"
                return result
        except Exception as e:
            logger.debug(f"FBI crime fetch failed: {e}")
        return {}

    def _fetch_epa_aqi(self, geo: GeoResolution) -> dict:
        """EPA AQS annual summary by CBSA code."""
        cbsa = geo.cbsa_code
        if not cbsa:
            return {}

        try:
            with httpx.Client(timeout=12) as client:
                r = client.get(
                    "https://aqs.epa.gov/data/api/annualData/byCBSA",
                    params={
                        "email":        "test@aqs.api",  # required placeholder
                        "key":          "test",           # public test key
                        "param":        "88101",          # PM2.5 FRM/FEM
                        "bdate":        "20220101",
                        "edate":        "20221231",
                        "cbsa":         cbsa,
                    },
                )
            data  = r.json()
            rows  = data.get("Data", [])
            if not rows:
                return {}

            pm25_vals = [self._safe_float(row.get("arithmetic_mean")) for row in rows]
            pm25_vals = [v for v in pm25_vals if v is not None]
            if pm25_vals:
                return {"pm25": round(sum(pm25_vals) / len(pm25_vals), 1)}
        except Exception as e:
            logger.debug(f"EPA AQS fetch failed: {e}")
        return {}

    def _fetch_walk_score(self, geo: GeoResolution) -> dict:
        """Walk Score API."""
        if not self.walk_score_key or not geo.latitude or not geo.longitude:
            return {}
        try:
            with httpx.Client(timeout=8) as client:
                r = client.get(
                    "https://api.walkscore.com/score",
                    params={
                        "format":   "json",
                        "address":  f"{geo.input_city}, {geo.input_state}",
                        "lat":      geo.latitude,
                        "lon":      geo.longitude,
                        "transit":  1,
                        "bike":     1,
                        "wsapikey": self.walk_score_key,
                    },
                )
            data = r.json()
            return {
                "walk":    data.get("walkscore"),
                "transit": data.get("transit", {}).get("score") if isinstance(data.get("transit"), dict) else None,
            }
        except Exception as e:
            logger.debug(f"Walk Score fetch failed: {e}")
        return {}

    def _fetch_noaa_climate_normals(self, geo: GeoResolution) -> dict:
        """NOAA CDO API: 1981–2010 climate normals for closest station."""
        if not self.noaa_token:
            # Static lookup for major metros (Jan temp, Jul temp, precip)
            return self._static_climate(geo)

        try:
            lat = geo.latitude or 0
            lon = geo.longitude or 0
            if not lat or not lon:
                return self._static_climate(geo)

            with httpx.Client(timeout=12) as client:
                # Find nearest station with normals
                r = client.get(
                    "https://www.ncei.noaa.gov/cdo-web/api/v2/stations",
                    headers={"token": self.noaa_token},
                    params={
                        "datasetid": "NORMAL_ANN",
                        "extent":    f"{lat-1},{lon-1},{lat+1},{lon+1}",
                        "limit":     1,
                    },
                )
                stations = r.json().get("results", [])
                if not stations:
                    return self._static_climate(geo)
                station_id = stations[0]["id"]

                # Fetch January normal temp
                r2 = client.get(
                    "https://www.ncei.noaa.gov/cdo-web/api/v2/data",
                    headers={"token": self.noaa_token},
                    params={
                        "datasetid":  "NORMAL_MLY",
                        "stationid":  station_id,
                        "datatypeid": "mly-tavg-normal",
                        "startdate":  "2010-01-01",
                        "enddate":    "2010-12-01",
                        "limit":      12,
                    },
                )
                normals = r2.json().get("results", [])
                months  = {n["date"][:7]: self._safe_float(n.get("value")) for n in normals}

                jan_val  = months.get("2010-01")
                jul_val  = months.get("2010-07")
                jan_f    = round(jan_val / 10 * 9/5 + 32, 1) if jan_val else None
                jul_f    = round(jul_val / 10 * 9/5 + 32, 1) if jul_val else None

                return {"jan_temp": jan_f, "jul_temp": jul_f}
        except Exception as e:
            logger.debug(f"NOAA climate normals fetch failed: {e}")
            return self._static_climate(geo)

    def _static_climate(self, geo: GeoResolution) -> dict:
        """Approximate climate normals by state."""
        # (jan_f, jul_f, precip_in)
        _CLIMATE: dict[str, tuple[float, float, float]] = {
            "AK": (12.0, 58.0, 16.0), "AL": (46.0, 81.0, 56.0), "AR": (40.0, 81.0, 50.0),
            "AZ": (53.0, 93.0, 8.0),  "CA": (53.0, 74.0, 20.0), "CO": (28.0, 73.0, 15.0),
            "CT": (27.0, 72.0, 47.0), "DC": (35.0, 78.0, 40.0), "DE": (33.0, 76.0, 45.0),
            "FL": (62.0, 82.0, 52.0), "GA": (43.0, 80.0, 50.0), "HI": (73.0, 80.0, 20.0),
            "ID": (28.0, 75.0, 12.0), "IL": (24.0, 75.0, 38.0), "IN": (27.0, 75.0, 40.0),
            "IA": (17.0, 74.0, 34.0), "KS": (28.0, 80.0, 28.0), "KY": (33.0, 76.0, 46.0),
            "LA": (52.0, 83.0, 60.0), "ME": (19.0, 67.0, 42.0), "MD": (33.0, 76.0, 44.0),
            "MA": (27.0, 72.0, 46.0), "MI": (20.0, 71.0, 32.0), "MN": (13.0, 70.0, 27.0),
            "MS": (46.0, 82.0, 55.0), "MO": (29.0, 78.0, 40.0), "MT": (22.0, 68.0, 14.0),
            "NE": (22.0, 77.0, 24.0), "NV": (36.0, 86.0, 7.0),  "NH": (20.0, 68.0, 44.0),
            "NJ": (31.0, 75.0, 46.0), "NM": (36.0, 80.0, 9.0),  "NY": (26.0, 72.0, 42.0),
            "NC": (40.0, 78.0, 48.0), "ND": (8.0,  70.0, 16.0), "OH": (27.0, 73.0, 38.0),
            "OK": (37.0, 83.0, 36.0), "OR": (40.0, 68.0, 36.0), "PA": (28.0, 73.0, 42.0),
            "RI": (29.0, 72.0, 47.0), "SC": (44.0, 80.0, 48.0), "SD": (14.0, 74.0, 17.0),
            "TN": (38.0, 79.0, 52.0), "TX": (47.0, 85.0, 26.0), "UT": (29.0, 78.0, 12.0),
            "VT": (17.0, 68.0, 40.0), "VA": (36.0, 76.0, 44.0), "WA": (38.0, 66.0, 36.0),
            "WV": (31.0, 72.0, 44.0), "WI": (16.0, 70.0, 32.0), "WY": (22.0, 68.0, 12.0),
        }
        vals = _CLIMATE.get(geo.input_state.upper())
        if vals:
            return {"jan_temp": vals[0], "jul_temp": vals[1], "precip": vals[2]}
        return {}

    def _fetch_acs_demographics(self, geo: GeoResolution) -> dict:
        """ACS 1-year demographic variables."""
        if not geo.state_fips:
            return {}
        geo_clause = {"for": f"state:{geo.state_fips}"}
        if self.census_key:
            geo_clause["key"] = self.census_key
        try:
            variables = "B01003_001E,B19013_001E,B08303_001E"  # pop, income, commute
            params = {"get": variables, **geo_clause}
            with httpx.Client(timeout=10) as client:
                r = client.get("https://api.census.gov/data/2022/acs/acs1", params=params)
            rows = r.json()
            if len(rows) >= 2:
                d      = dict(zip(rows[0], rows[1]))
                pop    = self._safe_float(d.get("B01003_001E"))
                income = self._safe_float(d.get("B19013_001E"))
                commute = self._safe_float(d.get("B08303_001E"))
                result: dict = {}
                if pop:    result["population"]   = int(pop)
                if income: result["median_income"] = income
                if commute and pop:
                    result["commute_time"] = round(commute / pop, 1)
                return result
        except Exception as e:
            logger.debug(f"ACS demographics fetch failed: {e}")
        return {}

    # ── Climate & flood risk ───────────────────────────────────────────────────

    def _build_climate_risk(
        self, geo: GeoResolution, depth: str
    ) -> Optional[ClimateRiskSnapshot]:
        snap = ClimateRiskSnapshot()

        # FEMA National Risk Index (county level) — free REST API
        nri = self._fetch_fema_nri(geo)
        if nri:
            snap.wildfire_risk_score  = nri.get("wildfire_score")
            snap.wildfire_risk_label  = nri.get("wildfire_label")
            snap.hurricane_risk_score = nri.get("hurricane_score")
            snap.hurricane_risk_label = nri.get("hurricane_label")

        # FEMA flood zone (property level — requires lat/lon)
        flood_detail = FloodRiskDetail()
        if geo.latitude and geo.longitude:
            fema_flood = self._fetch_fema_flood_zone(geo.latitude, geo.longitude)
            if fema_flood:
                flood_detail.fema_flood_zone       = fema_flood.get("zone")
                flood_detail.fema_zone_description = _FEMA_ZONE_DESC.get(
                    fema_flood.get("zone", ""), "Unknown zone"
                )
                flood_detail.base_flood_elevation_ft = fema_flood.get("bfe")
                zone = fema_flood.get("zone", "")
                flood_detail.is_sfha = zone.upper() in _SFHA_ZONES or any(
                    zone.upper().startswith(z) for z in _SFHA_ZONES
                )

        # First Street flood factor (if key provided)
        if self.first_street_key and geo.latitude and geo.longitude:
            fs = self._fetch_first_street_flood(geo)
            if fs:
                flood_detail.first_street_flood_factor   = fs.get("flood_factor")
                flood_detail.first_street_30yr_risk_pct  = fs.get("risk_30yr")

        # FEMA OpenFEMA disaster declarations (county level)
        openfema = self._fetch_openfema_disasters(geo)
        if openfema:
            flood_detail.fema_disaster_flood_count_10yr = openfema.get("flood_count")
            snap.fema_total_disaster_declarations_10yr  = openfema.get("total_count")

        snap.flood = flood_detail
        snap.flood_risk_overall = self._classify_flood_risk(flood_detail)

        # NOAA storm events (county level)
        storm = self._fetch_noaa_storm_events(geo)
        if storm:
            snap.noaa_storm_events_annual_avg   = storm.get("events_per_year")
            snap.noaa_storm_damage_annual_avg_usd = storm.get("damage_per_year")

        # Climate normals (already in demand — reuse static)
        climate = self._static_climate(geo)
        snap.avg_jan_temp_f              = climate.get("jan_temp")
        snap.avg_july_temp_f             = climate.get("jul_temp")
        snap.annual_precipitation_inches = climate.get("precip")

        snap.summary = self._climate_summary(snap, flood_detail, geo)
        return snap

    def _fetch_fema_flood_zone(self, lat: float, lon: float) -> dict:
        """
        FEMA NFHL ArcGIS REST query — returns flood zone for a lat/lon point.
        Layer 28 = Flood Hazard Zones.
        """
        try:
            with httpx.Client(timeout=12) as client:
                r = client.get(
                    "https://hazards.fema.gov/gis/nfhl/rest/services/public/NFHL/MapServer/28/query",
                    params={
                        "geometry":     f"{lon},{lat}",
                        "geometryType": "esriGeometryPoint",
                        "inSR":         "4326",
                        "spatialRel":   "esriSpatialRelIntersects",
                        "outFields":    "FLD_ZONE,STATIC_BFE,SFHA_TF",
                        "f":            "json",
                    },
                )
            data     = r.json()
            features = data.get("features", [])
            if features:
                attrs = features[0].get("attributes", {})
                zone  = attrs.get("FLD_ZONE", "")
                bfe   = self._safe_float(attrs.get("STATIC_BFE"))
                return {"zone": zone, "bfe": bfe if bfe and bfe > -9000 else None}
        except Exception as e:
            logger.debug(f"FEMA flood zone query failed: {e}")
        return {}

    def _fetch_fema_nri(self, geo: GeoResolution) -> dict:
        """FEMA National Risk Index REST API — county-level hazard scores."""
        if not geo.county_fips:
            return {}

        try:
            with httpx.Client(timeout=12) as client:
                r = client.get(
                    "https://hazards.fema.gov/nri/rest/api/nriData",
                    params={
                        "countyFips": geo.county_fips,
                        "returnFormat": "json",
                    },
                )
            data     = r.json()
            records  = data.get("records", [data]) if isinstance(data, dict) else data
            if records:
                rec = records[0]
                result: dict = {}
                # NRI scores 0–100; EAL = expected annual loss
                wf_score = self._safe_float(rec.get("WFIR_EALR") or rec.get("wfir_ealr"))
                hu_score = self._safe_float(rec.get("HRCN_EALR") or rec.get("hrcn_ealr"))

                def _label(score: Optional[float]) -> Optional[str]:
                    if score is None:
                        return None
                    if score < 0.1:
                        return "minimal"
                    if score < 1.0:
                        return "low"
                    if score < 5.0:
                        return "moderate"
                    if score < 20.0:
                        return "high"
                    return "very_high"

                if wf_score is not None:
                    result["wildfire_score"] = wf_score
                    result["wildfire_label"] = _label(wf_score)
                if hu_score is not None:
                    result["hurricane_score"] = hu_score
                    result["hurricane_label"] = _label(hu_score)
                return result
        except Exception as e:
            logger.debug(f"FEMA NRI fetch failed: {e}")
        return {}

    def _fetch_openfema_disasters(self, geo: GeoResolution) -> dict:
        """FEMA OpenFEMA disaster declarations — last 10 years by county."""
        if not geo.county_fips or not geo.state_fips:
            return {}

        from datetime import datetime, timedelta
        start_date = (datetime.now() - timedelta(days=3650)).strftime("%Y-%m-%d")
        state_abbr = geo.input_state.upper()

        try:
            with httpx.Client(timeout=12) as client:
                r = client.get(
                    "https://www.fema.gov/api/open/v2/disasterDeclarationsSummaries",
                    params={
                        "state":            state_abbr,
                        "declarationDate":  f"ge({start_date})",
                        "$select":          "disasterNumber,incidentType,declarationDate",
                        "$top":             200,
                        "$format":          "json",
                    },
                )
            data     = r.json()
            records  = data.get("DisasterDeclarationsSummaries", [])

            flood_types  = {"Flood", "Hurricane", "Coastal Storm", "Severe Storm", "Typhoon"}
            flood_count  = sum(1 for r in records if r.get("incidentType") in flood_types)
            total_count  = len(records)

            return {
                "total_count": total_count,
                "flood_count": flood_count,
            }
        except Exception as e:
            logger.debug(f"OpenFEMA disasters fetch failed: {e}")
        return {}

    def _fetch_first_street_flood(self, geo: GeoResolution) -> dict:
        """First Street Foundation Flood Factor API (requires key)."""
        if not self.first_street_key or not geo.latitude or not geo.longitude:
            return {}

        try:
            with httpx.Client(timeout=10) as client:
                r = client.get(
                    "https://api.firststreet.org/v1.0/location/summary",
                    headers={"x-api-key": self.first_street_key},
                    params={
                        "lat": geo.latitude,
                        "lng": geo.longitude,
                    },
                )
            data = r.json()
            flood = data.get("flood", {})
            return {
                "flood_factor": flood.get("flood_factor"),
                "risk_30yr":    flood.get("risk_30") or flood.get("cumulativeRisk30"),
            }
        except Exception as e:
            logger.debug(f"First Street API failed: {e}")
        return {}

    def _fetch_noaa_storm_events(self, geo: GeoResolution) -> dict:
        """NOAA Storm Events database — county annual averages."""
        if not self.noaa_token or not geo.county_fips:
            return {}

        from datetime import datetime
        end_year   = datetime.now().year - 1
        start_year = end_year - 9

        try:
            with httpx.Client(timeout=15) as client:
                r = client.get(
                    "https://www.ncei.noaa.gov/cdo-web/api/v2/data",
                    headers={"token": self.noaa_token},
                    params={
                        "datasetid":   "STORM_EVENTS",
                        "locationid":  f"FIPS:{geo.county_fips}",
                        "startdate":   f"{start_year}-01-01",
                        "enddate":     f"{end_year}-12-31",
                        "datatypeid":  "EVT",
                        "limit":       1000,
                    },
                )
            data   = r.json()
            events = data.get("results", [])
            years  = end_year - start_year + 1
            total_damage = sum(
                self._safe_float(e.get("value")) or 0 for e in events
            )
            return {
                "events_per_year": round(len(events) / years, 1),
                "damage_per_year": round(total_damage / years, 0),
            }
        except Exception as e:
            logger.debug(f"NOAA storm events fetch failed: {e}")
        return {}

    # ── Utility ────────────────────────────────────────────────────────────────

    @staticmethod
    def _safe_float(val) -> Optional[float]:
        if val is None:
            return None
        try:
            return float(str(val).replace(",", "").replace("$", "").strip())
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _classify_flood_risk(detail: FloodRiskDetail) -> str:
        zone = (detail.fema_flood_zone or "").upper()
        if zone.startswith("VE") or zone.startswith("V"):
            return "very_high"
        if zone.startswith("AE") or zone.startswith("A"):
            return "high"
        if zone.startswith("X500") or zone == "SHADED X":
            return "moderate"
        if zone == "X":
            return "minimal"
        if detail.first_street_flood_factor is not None:
            ff = detail.first_street_flood_factor
            if ff >= 8:
                return "very_high"
            if ff >= 6:
                return "high"
            if ff >= 4:
                return "moderate"
            if ff >= 2:
                return "low"
            return "minimal"
        return "low"   # default when zone is unknown

    def _housing_summary(self, snap: HousingMarketSnapshot, geo: GeoResolution) -> str:
        parts = []
        if snap.median_home_price:
            parts.append(f"Median home price ${snap.median_home_price:,.0f}")
        if snap.home_price_growth_yoy_pct is not None:
            parts.append(f"({snap.home_price_growth_yoy_pct:+.1%} YoY)")
        if snap.median_rent_monthly:
            parts.append(f"median rent ${snap.median_rent_monthly:,.0f}/mo")
        if snap.price_to_income_ratio:
            parts.append(f"price/income {snap.price_to_income_ratio:.1f}x")
        if snap.days_on_market_median:
            parts.append(f"DOM {snap.days_on_market_median:.0f} days")
        if snap.supply_elasticity:
            parts.append(f"supply: {snap.supply_elasticity}")
        if parts:
            return f"{geo.input_city}, {geo.input_state}: " + "; ".join(parts) + "."
        return f"Limited housing data available for {geo.input_city}, {geo.input_state}."

    def _demand_summary(self, snap: DemandFactorsSnapshot, geo: GeoResolution) -> str:
        parts = []
        if snap.violent_crime_per_100k:
            parts.append(f"violent crime {snap.violent_crime_per_100k:.0f}/100k")
        if snap.walkability_score:
            parts.append(f"walkability {snap.walkability_score:.0f}/100")
        if snap.avg_jan_temp_f:
            parts.append(f"Jan avg {snap.avg_jan_temp_f:.0f}°F")
        return ", ".join(parts) or "Demand factors partially available."

    def _climate_summary(
        self,
        snap: ClimateRiskSnapshot,
        flood: FloodRiskDetail,
        geo: GeoResolution,
    ) -> str:
        parts = []
        if flood.fema_flood_zone:
            parts.append(f"FEMA flood zone {flood.fema_flood_zone}")
        if flood.first_street_flood_factor:
            parts.append(f"First Street Flood Factor {flood.first_street_flood_factor}/10")
        if snap.wildfire_risk_label:
            parts.append(f"wildfire risk: {snap.wildfire_risk_label}")
        if snap.hurricane_risk_label:
            parts.append(f"hurricane risk: {snap.hurricane_risk_label}")
        if snap.fema_total_disaster_declarations_10yr:
            parts.append(
                f"{snap.fema_total_disaster_declarations_10yr} FEMA disaster declarations (10yr)"
            )
        return f"{geo.input_city}, {geo.input_state} climate: " + "; ".join(parts) + "." if parts else "Climate risk data limited."
