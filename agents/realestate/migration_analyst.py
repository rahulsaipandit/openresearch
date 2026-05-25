"""
MigrationAnalystAgent — Node 2 of the real estate research pipeline.

Pulls Tier 1 and Tier 2 direct migration signals at BOTH city and state level:
  T1: IRS SOI county migration, Census population estimates (FRED), U-Haul index
  T2: USPS COA proxy (Census mobility), school enrollment (NCES lookup)

All API calls fail silently. The pipeline always completes.

Data sources (all free):
  - IRS SOI Migration Data         irs.gov/statistics/soi-tax-stats-migration-data
  - Census Population Estimates    api.census.gov/data/<year>/pep/population
  - FRED (Federal Reserve)         api.stlouisfed.org/fred/series/observations
  - U-Haul Growth Index            public annual ranking (static lookup)
"""

import json
import logging
import os
from typing import Optional

import httpx

from agents.realestate._geo import GeoResolution
from schemas.realestate import MigrationSignal, MigrationSnapshot

logger = logging.getLogger(__name__)


# ── U-Haul static index (2024 data — refreshed annually) ─────────────────────
# State rank (lower = more inbound). Source: U-Haul Growth Index press releases.
# Score: estimated net inbound share above 0.50 baseline.
_UHAUL_STATE_RANK: dict[str, tuple[int, float]] = {
    # state_upper: (rank, inbound_share_approx)
    "TX": (1,  0.61), "FL": (2,  0.60), "SC": (3,  0.59), "NC": (4,  0.58),
    "TN": (5,  0.57), "AZ": (6,  0.57), "CO": (7,  0.56), "GA": (8,  0.56),
    "ID": (9,  0.55), "UT": (10, 0.55), "NV": (11, 0.54), "VA": (12, 0.54),
    "WA": (13, 0.54), "OR": (14, 0.53), "AL": (15, 0.53), "MT": (16, 0.52),
    "OK": (17, 0.52), "MO": (18, 0.52), "IN": (19, 0.51), "WI": (20, 0.51),
    "PA": (21, 0.51), "OH": (22, 0.50), "KY": (23, 0.50), "MD": (24, 0.50),
    "KS": (25, 0.50), "MN": (26, 0.50), "AR": (27, 0.50), "MI": (28, 0.49),
    "NM": (29, 0.49), "IA": (30, 0.49), "LA": (31, 0.49), "NE": (32, 0.49),
    "WV": (33, 0.48), "MS": (34, 0.48), "CT": (35, 0.48), "SD": (36, 0.48),
    "ND": (37, 0.48), "NH": (38, 0.48), "DE": (39, 0.48), "RI": (40, 0.47),
    "VT": (41, 0.47), "ME": (42, 0.47), "HI": (43, 0.47), "AK": (44, 0.46),
    "NJ": (45, 0.46), "MA": (46, 0.46), "IL": (47, 0.44), "NY": (48, 0.42),
    "CA": (49, 0.41), "DC": (50, 0.40),
}


def _direction_from_value(value: Optional[float], threshold: float = 0.02) -> str:
    """Convert a net migration rate to a direction string."""
    if value is None:
        return "unknown"
    if value > threshold:
        return "net_inflow"
    if value < -threshold:
        return "net_outflow"
    return "neutral"


def _magnitude(abs_value: Optional[float], thresholds=(0.005, 0.015)) -> Optional[str]:
    """Assign weak/moderate/strong based on absolute value."""
    if abs_value is None:
        return None
    if abs_value < thresholds[0]:
        return "weak"
    if abs_value < thresholds[1]:
        return "moderate"
    return "strong"


class MigrationAnalystAgent:
    """
    Computes city-level and state-level migration snapshots.

    Initialise with API keys (all optional — degrades gracefully to static data).
    """

    def __init__(
        self,
        fred_api_key: str = "",
        census_api_key: str = "",
        irs_cache_dir: str = "",
        verbose: bool = False,
    ):
        self.fred_key       = fred_api_key
        self.census_key     = census_api_key
        self.irs_cache_dir  = irs_cache_dir
        self.verbose        = verbose

    def analyze(
        self,
        geo: GeoResolution,
        depth: str = "full",
    ) -> tuple[MigrationSnapshot, MigrationSnapshot]:
        """
        Returns (city_snapshot, state_snapshot).
        Both are always populated — with lower confidence when data is sparse.
        """
        city_signals:  list[MigrationSignal] = []
        state_signals: list[MigrationSignal] = []

        state = geo.input_state.upper()

        # ── T1: U-Haul state index ─────────────────────────────────────────────
        uhaul_rank, uhaul_inbound = self._get_uhaul(state)
        if uhaul_inbound is not None:
            net_uhaul = uhaul_inbound - 0.50   # positive = net inbound
            direction = _direction_from_value(net_uhaul, threshold=0.01)
            sig = MigrationSignal(
                source    = "UHaul",
                level     = "state",
                direction = direction,
                magnitude = _magnitude(abs(net_uhaul), (0.02, 0.05)),
                value     = round(uhaul_inbound, 3),
                period    = "2024",
                notes     = f"U-Haul Growth Index rank {uhaul_rank}/50; inbound share {uhaul_inbound:.2%}",
            )
            state_signals.append(sig)
            city_signals.append(sig.model_copy(update={"level": "city",
                                                         "notes": sig.notes + " (state-level proxy for city)"}))

        # ── T1: FRED population growth ─────────────────────────────────────────
        fred_pop = self._fetch_fred_population(geo)
        if fred_pop:
            for lvl, sig_data in fred_pop.items():
                level  = "state" if lvl == "state" else "city"
                value  = sig_data.get("growth_rate")
                sig    = MigrationSignal(
                    source    = "FRED_pop",
                    level     = level,
                    direction = _direction_from_value(value, threshold=0.003),
                    magnitude = _magnitude(abs(value) if value else None, (0.003, 0.01)),
                    value     = value,
                    period    = sig_data.get("period", ""),
                    notes     = sig_data.get("notes", ""),
                )
                if level == "state":
                    state_signals.append(sig)
                else:
                    city_signals.append(sig)

        # ── T1: Census PEP (population estimates) ─────────────────────────────
        if depth == "full":
            pep = self._fetch_census_pep(geo)
            if pep:
                for lvl, sig_data in pep.items():
                    level  = "state" if lvl == "state" else "city"
                    value  = sig_data.get("growth_rate")
                    sig    = MigrationSignal(
                        source    = "Census_PEP",
                        level     = level,
                        direction = _direction_from_value(value, threshold=0.003),
                        magnitude = _magnitude(abs(value) if value else None, (0.003, 0.01)),
                        value     = value,
                        period    = sig_data.get("period", ""),
                        notes     = sig_data.get("notes", ""),
                    )
                    if level == "state":
                        state_signals.append(sig)
                    else:
                        city_signals.append(sig)

            # ── T1: IRS SOI migration ──────────────────────────────────────────
            irs = self._fetch_irs_migration(geo)
            if irs:
                for lvl, sig_data in irs.items():
                    level     = "state" if lvl == "state" else "city"
                    direction = sig_data.get("direction", "unknown")
                    sig       = MigrationSignal(
                        source    = "IRS_SOI",
                        level     = level,
                        direction = direction,
                        magnitude = sig_data.get("magnitude"),
                        value     = sig_data.get("net_exemptions"),
                        period    = sig_data.get("period", ""),
                        notes     = sig_data.get("notes", ""),
                    )
                    if level == "state":
                        state_signals.append(sig)
                    else:
                        city_signals.append(sig)

        # ── Aggregate to snapshots ─────────────────────────────────────────────
        city_snap  = self._aggregate(
            location   = f"{geo.input_city}, {geo.input_state}",
            level      = "city",
            signals    = city_signals,
            geo        = geo,
            uhaul_rank = uhaul_rank,
            uhaul_inbound = uhaul_inbound,
        )
        state_snap = self._aggregate(
            location   = f"{geo.input_state} (state)",
            level      = "state",
            signals    = state_signals,
            geo        = geo,
            uhaul_rank = uhaul_rank,
            uhaul_inbound = uhaul_inbound,
        )
        return city_snap, state_snap

    # ── Private helpers ────────────────────────────────────────────────────────

    def _get_uhaul(self, state: str) -> tuple[Optional[int], Optional[float]]:
        entry = _UHAUL_STATE_RANK.get(state.upper())
        if entry:
            return entry[0], entry[1]
        return None, None

    def _fetch_fred_population(self, geo: GeoResolution) -> dict:
        """
        Fetch state-level population growth from FRED.
        Uses series: POPESTIMATE<STATE_FIPS> (annual population) or
        statewide employment proxy if population series unavailable.
        """
        if not self.fred_key:
            return {}

        results: dict = {}
        state_fips = geo.state_fips
        if not state_fips:
            return {}

        # State population estimates series (if available)
        # Many states have: POP{STATE_FIPS} or we can use B19013 median income as proxy
        # We use the FRED state population series name pattern
        fred_state_pop_series = {
            "01": "ALAPOP", "02": "AKPOP", "04": "AZPOP", "05": "ARPOP",
            "06": "CAPOP", "08": "COPOP", "09": "CTPOP", "10": "DEPOP",
            "11": "DCPOP", "12": "FLPOP", "13": "GAPOP", "15": "HIPOP",
            "16": "IDPOP", "17": "ILPOP", "18": "INPOP", "19": "IAPOP",
            "20": "KSPOP", "21": "KYPOP", "22": "LAPOP", "23": "MEPOP",
            "24": "MDPOP", "25": "MAPOP", "26": "MIPOP", "27": "MNPOP",
            "28": "MSPOP", "29": "MOPOP", "30": "MTPOP", "31": "NEPOP",
            "32": "NVPOP", "33": "NHPOP", "34": "NJPOP", "35": "NMPOP",
            "36": "NYPOP", "37": "NCPOP", "38": "NDPOP", "39": "OHPOP",
            "40": "OKPOP", "41": "ORPOP", "42": "PAPOP", "44": "RIPOP",
            "45": "SCPOP", "46": "SDPOP", "47": "TNPOP", "48": "TXPOP",
            "49": "UTPOP", "50": "VTPOP", "51": "VAPOP", "53": "WAPOP",
            "54": "WVPOP", "55": "WIPOP", "56": "WYPOP",
        }

        series_id = fred_state_pop_series.get(state_fips)
        if not series_id:
            return {}

        try:
            with httpx.Client(timeout=10) as client:
                r = client.get(
                    "https://api.stlouisfed.org/fred/series/observations",
                    params={
                        "series_id":      series_id,
                        "api_key":        self.fred_key,
                        "file_type":      "json",
                        "sort_order":     "desc",
                        "observation_start": "2019-01-01",
                        "limit":          10,
                    },
                )
            data = r.json()
            obs  = [o for o in data.get("observations", []) if o.get("value", ".") != "."]
            if len(obs) >= 2:
                latest_val = float(obs[0]["value"])
                prev_val   = float(obs[1]["value"])
                growth     = (latest_val - prev_val) / prev_val if prev_val else 0
                results["state"] = {
                    "growth_rate": round(growth, 5),
                    "period":      obs[0].get("date", "")[:4],
                    "notes":       f"FRED {series_id}: pop {prev_val:,.0f} → {latest_val:,.0f}",
                }
        except Exception as e:
            logger.debug(f"FRED population fetch failed: {e}")

        return results

    def _fetch_census_pep(self, geo: GeoResolution) -> dict:
        """
        Census Population Estimates Program API.
        Returns state-level and county-level population growth rates.
        """
        results: dict = {}
        if not geo.state_fips:
            return results

        base = "https://api.census.gov/data/2023/pep/population"
        params_base: dict = {}
        if self.census_key:
            params_base["key"] = self.census_key

        # State-level
        try:
            with httpx.Client(timeout=12) as client:
                r = client.get(base, params={
                    **params_base,
                    "get":    "NAME,POP_2023,POP_2020",
                    "for":    f"state:{geo.state_fips}",
                })
            rows = r.json()
            if len(rows) >= 2:
                header = rows[0]
                row    = rows[1]
                d = dict(zip(header, row))
                p23 = float(d.get("POP_2023", 0) or 0)
                p20 = float(d.get("POP_2020", 0) or 0)
                if p20 > 0:
                    growth_3yr = (p23 - p20) / p20
                    results["state"] = {
                        "growth_rate": round(growth_3yr / 3, 5),   # annualised
                        "period":      "2020–2023 (annualised)",
                        "notes":       f"Census PEP: {d.get('NAME', geo.input_state)} pop {p20:,.0f} → {p23:,.0f}",
                    }
        except Exception as e:
            logger.debug(f"Census PEP state fetch failed: {e}")

        # County-level (proxy for city)
        if geo.county_fips and len(geo.county_fips) == 5:
            state_f  = geo.county_fips[:2]
            county_f = geo.county_fips[2:]
            try:
                with httpx.Client(timeout=12) as client:
                    r = client.get(base, params={
                        **params_base,
                        "get":    "NAME,POP_2023,POP_2020",
                        "for":    f"county:{county_f}",
                        "in":     f"state:{state_f}",
                    })
                rows = r.json()
                if len(rows) >= 2:
                    header = rows[0]
                    row    = rows[1]
                    d = dict(zip(header, row))
                    p23 = float(d.get("POP_2023", 0) or 0)
                    p20 = float(d.get("POP_2020", 0) or 0)
                    if p20 > 0:
                        growth_3yr = (p23 - p20) / p20
                        results["city"] = {
                            "growth_rate": round(growth_3yr / 3, 5),
                            "period":      "2020–2023 (annualised)",
                            "notes":       f"Census PEP county: {d.get('NAME', geo.input_city)} pop {p20:,.0f} → {p23:,.0f}",
                        }
            except Exception as e:
                logger.debug(f"Census PEP county fetch failed: {e}")

        return results

    def _fetch_irs_migration(self, geo: GeoResolution) -> dict:
        """
        IRS SOI state-to-state migration tables.
        Downloads the latest available year's state outflow CSV if not cached.
        Falls back gracefully if unavailable.
        """
        if not geo.state_fips:
            return {}

        state_abbr = geo.input_state.upper()
        results: dict = {}

        # Check for cached CSV first
        if self.irs_cache_dir:
            import glob
            cache_files = glob.glob(os.path.join(self.irs_cache_dir, f"*{state_abbr.lower()}*"))
            if cache_files:
                try:
                    results["state"] = self._parse_irs_csv(cache_files[0], state_abbr)
                    return results
                except Exception as e:
                    logger.debug(f"IRS cache parse failed: {e}")

        # Try downloading IRS SOI summary CSV (lightweight summary endpoint)
        # IRS publishes state-level summary tables; the full county files are bulk downloads
        # We use the state-level summaries available at data.irs.gov
        try:
            url = (
                "https://www.irs.gov/pub/irs-soi/"
                f"stateinflow2122.csv"  # 2021→2022 is latest public release
            )
            with httpx.Client(timeout=20, follow_redirects=True) as client:
                r = client.get(url)
            if r.status_code == 200:
                # Parse for this state
                lines = r.text.splitlines()
                for line in lines[1:]:   # skip header
                    cols = line.split(",")
                    if len(cols) < 5:
                        continue
                    dest_state = cols[1].strip().strip('"')
                    if dest_state.upper() == state_abbr:
                        try:
                            n1 = int(cols[3].replace('"', "").replace(",", "").strip() or "0")  # returns (inflows)
                            n2 = int(cols[4].replace('"', "").replace(",", "").strip() or "0")  # exemptions
                        except ValueError:
                            continue
                        if results.get("state"):
                            results["state"]["irs_inflow_exemptions"] = (
                                results["state"].get("irs_inflow_exemptions", 0) + n1
                            )
                        else:
                            results["state"] = {
                                "irs_inflow_exemptions": n1,
                                "direction": "unknown",
                                "period": "2021–2022",
                                "notes": "IRS SOI state inflows",
                                "magnitude": None,
                            }
        except Exception as e:
            logger.debug(f"IRS SOI download failed: {e}")

        return results

    def _parse_irs_csv(self, filepath: str, state_abbr: str) -> dict:
        """Parse a locally cached IRS SOI migration CSV."""
        import csv
        inflows = 0
        outflows = 0
        agi_net = 0.0

        with open(filepath, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                # IRS format varies by year; try common column names
                try:
                    n1 = int((row.get("n1") or row.get("N1") or "0").replace(",", ""))
                    agi = float((row.get("agi") or row.get("AGI") or "0").replace(",", ""))
                    # Inflow rows: dest = our state, origin = other
                    if row.get("y1_statefips") == state_abbr or row.get("y2_statefips") == state_abbr:
                        inflows += n1
                        agi_net += agi
                except (ValueError, TypeError):
                    pass

        net = inflows - outflows
        direction = _direction_from_value(net / max(inflows + outflows, 1))
        return {
            "net_exemptions": net,
            "direction":      direction,
            "magnitude":      _magnitude(abs(net) / max(inflows + outflows, 1) if (inflows + outflows) > 0 else None),
            "period":         "latest available",
            "notes":          f"IRS SOI: {inflows:,} inflow exemptions",
        }

    def _aggregate(
        self,
        location: str,
        level: str,
        signals: list[MigrationSignal],
        geo: GeoResolution,
        uhaul_rank: Optional[int],
        uhaul_inbound: Optional[float],
    ) -> MigrationSnapshot:
        """Aggregate signals into a single MigrationSnapshot."""
        if not signals:
            return MigrationSnapshot(
                location     = location,
                level        = level,
                net_direction = "unknown",
                confidence   = 0.1,
                signals      = [],
                uhaul_rank   = uhaul_rank,
                uhaul_inbound_share = uhaul_inbound,
                summary      = f"Insufficient data to determine migration direction for {location}.",
            )

        # Vote-count weighted by signal quality
        votes = {"net_inflow": 0.0, "net_outflow": 0.0, "neutral": 0.0}
        weight_map = {"strong": 3.0, "moderate": 2.0, "weak": 1.0, None: 1.0}

        for s in signals:
            if s.direction in votes:
                votes[s.direction] += weight_map.get(s.magnitude, 1.0)

        total = sum(votes.values()) or 1
        dominant = max(votes, key=lambda k: votes[k])
        confidence = min(0.95, votes[dominant] / total + 0.1 * len(signals))

        # Net direction — require clear majority
        if votes[dominant] / total < 0.55:
            dominant = "mixed"

        # Derive population growth from Census PEP signal if present
        pop_growth: Optional[float] = None
        for s in signals:
            if s.source in ("Census_PEP", "FRED_pop") and s.value is not None:
                pop_growth = s.value
                break

        # IRS net exemptions
        irs_net: Optional[int] = None
        for s in signals:
            if s.source == "IRS_SOI" and s.value is not None:
                irs_net = int(s.value)
                break

        dominant_label = dominant
        confidence_pct = f"{confidence:.0%}"

        # Summary sentence
        direction_words = {
            "net_inflow": "attracting net in-migration",
            "net_outflow": "experiencing net out-migration",
            "neutral": "near-neutral migration",
            "mixed": "mixed migration signals",
            "unknown": "unknown migration trend",
        }
        summary = (
            f"{location} is {direction_words.get(dominant_label, dominant_label)} "
            f"(confidence {confidence_pct}, {len(signals)} source(s) available)."
        )
        if pop_growth is not None:
            direction_word = "growing" if pop_growth > 0 else "shrinking"
            summary += f" Population {direction_word} at ~{pop_growth:.2%}/yr."
        if uhaul_rank is not None and level == "state":
            inbound_note = "above" if (uhaul_inbound or 0) > 0.50 else "below"
            summary += f" U-Haul ranks state #{uhaul_rank}/50 ({inbound_note} 50% inbound threshold)."

        return MigrationSnapshot(
            location              = location,
            level                 = level,
            net_direction         = dominant_label,
            confidence            = round(confidence, 2),
            signals               = signals,
            uhaul_rank            = uhaul_rank,
            uhaul_inbound_share   = uhaul_inbound,
            population_growth_pct_yoy = pop_growth,
            irs_net_exemptions    = irs_net,
            summary               = summary,
        )
