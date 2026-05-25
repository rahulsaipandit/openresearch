"""
DocumentIngestionAgent — Node 1 of the real estate research pipeline.

Two-pass per-file processing:
  1. Load each file individually using DocumentLoader.load_file() + ScannedPDFOCR
  2. Per-file LLM call: classify document type + extract type-specific structured facts
  3. Aggregate extracted facts into a DocumentFactsBundle for downstream use

Supported document types and what gets extracted:
  appraisal      → appraised value, condition, effective age, comparable sales
  inspection     → major defects, system conditions, repair cost estimates
  hoa            → monthly fee, rental restrictions, STR ban, reserve fund
  tax_record     → actual annual tax bill, assessed value, homestead exemption
  lease_rent_roll → current rent, lease expiration, tenant info
  flood_cert     → FEMA zone, base flood elevation, actual NFIP premium
  listing_mls    → list price, DOM, price reductions, seller concessions
  cma_comps      → value range, median comp price, market trend
  zoning_permit  → permitted uses, STR zoning status, open permits, violations
  other          → generic key facts only

Extracted facts in DocumentFactsBundle override formula-based estimates in
RentalUnderwriterAgent (e.g. actual tax bill replaces the % estimate).
"""

import json
import logging
from pathlib import Path
from typing import Optional

import yaml

from agents.api_utils import LLMClient
from schemas.realestate import (
    DocumentInsight, DocumentFactsBundle,
    AppraisalExtract, InspectionExtract, HOAExtract, TaxRecordExtract,
    LeaseExtract, FloodCertExtract, ListingExtract, CMAExtract, ZoningExtract,
)

logger = logging.getLogger(__name__)


# ── System prompt ──────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are a real estate document analyst.

Your task: classify a property-related document and extract structured facts.

Document types and what to extract from each:
  appraisal      → appraised_value, appraisal_date, condition_rating, quality_rating,
                   effective_age_years, gross_living_area_sqft, comparable_sales,
                   neighborhood_trend, price_vs_purchase_note
  inspection     → overall_condition, major_defects, safety_issues, deferred_maintenance,
                   estimated_repair_cost_low/high, roof/hvac/foundation/electrical/plumbing
                   condition + age, mold_moisture_noted, pest_damage_noted
  hoa            → monthly_hoa_fee, special_assessments_pending, reserve_fund_pct_funded,
                   rental_restrictions, rental_cap_pct, str_prohibited,
                   minimum_rental_term_days, litigation_noted
  tax_record     → actual_annual_tax, assessed_value, tax_rate_pct, tax_year,
                   homestead_exemption_applied, homestead_exemption_savings,
                   special_assessments
  lease_rent_roll → current_monthly_rent, gross_annual_rent_roll, unit_count,
                   lease_expiration_date, month_to_month, rent_increase_clause,
                   tenant_pays_utilities
  flood_cert     → fema_flood_zone, base_flood_elevation_ft, property_elevation_ft,
                   nfip_required, actual_nfip_premium
  listing_mls    → list_price, original_list_price, price_per_sqft, days_on_market,
                   price_reduction_count, seller_concessions, hoa_fee_per_listing,
                   taxes_per_listing
  cma_comps      → subject_value_estimate_low/high, median_comp_price,
                   median_comp_price_per_sqft, avg_days_on_market, market_trend,
                   comps_summary
  zoning_permit  → zoning_classification, permitted_uses, str_permitted_by_zoning,
                   open_permits, violations_noted
  other          → generic facts only

Rules:
- Return ONLY valid JSON — no markdown fences, no prose.
- Use null for fields not present in the document.
- All monetary values in USD (no $ signs in JSON, just numbers).
- Dates as ISO strings "YYYY-MM-DD" when possible.
- Confidence 0.9–1.0 = obvious; 0.7–0.9 = likely; 0.5–0.7 = uncertain.
"""

# ── Per-document extraction schema ────────────────────────────────────────────

EXTRACTION_SCHEMA = """{
  "document_type": "<appraisal|inspection|hoa|tax_record|lease_rent_roll|flood_cert|listing_mls|cma_comps|zoning_permit|other>",
  "classification_confidence": 0.0,
  "key_facts": ["<most important facts — max 5>"],
  "property_mentions": ["<specific property references — address, sq ft, bed/bath, valuation>"],
  "market_mentions": ["<market conditions — comp sales, trends, inventory>"],
  "conflicts": ["<any conflict between this document and expected data, e.g. 'Appraised $420k but contract price is $465k'>"],

  "appraisal": null,
  "inspection": null,
  "hoa": null,
  "tax_record": null,
  "lease": null,
  "flood_cert": null,
  "listing": null,
  "cma": null,
  "zoning": null
}

IMPORTANT: Only ONE type-specific object should be non-null.
Set the matching object's fields; leave all others as null.

Example for an appraisal document:
{
  "document_type": "appraisal",
  "classification_confidence": 0.95,
  "key_facts": ["Appraised value $485,000 as of Jan 2025", "Condition C3 — Average"],
  ...
  "appraisal": {
    "appraised_value": 485000,
    "appraisal_date": "2025-01-15",
    "condition_rating": "C3 — Average",
    ...
  },
  "inspection": null,
  ...
}"""


class DocumentIngestionAgent:
    """
    Classifies and extracts structured data from property documents.

    Returns (list[DocumentInsight], DocumentFactsBundle).
    Pass documents_dir=None to skip; returns ([], empty bundle).
    """

    def __init__(self, llm: LLMClient, config_path: str = "config.yaml"):
        self.llm         = llm
        self.config_path = config_path

    def ingest(
        self,
        documents_dir: Optional[str],
        verbose: bool = False,
    ) -> tuple[list[DocumentInsight], DocumentFactsBundle]:

        empty_bundle = DocumentFactsBundle()

        if not documents_dir:
            return [], empty_bundle

        doc_path = Path(documents_dir)
        if not doc_path.exists():
            logger.warning(f"DocumentIngestionAgent: directory not found: {documents_dir}")
            return [], empty_bundle

        # ── Set up document loader + optional OCR ─────────────────────────────
        try:
            from integrations.documents import DocumentLoader
            ocr = None
            try:
                with open(self.config_path) as f:
                    _cfg = yaml.safe_load(f)
                if _cfg.get("ocr", {}).get("enabled", True):
                    from integrations.ocr import ScannedPDFOCR
                    ocr = ScannedPDFOCR.from_config(self.config_path)
            except Exception:
                pass

            loader = DocumentLoader(str(doc_path), ocr=ocr)
        except Exception as e:
            logger.warning(f"DocumentLoader setup failed: {e}")
            return [], empty_bundle

        # ── Enumerate files ────────────────────────────────────────────────────
        supported_exts = {".pdf", ".docx", ".md", ".txt"}
        files = [
            f for f in sorted(doc_path.iterdir())
            if f.is_file() and f.suffix.lower() in supported_exts
        ]
        if not files:
            logger.info("DocumentIngestionAgent: no supported files found.")
            return [], empty_bundle

        if verbose:
            logger.info(f"DocumentIngestionAgent: processing {len(files)} file(s)...")

        # ── Process each file ──────────────────────────────────────────────────
        insights: list[DocumentInsight] = []

        for fpath in files:
            insight = self._process_file(fpath, loader, verbose=verbose)
            if insight:
                insights.append(insight)

        # ── Aggregate into DocumentFactsBundle ────────────────────────────────
        bundle = self._aggregate(insights)

        if verbose:
            logger.info(
                f"DocumentIngestionAgent: {len(insights)} document(s) classified. "
                f"Bundle: appraised_value={bundle.appraised_value}, "
                f"tax={bundle.actual_annual_property_tax}, "
                f"rent={bundle.current_monthly_rent}, "
                f"hoa={bundle.monthly_hoa_fee}"
            )

        return insights, bundle

    # ── Per-file processing ────────────────────────────────────────────────────

    def _process_file(
        self,
        fpath: Path,
        loader,
        verbose: bool = False,
    ) -> Optional[DocumentInsight]:
        """Load a single file, classify it, and extract structured facts."""

        # ── Load text ──────────────────────────────────────────────────────────
        try:
            raw_text = loader.load_file(str(fpath))
        except Exception as e:
            logger.warning(f"  {fpath.name}: load failed ({e})")
            return None

        if not raw_text or len(raw_text.strip()) < 30:
            logger.info(f"  {fpath.name}: empty or too short, skipping.")
            return None

        # Determine file_type for the schema
        ext = fpath.suffix.lower()
        file_type_map = {".pdf": "pdf_text", ".docx": "docx", ".md": "markdown", ".txt": "txt"}
        file_type = file_type_map.get(ext, "txt")

        # Cap text at 8000 chars per file to stay within token budget
        text_excerpt = raw_text[:8000]

        # ── LLM: classify + extract ────────────────────────────────────────────
        user_msg = (
            f"Document filename: {fpath.name}\n"
            f"Document text ({len(raw_text):,} chars total, first 8000 shown):\n\n"
            f"{text_excerpt}\n\n"
            f"Classify this document and extract structured facts.\n"
            f"Return ONLY JSON matching this schema:\n\n{EXTRACTION_SCHEMA}"
        )

        try:
            raw_json = self.llm.create(
                system   = SYSTEM_PROMPT,
                messages = [{"role": "user", "content": user_msg}],
                max_tokens = 1200,
            )
            data = json.loads(raw_json.strip())
        except (json.JSONDecodeError, Exception) as e:
            logger.warning(f"  {fpath.name}: LLM extraction failed ({e})")
            # Return minimal insight with raw key facts
            return DocumentInsight(
                source_file              = fpath.name,
                file_type                = file_type,    # type: ignore
                document_type            = "other",
                classification_confidence = 0.0,
                key_facts                = [f"Raw text available ({len(raw_text):,} chars); LLM parse failed."],
            )

        if verbose:
            logger.info(
                f"  {fpath.name}: classified as '{data.get('document_type', 'other')}' "
                f"(confidence {data.get('classification_confidence', 0):.0%})"
            )

        # ── Build DocumentInsight ──────────────────────────────────────────────
        doc_type = data.get("document_type", "other")
        insight = DocumentInsight(
            source_file               = fpath.name,
            file_type                 = file_type,    # type: ignore
            document_type             = doc_type,
            classification_confidence = float(data.get("classification_confidence", 0.0)),
            key_facts                 = data.get("key_facts", []),
            property_mentions         = data.get("property_mentions", []),
            market_mentions           = data.get("market_mentions", []),
            conflicts                 = data.get("conflicts", []),
        )

        # ── Populate type-specific extract ─────────────────────────────────────
        _extract_dispatch = {
            "appraisal":      ("appraisal",   AppraisalExtract,  "appraisal"),
            "inspection":     ("inspection",  InspectionExtract, "inspection"),
            "hoa":            ("hoa",         HOAExtract,        "hoa"),
            "tax_record":     ("tax_record",  TaxRecordExtract,  "tax_record"),
            "lease_rent_roll":("lease",       LeaseExtract,      "lease"),
            "flood_cert":     ("flood_cert",  FloodCertExtract,  "flood_cert"),
            "listing_mls":    ("listing",     ListingExtract,    "listing"),
            "cma_comps":      ("cma",         CMAExtract,        "cma"),
            "zoning_permit":  ("zoning",      ZoningExtract,     "zoning"),
        }

        dispatch = _extract_dispatch.get(doc_type)
        if dispatch:
            json_key, model_cls, insight_attr = dispatch
            raw_extract = data.get(json_key)
            if raw_extract and isinstance(raw_extract, dict):
                try:
                    setattr(insight, insight_attr, model_cls(**raw_extract))
                except Exception as e:
                    logger.debug(f"  {fpath.name}: {json_key} parse failed: {e}")

        return insight

    # ── Bundle aggregation ─────────────────────────────────────────────────────

    def _aggregate(self, insights: list[DocumentInsight]) -> DocumentFactsBundle:
        """
        Merge type-specific extracts across all documents into one bundle.
        When the same fact appears in multiple documents, prefer the
        higher-confidence source (e.g. flood cert > appraisal for FEMA zone).
        """
        bundle = DocumentFactsBundle()

        for ins in insights:
            bundle.source_documents.append(ins.source_file)

            # ── Appraisal ──────────────────────────────────────────────────────
            if ins.appraisal:
                a = ins.appraisal
                bundle.appraised_value = _prefer(bundle.appraised_value, a.appraised_value)

            # ── Inspection ─────────────────────────────────────────────────────
            if ins.inspection:
                i = ins.inspection
                # Take highest repair estimate for conservatism
                if i.estimated_repair_cost_low is not None:
                    bundle.estimated_repair_cost_low = _prefer_max(
                        bundle.estimated_repair_cost_low, i.estimated_repair_cost_low
                    )
                if i.estimated_repair_cost_high is not None:
                    bundle.estimated_repair_cost_high = _prefer_max(
                        bundle.estimated_repair_cost_high, i.estimated_repair_cost_high
                    )
                if i.major_defects:
                    bundle.major_defects_summary.extend(i.major_defects)

            # ── HOA ────────────────────────────────────────────────────────────
            if ins.hoa:
                h = ins.hoa
                bundle.monthly_hoa_fee       = _prefer(bundle.monthly_hoa_fee, h.monthly_hoa_fee)
                bundle.hoa_rental_restrictions = _prefer(bundle.hoa_rental_restrictions, h.rental_restrictions)
                bundle.hoa_str_prohibited    = _prefer(bundle.hoa_str_prohibited, h.str_prohibited)
                bundle.hoa_minimum_rental_term_days = _prefer(
                    bundle.hoa_minimum_rental_term_days, h.minimum_rental_term_days
                )

            # ── Tax record ─────────────────────────────────────────────────────
            if ins.tax_record:
                t = ins.tax_record
                bundle.actual_annual_property_tax = _prefer(
                    bundle.actual_annual_property_tax, t.actual_annual_tax
                )
                if t.homestead_exemption_applied:
                    savings = t.homestead_exemption_savings or 0
                    bundle.homestead_exemption_note = (
                        f"Homestead exemption currently applied (saves ~${savings:,.0f}/yr). "
                        "This exemption is lost when property is rented — actual tax will be higher."
                    )

            # ── Lease ──────────────────────────────────────────────────────────
            if ins.lease:
                l = ins.lease
                bundle.current_monthly_rent   = _prefer(bundle.current_monthly_rent, l.current_monthly_rent)
                bundle.lease_expiration_date  = _prefer(bundle.lease_expiration_date, l.lease_expiration_date)
                bundle.gross_annual_rent_roll = _prefer(bundle.gross_annual_rent_roll, l.gross_annual_rent_roll)

            # ── Flood cert ─────────────────────────────────────────────────────
            if ins.flood_cert:
                f = ins.flood_cert
                bundle.fema_zone_confirmed = _prefer(bundle.fema_zone_confirmed, f.fema_flood_zone)
                bundle.actual_nfip_premium = _prefer(bundle.actual_nfip_premium, f.actual_nfip_premium)

            # ── Listing ────────────────────────────────────────────────────────
            if ins.listing:
                li = ins.listing
                bundle.list_price     = _prefer(bundle.list_price, li.list_price)
                bundle.days_on_market = _prefer(bundle.days_on_market, li.days_on_market)

            # ── CMA ────────────────────────────────────────────────────────────
            if ins.cma:
                c = ins.cma
                bundle.cma_value_low  = _prefer(bundle.cma_value_low,  c.subject_value_estimate_low)
                bundle.cma_value_high = _prefer(bundle.cma_value_high, c.subject_value_estimate_high)

            # ── Zoning ─────────────────────────────────────────────────────────
            if ins.zoning:
                z = ins.zoning
                bundle.str_permitted_by_zoning = _prefer(
                    bundle.str_permitted_by_zoning, z.str_permitted_by_zoning
                )
                if z.open_permits:
                    bundle.open_permits.extend(z.open_permits)
                if z.violations_noted:
                    bundle.violations.extend(z.violations_noted)

            # ── Cross-document conflicts ───────────────────────────────────────
            if ins.conflicts:
                bundle.conflicts.extend(ins.conflicts)

        # ── Post-aggregation conflict detection ───────────────────────────────
        _detect_bundle_conflicts(bundle)

        return bundle


# ── Helpers ────────────────────────────────────────────────────────────────────

def _prefer(existing, new):
    """Use existing value if already set; otherwise use new."""
    return existing if existing is not None else new


def _prefer_max(existing, new):
    """For costs/risks, keep the higher value."""
    if existing is None:
        return new
    if new is None:
        return existing
    return max(existing, new)


def _detect_bundle_conflicts(bundle: DocumentFactsBundle) -> None:
    """Flag obvious cross-document conflicts."""
    if bundle.appraised_value and bundle.list_price:
        diff_pct = (bundle.list_price - bundle.appraised_value) / bundle.appraised_value * 100
        if abs(diff_pct) > 8:
            direction = "above" if diff_pct > 0 else "below"
            bundle.conflicts.append(
                f"List price ${bundle.list_price:,.0f} is {abs(diff_pct):.1f}% "
                f"{direction} appraised value ${bundle.appraised_value:,.0f}."
            )

    if bundle.cma_value_high and bundle.list_price:
        if bundle.list_price > bundle.cma_value_high * 1.05:
            bundle.conflicts.append(
                f"List price ${bundle.list_price:,.0f} exceeds CMA high estimate "
                f"${bundle.cma_value_high:,.0f} — potential overprice."
            )

    if bundle.fema_zone_confirmed and bundle.actual_nfip_premium is None:
        sfha_zones = {"A", "AE", "AO", "AH", "V", "VE"}
        if any(bundle.fema_zone_confirmed.upper().startswith(z) for z in sfha_zones):
            bundle.conflicts.append(
                f"FEMA zone {bundle.fema_zone_confirmed} (SFHA) confirmed in documents "
                "but no NFIP premium quoted — obtain a flood insurance quote before closing."
            )

    if bundle.major_defects_summary:
        bundle.conflicts.append(
            f"Inspection flagged {len(bundle.major_defects_summary)} major defect(s): "
            + "; ".join(bundle.major_defects_summary[:3])
            + ("..." if len(bundle.major_defects_summary) > 3 else "")
        )
