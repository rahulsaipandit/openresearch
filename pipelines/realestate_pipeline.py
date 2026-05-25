"""
Real Estate Research Pipeline

7-node sequential pipeline:
  GeoResolve → DocumentIngestion → MigrationAnalyst →
  EconomicAnalyst+HousingAnalyst (sequential) → Synthesizer →
  [Rental: Underwriter + Regulatory + Neighborhood + RentalSynthesizer]

Returns a RealEstateBrief.

Rental analysis runs automatically when the request includes ANY of:
  bedrooms, bathrooms, sqft, purchase_price

depth="quick":
  - Skips document ingestion
  - Uses static/lookup data only (no live API calls for Zillow, Redfin)
  - Rental nodes run but use HUD FMR + static tables only

depth="full" (default):
  - All nodes
  - Live downloads of Zillow/Redfin CSVs if not cached
  - Census Geocoder lat/lon (for FEMA flood zone + ACS tract)
  - RentCast API if rentcast_api_key provided

All external API calls fail silently — the pipeline always completes.
"""

import logging
from typing import Optional

from agents.api_utils import LLMClient
from agents.realestate._geo import resolve_geo
from agents.realestate.document_ingestion import DocumentIngestionAgent
from agents.realestate.migration_analyst import MigrationAnalystAgent
from agents.realestate.economic_analyst import EconomicAnalystAgent
from agents.realestate.housing_analyst import HousingAnalystAgent
from agents.realestate.synthesizer import RealEstateSynthesizerAgent
from agents.realestate.rental_underwriter import RentalUnderwriterAgent
from agents.realestate.regulatory_analyst import RegulatoryAnalystAgent
from agents.realestate.neighborhood_analyst import NeighborhoodAnalystAgent
from agents.realestate.rental_synthesizer import RentalSynthesizerAgent
from schemas.realestate import RealEstateBrief, RealEstatePipelineInput, DocumentFactsBundle

logger = logging.getLogger(__name__)


class RealEstatePipeline:
    """
    Run the full real estate research pipeline.

    Usage:
        pipeline = RealEstatePipeline.from_config("config.yaml")
        brief = pipeline.run(RealEstatePipelineInput(city="Austin", state="TX"))

    Rental analysis:
        brief = pipeline.run(RealEstatePipelineInput(
            city="Austin", state="TX",
            address="123 Main St, Austin, TX 78701",
            bedrooms=3, bathrooms=2, sqft=1600, purchase_price=450000,
        ))
        # brief.rental_analysis is populated
    """

    def __init__(
        self,
        llm: LLMClient,
        fred_api_key: str = "",
        bea_api_key: str = "",
        census_api_key: str = "",
        walk_score_api_key: str = "",
        noaa_cdo_token: str = "",
        first_street_api_key: str = "",
        rentcast_api_key: str = "",
        zillow_cache_dir: str = "",
        redfin_cache_dir: str = "",
        irs_cache_dir: str = "",
        config_path: str = "config.yaml",
        verbose: bool = True,
    ):
        self.llm         = llm
        self.config_path = config_path
        self.verbose     = verbose

        # ── Market research agents ─────────────────────────────────────────────
        self.doc_agent = DocumentIngestionAgent(llm=llm, config_path=config_path)

        self.migration_agent = MigrationAnalystAgent(
            fred_api_key   = fred_api_key,
            census_api_key = census_api_key,
            irs_cache_dir  = irs_cache_dir,
            verbose        = verbose,
        )
        self.economic_agent = EconomicAnalystAgent(
            fred_api_key   = fred_api_key,
            bea_api_key    = bea_api_key,
            census_api_key = census_api_key,
            verbose        = verbose,
        )
        self.housing_agent = HousingAnalystAgent(
            zillow_cache_dir     = zillow_cache_dir,
            redfin_cache_dir     = redfin_cache_dir,
            walk_score_api_key   = walk_score_api_key,
            noaa_cdo_token       = noaa_cdo_token,
            first_street_api_key = first_street_api_key,
            census_api_key       = census_api_key,
            verbose              = verbose,
        )
        self.synthesizer = RealEstateSynthesizerAgent(llm=llm, verbose=verbose)

        # ── Rental analysis agents ─────────────────────────────────────────────
        self.rental_underwriter   = RentalUnderwriterAgent(
            rentcast_api_key = rentcast_api_key,
            verbose          = verbose,
        )
        self.regulatory_analyst  = RegulatoryAnalystAgent(verbose=verbose)
        self.neighborhood_analyst = NeighborhoodAnalystAgent(
            census_api_key    = census_api_key,
            walk_score_api_key = walk_score_api_key,
            verbose            = verbose,
        )
        self.rental_synthesizer = RentalSynthesizerAgent(llm=llm, verbose=verbose)

    @classmethod
    def from_config(cls, config_path: str = "config.yaml") -> "RealEstatePipeline":
        import yaml
        with open(config_path) as f:
            cfg = yaml.safe_load(f)

        llm = LLMClient.from_config(config_path)
        re_cfg  = cfg.get("real_estate_research", {})
        sources = re_cfg.get("data_sources", {})

        return cls(
            llm                  = llm,
            fred_api_key         = sources.get("fred_api_key", "") or "",
            bea_api_key          = sources.get("bea_api_key", "") or "",
            census_api_key       = sources.get("census_api_key", "") or "",
            walk_score_api_key   = sources.get("walk_score_api_key", "") or "",
            noaa_cdo_token       = sources.get("noaa_cdo_token", "") or "",
            first_street_api_key = sources.get("first_street_api_key", "") or "",
            rentcast_api_key     = sources.get("rentcast_api_key", "") or "",
            zillow_cache_dir     = re_cfg.get("zillow_cache_dir", "") or "",
            redfin_cache_dir     = re_cfg.get("redfin_cache_dir", "") or "",
            irs_cache_dir        = re_cfg.get("irs_cache_dir", "") or "",
            config_path          = config_path,
            verbose              = cfg.get("server", {}).get("verbose", True),
        )

    def _rental_requested(self, request: RealEstatePipelineInput) -> bool:
        """Returns True when enough property data is present to run rental analysis."""
        return bool(
            request.bedrooms is not None
            or request.purchase_price is not None
            or request.bathrooms is not None
        )

    def run(self, request: RealEstatePipelineInput) -> RealEstateBrief:
        city  = request.city.strip()
        state = request.state.strip().upper()
        depth = request.depth
        do_rental = self._rental_requested(request)

        if self.verbose:
            rental_note = " + rental analysis" if do_rental else ""
            print(f"\n[RealEstatePipeline] {city}, {state} (depth={depth}{rental_note})")

        # ── Node 0: Geo resolution ─────────────────────────────────────────────
        if self.verbose:
            print("  [0] Resolving geography (FIPS, CBSA, lat/lon)...")
        geo = resolve_geo(
            city     = city,
            state    = state,
            address  = request.address or "",
            zip_code = request.zip_code,
        )
        if self.verbose:
            cbsa = f" → CBSA {geo.cbsa_code} ({geo.cbsa_name})" if geo.cbsa_code else ""
            print(f"      County: {geo.county_name or 'n/a'}{cbsa}")

        # ── Node 1: Document ingestion ─────────────────────────────────────────
        doc_insights = []
        doc_facts    = DocumentFactsBundle()
        docs_dir = request.documents_dir
        if docs_dir:
            if self.verbose:
                print(f"  [1] Ingesting documents from {docs_dir}...")
            doc_insights, doc_facts = self.doc_agent.ingest(docs_dir, verbose=self.verbose)
            if self.verbose:
                types_found = {ins.document_type for ins in doc_insights}
                print(f"      {len(doc_insights)} document(s) processed. "
                      f"Types: {', '.join(sorted(types_found)) or 'none'}")
                if doc_facts.conflicts:
                    print(f"      ⚠ {len(doc_facts.conflicts)} conflict(s) detected in documents.")
        else:
            if self.verbose:
                print("  [1] Document ingestion skipped (no documents_dir).")

        # ── Node 2: Migration analysis ─────────────────────────────────────────
        if self.verbose:
            print("  [2] Analysing migration signals (city + state)...")
        city_mig, state_mig = self.migration_agent.analyze(geo, depth=depth)
        if self.verbose:
            print(f"      City: {city_mig.net_direction} | State: {state_mig.net_direction}")

        # ── Node 3: Economic (BLS, FRED, BEA, Census) ─────────────────────────
        if self.verbose:
            print("  [3] Fetching labor market + cost-of-living data...")
        labor, col = self.economic_agent.analyze(geo, depth=depth)

        # ── Node 4: Housing + demand + climate ────────────────────────────────
        if self.verbose:
            print("  [4] Fetching housing market + demand + climate risk...")
        housing, demand, climate = self.housing_agent.analyze(geo, depth=depth)
        if self.verbose and climate:
            zone = f" | Flood zone: {climate.flood.fema_flood_zone}" if climate.flood and climate.flood.fema_flood_zone else ""
            print(f"      Flood risk: {climate.flood_risk_overall or 'n/a'}{zone}")

        # ── Node 5: Market synthesis (LLM) ────────────────────────────────────
        if self.verbose:
            print("  [5] Synthesizing market brief (LLM)...")
        brief = self.synthesizer.synthesize(
            geo             = geo,
            city_migration  = city_mig,
            state_migration = state_mig,
            labor           = labor,
            housing         = housing,
            col             = col,
            demand          = demand,
            climate         = climate,
            doc_insights    = doc_insights,
            depth           = depth,
        )

        # ── Nodes 6–9: Rental analysis (when property data provided) ──────────
        if do_rental:
            bedrooms  = request.bedrooms  or 3
            bathrooms = request.bathrooms or 2.0
            sqft      = request.sqft
            prop_type = request.property_type
            yr_built  = request.year_built
            price     = request.purchase_price

            if self.verbose:
                price_note = f"${price:,.0f}" if price else "price unknown"
                print(f"  [6] Rental underwriting ({bedrooms}bd/{bathrooms}ba, {price_note})...")
            underwriting = self.rental_underwriter.underwrite(
                address        = request.address or "",
                state          = state,
                bedrooms       = bedrooms,
                bathrooms      = bathrooms,
                sqft           = sqft,
                property_type  = prop_type,
                year_built     = yr_built,
                purchase_price = price,
                down_payment_pct   = request.down_payment_pct,
                interest_rate_pct  = request.interest_rate_pct,
                loan_term_years    = request.loan_term_years,
                housing        = housing,
                col            = col,
                climate        = climate,
                doc_facts      = doc_facts if doc_facts.source_documents else None,
            )
            if self.verbose:
                cf = underwriting.monthly_cash_flow
                cr = underwriting.cap_rate_pct
                print(f"      Cap rate: {cr:.1f}% | Cash flow: ${cf:+.0f}/mo | "
                      f"DSCR: {underwriting.dscr:.2f}" if cf and cr and underwriting.dscr else
                      "      Financial model partial (missing price or rent data).")

            if self.verbose:
                print("  [7] Regulatory analysis (eviction, rent control, STR)...")
            regulatory = self.regulatory_analyst.analyze(geo=geo, city=city, state=state)
            if self.verbose:
                print(f"      Regulatory risk: {regulatory.overall_regulatory_risk}")

            if self.verbose:
                print("  [8] Neighborhood analysis (ACS, HUD vacancy, Walk Score)...")
            # Reuse walk score from housing agent if already fetched
            walk_score    = demand.walkability_score if demand else None
            transit_score = demand.transit_score     if demand else None
            neighborhood = self.neighborhood_analyst.analyze(
                geo           = geo,
                zip_code      = request.zip_code,
                city          = city,
                state         = state,
                address       = request.address or "",
                depth         = depth,
                walk_score    = walk_score,
                transit_score = transit_score,
            )

            if self.verbose:
                print("  [9] Rental feasibility synthesis (LLM)...")
            rental_analysis = self.rental_synthesizer.synthesize(
                geo           = geo,
                city          = city,
                state         = state,
                bedrooms      = bedrooms,
                bathrooms     = bathrooms,
                sqft          = sqft,
                property_type = prop_type,
                year_built    = yr_built,
                underwriting  = underwriting,
                regulatory    = regulatory,
                neighborhood  = neighborhood,
                city_migration = city_mig,
                labor         = labor,
                housing       = housing,
                col           = col,
                climate       = climate,
            )
            brief.rental_analysis = rental_analysis
            if self.verbose:
                print(f"      Verdict: {rental_analysis.feasibility_verdict}")

        if self.verbose:
            print(
                f"\n[RealEstatePipeline] Complete. "
                f"Verdict: {brief.demand_verdict} | "
                f"Signal: {brief.investment_signal} | "
                f"Confidence: {brief.confidence:.0%}"
                + (f" | Rental: {brief.rental_analysis.feasibility_verdict}" if brief.rental_analysis else "")
            )

        return brief
