"""
Geo resolution helper — city/state/zip/address → FIPS + CBSA + lat/lon.

Resolution order:
  1. Census Geocoder API (free, no key)
  2. Lookup table of top-100 US metros (offline fallback)

All external calls fail silently — callers get a partially-filled
GeoResolution and must handle None fields gracefully.
"""

import logging
from typing import Optional

import httpx

from schemas.realestate import GeoResolution

logger = logging.getLogger(__name__)

# ── Static lookup: city → (state_fips, county_fips, cbsa_code, cbsa_name) ─────
# Covers the 60 most-searched US metros. Used when geocoder is unavailable.
_METRO_LOOKUP: dict[tuple[str, str], tuple[str, str, str, str]] = {
    # (city_lower, state_upper): (state_fips, county_fips, cbsa_code, cbsa_name)
    ("austin",          "TX"): ("48", "48453", "12420", "Austin-Round Rock-Georgetown, TX"),
    ("dallas",          "TX"): ("48", "48113", "19100", "Dallas-Fort Worth-Arlington, TX"),
    ("houston",         "TX"): ("48", "48201", "26420", "Houston-The Woodlands-Sugar Land, TX"),
    ("san antonio",     "TX"): ("48", "48029", "41700", "San Antonio-New Braunfels, TX"),
    ("new york",        "NY"): ("36", "36061", "35620", "New York-Newark-Jersey City, NY-NJ-PA"),
    ("los angeles",     "CA"): ("06", "06037", "31080", "Los Angeles-Long Beach-Anaheim, CA"),
    ("chicago",         "IL"): ("17", "17031", "16980", "Chicago-Naperville-Elgin, IL-IN-WI"),
    ("phoenix",         "AZ"): ("04", "04013", "38060", "Phoenix-Mesa-Chandler, AZ"),
    ("philadelphia",    "PA"): ("42", "42101", "37980", "Philadelphia-Camden-Wilmington, PA-NJ-DE-MD"),
    ("san antonio",     "TX"): ("48", "48029", "41700", "San Antonio-New Braunfels, TX"),
    ("san diego",       "CA"): ("06", "06073", "41740", "San Diego-Chula Vista-Carlsbad, CA"),
    ("dallas",          "TX"): ("48", "48113", "19100", "Dallas-Fort Worth-Arlington, TX"),
    ("san jose",        "CA"): ("06", "06085", "41940", "San Jose-Sunnyvale-Santa Clara, CA"),
    ("austin",          "TX"): ("48", "48453", "12420", "Austin-Round Rock-Georgetown, TX"),
    ("jacksonville",    "FL"): ("12", "12031", "27260", "Jacksonville, FL"),
    ("fort worth",      "TX"): ("48", "48121", "19100", "Dallas-Fort Worth-Arlington, TX"),
    ("columbus",        "OH"): ("39", "39049", "18140", "Columbus, OH"),
    ("charlotte",       "NC"): ("37", "37119", "16740", "Charlotte-Concord-Gastonia, NC-SC"),
    ("san francisco",   "CA"): ("06", "06075", "41860", "San Francisco-Oakland-Berkeley, CA"),
    ("indianapolis",    "IN"): ("18", "18097", "26900", "Indianapolis-Carmel-Anderson, IN"),
    ("seattle",         "WA"): ("53", "53033", "42660", "Seattle-Tacoma-Bellevue, WA"),
    ("denver",          "CO"): ("08", "08031", "19740", "Denver-Aurora-Lakewood, CO"),
    ("nashville",       "TN"): ("47", "47037", "34980", "Nashville-Davidson-Murfreesboro-Franklin, TN"),
    ("oklahoma city",   "OK"): ("40", "40109", "36420", "Oklahoma City, OK"),
    ("el paso",         "TX"): ("48", "48141", "21340", "El Paso, TX"),
    ("washington",      "DC"): ("11", "11001", "47900", "Washington-Arlington-Alexandria, DC-VA-MD-WV"),
    ("las vegas",       "NV"): ("32", "32003", "29820", "Las Vegas-Henderson-Paradise, NV"),
    ("louisville",      "KY"): ("21", "21111", "31140", "Louisville/Jefferson County, KY-IN"),
    ("memphis",         "TN"): ("47", "47157", "32820", "Memphis, TN-MS-AR"),
    ("baltimore",       "MD"): ("24", "24510", "12580", "Baltimore-Columbia-Towson, MD"),
    ("milwaukee",       "WI"): ("55", "55079", "33340", "Milwaukee-Waukesha, WI"),
    ("albuquerque",     "NM"): ("35", "35001", "10740", "Albuquerque, NM"),
    ("tucson",          "AZ"): ("04", "04019", "46060", "Tucson, AZ"),
    ("fresno",          "CA"): ("06", "06019", "23420", "Fresno, CA"),
    ("sacramento",      "CA"): ("06", "06067", "40900", "Sacramento-Roseville-Folsom, CA"),
    ("mesa",            "AZ"): ("04", "04013", "38060", "Phoenix-Mesa-Chandler, AZ"),
    ("kansas city",     "MO"): ("29", "29095", "28140", "Kansas City, MO-KS"),
    ("atlanta",         "GA"): ("13", "13121", "12060", "Atlanta-Sandy Springs-Alpharetta, GA"),
    ("omaha",           "NE"): ("31", "31055", "36540", "Omaha-Council Bluffs, NE-IA"),
    ("colorado springs","CO"): ("08", "08041", "17820", "Colorado Springs, CO"),
    ("raleigh",         "NC"): ("37", "37183", "39580", "Raleigh-Cary, NC"),
    ("long beach",      "CA"): ("06", "06037", "31080", "Los Angeles-Long Beach-Anaheim, CA"),
    ("virginia beach",  "VA"): ("51", "51810", "47260", "Virginia Beach-Norfolk-Newport News, VA-NC"),
    ("minneapolis",     "MN"): ("27", "27053", "33460", "Minneapolis-St. Paul-Bloomington, MN-WI"),
    ("tampa",           "FL"): ("12", "12057", "45300", "Tampa-St. Petersburg-Clearwater, FL"),
    ("new orleans",     "LA"): ("22", "22071", "35380", "New Orleans-Metairie, LA"),
    ("portland",        "OR"): ("41", "41051", "38900", "Portland-Vancouver-Hillsboro, OR-WA"),
    ("st. louis",       "MO"): ("29", "29189", "41180", "St. Louis, MO-IL"),
    ("riverside",       "CA"): ("06", "06065", "40140", "Riverside-San Bernardino-Ontario, CA"),
    ("miami",           "FL"): ("12", "12086", "33100", "Miami-Fort Lauderdale-Pompano Beach, FL"),
    ("orlando",         "FL"): ("12", "12095", "36740", "Orlando-Kissimmee-Sanford, FL"),
    ("pittsburgh",      "PA"): ("42", "42003", "38300", "Pittsburgh, PA"),
    ("cincinnati",      "OH"): ("39", "39061", "17140", "Cincinnati, OH-KY-IN"),
    ("cleveland",       "OH"): ("39", "39035", "17460", "Cleveland-Elyria, OH"),
    ("detroit",         "MI"): ("26", "26163", "19820", "Detroit-Warren-Dearborn, MI"),
    ("boston",          "MA"): ("25", "25025", "14460", "Boston-Cambridge-Newton, MA-NH"),
    ("salt lake city",  "UT"): ("49", "49035", "41620", "Salt Lake City, UT"),
    ("richmond",        "VA"): ("51", "51760", "40060", "Richmond, VA"),
    ("hartford",        "CT"): ("09", "09003", "25540", "Hartford-East Hartford-Middletown, CT"),
    ("buffalo",         "NY"): ("36", "36029", "15380", "Buffalo-Cheektowaga, NY"),
    ("rochester",       "NY"): ("36", "36055", "40380", "Rochester, NY"),
    ("birmingham",      "AL"): ("01", "01073", "13820", "Birmingham-Hoover, AL"),
    ("boise",           "ID"): ("16", "16001", "14260", "Boise City, ID"),
    ("spokane",         "WA"): ("53", "53063", "44060", "Spokane-Spokane Valley, WA"),
    ("bakersfield",     "CA"): ("06", "06029", "12540", "Bakersfield, CA"),
    ("des moines",      "IA"): ("19", "19153", "20780", "Des Moines-West Des Moines, IA"),
    ("madison",         "WI"): ("55", "55025", "31540", "Madison, WI"),
    ("green bay",       "WI"): ("55", "55009", "24580", "Green Bay, WI"),
    ("cape coral",      "FL"): ("12", "12071", "15980", "Cape Coral-Fort Myers, FL"),
    ("lakewood",        "CO"): ("08", "08059", "19740", "Denver-Aurora-Lakewood, CO"),
    ("aurora",          "CO"): ("08", "08005", "19740", "Denver-Aurora-Lakewood, CO"),
    ("henderson",       "NV"): ("32", "32003", "29820", "Las Vegas-Henderson-Paradise, NV"),
    ("scottsdale",      "AZ"): ("04", "04013", "38060", "Phoenix-Mesa-Chandler, AZ"),
    ("gilbert",         "AZ"): ("04", "04013", "38060", "Phoenix-Mesa-Chandler, AZ"),
    ("chandler",        "AZ"): ("04", "04013", "38060", "Phoenix-Mesa-Chandler, AZ"),
    ("plano",           "TX"): ("48", "48085", "19100", "Dallas-Fort Worth-Arlington, TX"),
    ("durham",          "NC"): ("37", "37063", "20500", "Durham-Chapel Hill, NC"),
}

# State abbreviation → FIPS
_STATE_FIPS: dict[str, str] = {
    "AL": "01", "AK": "02", "AZ": "04", "AR": "05", "CA": "06",
    "CO": "08", "CT": "09", "DE": "10", "FL": "12", "GA": "13",
    "HI": "15", "ID": "16", "IL": "17", "IN": "18", "IA": "19",
    "KS": "20", "KY": "21", "LA": "22", "ME": "23", "MD": "24",
    "MA": "25", "MI": "26", "MN": "27", "MS": "28", "MO": "29",
    "MT": "30", "NE": "31", "NV": "32", "NH": "33", "NJ": "34",
    "NM": "35", "NY": "36", "NC": "37", "ND": "38", "OH": "39",
    "OK": "40", "OR": "41", "PA": "42", "RI": "44", "SC": "45",
    "SD": "46", "TN": "47", "TX": "48", "UT": "49", "VT": "50",
    "VA": "51", "WA": "53", "WV": "54", "WI": "55", "WY": "56",
    "DC": "11",
}


def resolve_geo(
    city: str,
    state: str,
    address: str = "",
    zip_code: Optional[str] = None,
) -> GeoResolution:
    """
    Resolve city/state (and optionally address) to FIPS + CBSA + lat/lon.

    Tries Census Geocoder first; falls back to lookup table.
    Never raises — returns a partial GeoResolution on failure.
    """
    city_clean  = city.strip()
    state_upper = state.strip().upper()
    geo = GeoResolution(
        input_city=city_clean,
        input_state=state_upper,
        input_zip=zip_code,
        input_address=address if address else None,
        state_fips=_STATE_FIPS.get(state_upper),
    )

    # 1. Try lookup table first (instant, no network)
    key = (city_clean.lower(), state_upper)
    if key in _METRO_LOOKUP:
        sfips, cfips, cbsa, cbsa_name = _METRO_LOOKUP[key]
        geo.state_fips   = sfips
        geo.county_fips  = cfips
        geo.cbsa_code    = cbsa
        geo.cbsa_name    = cbsa_name
        geo.resolution_method = "lookup_table"
        logger.debug(f"Geo resolved via lookup: {city_clean}, {state_upper} → CBSA {cbsa}")

    # 2. Census Geocoder for lat/lon (and county FIPS if not in lookup)
    try:
        query = address if address else f"{city_clean}, {state_upper}"
        if zip_code:
            query += f" {zip_code}"
        with httpx.Client(timeout=8) as client:
            r = client.get(
                "https://geocoding.geo.census.gov/geocoder/geographies/onelineaddress",
                params={
                    "address":   query,
                    "benchmark": "Public_AR_Current",
                    "vintage":   "Current_Current",
                    "layers":    "Counties",
                    "format":    "json",
                },
            )
        data = r.json()
        matches = data.get("result", {}).get("addressMatches", [])
        if matches:
            m = matches[0]
            coords = m.get("coordinates", {})
            geo.latitude  = coords.get("y")
            geo.longitude = coords.get("x")
            # Extract county FIPS from geographies
            geos = m.get("geographies", {})
            counties = geos.get("Counties", [])
            if counties:
                c = counties[0]
                geo.county_fips = c.get("GEOID", "")     # 5-digit
                geo.county_name = c.get("NAME", "")
                if not geo.state_fips:
                    geo.state_fips = c.get("STATE", "")
            if geo.resolution_method == "unknown":
                geo.resolution_method = "geocoder"
            else:
                geo.resolution_method = "lookup_table+geocoder"
    except Exception as e:
        logger.debug(f"Census Geocoder failed for '{city_clean}, {state_upper}': {e}")

    return geo
