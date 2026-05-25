# Rental Property Analysis: Human Workflow & System Design
Also, check out - MetaClassifier.md - Self-Generating Classification System

## How a Human Analyzes a Rental Property (Address + Price in Hand)

Here's the typical workflow — roughly in order:

### 1. Quick Gut-Check (5 min)

- **Gross Rent Multiplier**: Search Zillow/Rentometer for the area's typical rent. Divide price by (monthly rent × 12). Below 10 = great, 10–15 = decent, 15+ = tough pencil.
- **1% Rule thumb**: Does monthly rent ≥ 1% of purchase price? ($300k → needs $3k/mo rent). Many markets fail this now, but it's a quick filter.
- **Price per sq ft vs. comps**: Is this priced at market, below, or premium?

### 2. Comparable Rents ("What can I actually charge?")

- Pull actives on Zillow/Craigslist for similar beds/baths/sqft within 0.5–1 mile
- Check Rentometer, RentCast, or Apartments.com for the zip code's median
- Note vacancy: are units sitting 60 days or renting in a week? That's demand signal.

### 3. Run the Operating Numbers

Write down every real expense — people undercount here:

- Property tax (call the county assessor or look up the actual tax bill)
- Insurance (landlord policy, not homeowner — typically 15–25% more; get a quote)
- NFIP/flood insurance if the zone is A or V (can be $1k–$5k+/yr)
- Vacancy: budget 5–8% (one month empty per year)
- Management: 8–10% of rent if using a PM company (or your time if self-managing)
- Maintenance: 1% of property value/year for older homes, 0.5% for newer
- CapEx reserves: roof, HVAC, water heater — budget 0.5–1% of value/yr
- HOA fees if applicable

### 4. Calculate NOI and Cap Rate

- NOI = annual gross rent − all operating expenses (no mortgage)
- Cap rate = NOI / purchase price × 100

Target: ≥ 6% in growth markets, ≥ 7–8% in stable markets. Below 4–5% means you're counting on appreciation.

### 5. Run the Financing

- Down payment (20–25% for investment property) → loan amount
- Monthly mortgage at today's rate (use a mortgage calculator)
- Annual debt service = monthly × 12
- DSCR = NOI / debt service — lenders want ≥ 1.25; if below 1.0, property doesn't cover its mortgage

### 6. Cash Flow and Cash-on-Cash Return

- Annual cash flow = NOI − debt service
- Cash-on-cash = annual cash flow / total cash invested (down + closing + repairs)

Target: ≥ 6–8% CoC. Negative cash flow = you're paying to own it (speculation play).

### 7. Legal and Regulatory Check

- Eviction laws: Google "[state] eviction timeline" — some states take 30 days, others 6–12 months
- Rent control: Is the city or county rent-controlled? New York, LA, SF, Portland, Seattle have strict rules
- Short-term rentals: Airbnb allowed? City permit required? Primary residence only?
- Landlord licensing: Some cities require a rental license and annual inspections

### 8. Neighborhood Deep Dive

- Schools: GreatSchools rating → affects tenant quality and appreciation
- Crime: SpotCrime, NeighborhoodScout — look for trend, not just absolute
- Who rents here?: Owner-occupancy rate (Census) — low OO% = established rental market
- Job base: What are people working? One major employer = concentration risk

### 9. Flood and Climate Risk

- FEMA flood map (msc.fema.gov): Is it zone X (safe), AE (100-yr floodplain), or VE (coastal)? AE/VE = mandatory flood insurance if mortgaged
- Fire risk: CalFire / USFS maps for CA; FEMA NRI for other states
- Insurance market: Is this a state where insurers are pulling out? (FL, CA, LA right now)

### 10. Property-Level Due Diligence (after offer accepted)

- Full inspection: roof, foundation, HVAC, electrical, plumbing
- Title search: any liens, easements, encroachments?
- Survey if rural or lot lines unclear
- Environmental: oil tanks, mold, lead paint (pre-1978)
- Property management interview: what does a good PM say rents for?

### 11. Stress Testing

- What if vacancy runs 15% instead of 5%?
- What if rent growth is flat for 3 years?
- What if rates rise and you need to refi?
- What if a major repair hits year 2?

**Decision: Buy/Pass**

Most investors want: positive cash flow + ≥ 6% CoC + DSCR ≥ 1.25 + favorable regulatory environment. Any two out of three can be a buy if the neighborhood trajectory is strong.

## System Implementation

Our implementation covers all of this — steps 1–9 are automated via a pipeline of deterministic + LLM agents. Steps 10–11 surface in `recommended_actions`.

### Core Files
- `schemas/realestate.py` — All Pydantic snapshots (`RentalUnderwritingSnapshot`, `RegulatoryRiskSnapshot`, `NeighborhoodSnapshot`, `DocumentFactsBundle`, ...) and the final `RealEstateBrief`
- `agents/realestate/`
  - `rental_underwriter.py` — Zero-LLM financial engine (RentCast / ZORI / HUD FMR, full expense model, mortgage math, verdicts, DSCR, CoC, break-even)
  - `regulatory_analyst.py` — 50-state tables for eviction timelines/friendliness, rent control preemption + city rules, STR (Airbnb) regulations, insurance market stress, just-cause and licensing flags. Computes overall regulatory risk tier.
  - `neighborhood_analyst.py` — Census ACS 5yr (tract income, owner-occ %, education), HUD USPS ZIP vacancy, optional WalkScore/Transit. Infers rental demand signal + neighborhood trajectory (appreciating/stable/declining).
  - `rental_synthesizer.py` — LLM node that ingests the three rental snapshots + market context and emits a concise narrative verdict, pros/cons bullets, and prioritized `recommended_actions`.
  - `document_ingestion.py` — (optional upstream node) Per-file classification + structured extraction from appraisals, tax bills, rent rolls, inspections, etc. Produces `DocumentFactsBundle` used to ground the underwriter.
- `pipelines/realestate_pipeline.py` — Orchestrates the full research flow (GeoResolve → optional docs → parallel market analysts → rental quartet → synthesis) returning a `RealEstateBrief`.

See the modules themselves for detailed docstrings, edge-case handling, and fallback logic.

### Rent Estimation Priority (RentalUnderwriterAgent)
1. RentCast API (`/avm/rent/property`) — property-specific, most accurate — requires `rentcast_api_key`
2. HUD Fair Market Rents (county-level by bedroom count, FY2024 tables) — free, no key
3. Metro median rent from `HousingMarketSnapshot` (Zillow ZORI) as fallback

### Key Metrics & Verdicts Produced
- Income ratios: gross rent yield, GRM, price-to-rent ratio
- Full operating expenses (tax at effective rate, base insurance + NFIP if in SFHA, vacancy allowance, mgmt fee, maintenance, CapEx reserve)
- NOI, cap rate
- Financed: down payment, loan amount, monthly/annual P&I (standard amortization), cash flow (annual + monthly), cash-on-cash return, DSCR, break-even occupancy
- Verdicts: `cash_flow_verdict` (positive/marginal/negative), `cap_rate_pct`, regulatory risk tier, neighborhood trajectory, final synthesized recommendation

### Document Ingestion (Optional but Powerful)

Supported document types and extracted facts (used to override model estimates):

- Appraisal → appraised_value, effective date
- Tax bill → actual_annual_property_tax, assessed_value, exemptions
- Rent roll / leases → current_rent, lease expirations, tenant quality signals
- Inspection → major defects + repair cost estimates → bumps maintenance/CapEx
- HOA docs → monthly fees, special assessments
- Flood cert / elevation → confirms SFHA status for NFIP
- Environmental / zoning → additional risk flags

The bundle also performs automatic conflict detection (list price vs appraisal >8%, etc.).

## Configuration & API Keys
Optional keys improve precision (all calls fail gracefully):
- `rentcast_api_key`
- Census API key (for tract-level ACS)
- Walk Score API key

## Decision Criteria (Default Targets)

Buy/strong interest if:
- Positive or marginal cash flow
- CoC ≥ 6–8%
- DSCR ≥ 1.25
- Cap rate ≥ 6% (growth) / 7–8% (stable)
- Regulatory risk not "very_high"
- Neighborhood trajectory not "declining"

Any two of the financial three + good location trajectory can still be a buy.

---

## How are the documents that are dropped classified?
On Document Classification and Analysis
The DocumentIngestionAgent already extracts structured facts from documents, but you're right — it doesn't classify documents by type first before analyzing them. Right now it just lumps everything together and asks the LLM to figure out what's what.

Here's what I'd recommend, and I can implement it:

Document Types in a Rental Property Context
When you share documents about a property, they fall into a few distinct categories that require different extraction lenses:

| Document Type                        | Key Data to Extract                                                               | Affects                                     |
| ------------------------------------ | --------------------------------------------------------------------------------- | ------------------------------------------- |
| Appraisal report                     | Appraised value, comp sales, adjustments, effective age, condition                | Purchase price validation, underwriting     |
| Home inspection report               | Systems condition, defects, estimated repairs, life expectancy                    | CapEx reserves, negotiation leverage        |
| HOA docs (CC&Rs, financials)         | Monthly dues, special assessments, rental restrictions, pet rules, reserve fund % | Cash flow, regulatory risk, STR eligibility |
| Property tax records                 | Current assessed value, mill rate, actual annual tax bill                         | Expense accuracy (better than % estimate)   |
| Rent roll / leases                   | Current rent, lease expiration dates, tenant payment history                      | Rent validation, vacancy, inherited tenants |
| Flood determination / elevation cert | FEMA zone, base flood elevation, actual flood insurance cost                      | NFIP requirement, insurance expense         |
| Listing / MLS sheet                  | Price, price history, days on market, seller concessions                          | Negotiation context                         |
| Comparable sales (CMA)               | Recent sales, price/sqft, adjustments                                             | Market value validation                     |
| Environmental report (Phase I)       | USTs, contamination risk, prior use                                               | Risk flag                                   |
| Zoning / permit records              | Allowed uses, violations, open permits                                            | Legal risk, STR eligibility                 |


## What I'd Build
The upgraded document ingestion would:
1> **Classify** each document into one of the types above
2> **Extract type-specific fields** (e.g., for an inspection: major defects + estimated repair costs; for a lease: rent + expiration + tenant name)
3> **Feed those structured facts directly into the financial model** (e.g., actual tax bill replaces the estimated tax; actual rent roll replaces the ZORI estimate)
4> **Surface conflicts** (e.g., "appraisal says $420k but you offered $465k — 10.7% premium")
Now we have to upgrade the document ingestion agent to support this type-aware classification and structured extraction? It would make the pipeline significantly more accurate when you have property documents on hand.

## DocumentLoader has a load_file() method — exactly what I need for per-file processing. Now I'll build the full type-aware system:

__Plan__:
Add typed extraction schemas (AppraisalExtract, InspectionExtract, HOAExtract, etc.)
Rewrite DocumentIngestionAgent — classify + extract per file in one LLM call
Add DocumentFactsBundle to carry document-derived facts to underwriting
Update RentalUnderwriterAgent to prefer document facts over estimates
Wire it through the pipeline

Edit d:\Github\openresearch\schemas\realestate.py
Now rewrite the document ingestion agent with per-file classification + type-specific extraction:

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

# Test DocumentInsight with a typed extract
ins = DocumentInsight(
    source_file='appraisal.pdf',
    file_type='pdf_text',
    document_type='appraisal',
    classification_confidence=0.95,
    key_facts=['Appraised value \$485,000'],
    appraisal=AppraisalExtract(appraised_value=485000, condition_rating='C3'),
)
print('DocumentInsight:', ins.document_type, ins.appraisal.appraised_value)

What's New: Document Classification + Analysis
9 Document Types, Each with Targeted Extraction
| Type              | Extracted Fields                                                             | Feeds Into                                                                            |
| ----------------- | ---------------------------------------------------------------------------- | ------------------------------------------------------------------------------------- |
| Appraisal         | Appraised value, condition rating, comp sales, effective age                 | `estimated_market_value`, conflict detection vs. list price                           |
| Inspection        | Major defects, system conditions (roof/HVAC/plumbing age), repair cost range | CapEx reserve (bumped to 2% if defects found), conflict flag                          |
| HOA               | Monthly fee, rental restrictions, STR prohibition, reserve fund %            | Annual expenses, regulatory flags on rental                                           |
| Tax Record        | Actual annual tax bill, assessed value, homestead exemption                  | Replaces the 1.1% estimate with the real number; warns if homestead exemption applies |
| Flood Certificate | FEMA zone confirmed, base flood elevation, actual NFIP premium               | Replaces estimated NFIP premium with actual quoted figure                             |
| Lease / Rent Roll | Current rent, lease expiration, unit count                                   | Replaces ZORI/HUD FMR estimate — in-place rent is the most accurate figure            |
| Listing / MLS     | List price, original price, DOM, price reductions, seller concessions        | Conflict detection vs. appraisal/CMA                                                  |
| CMA / Comps       | Value range, median comp price, market trend                                 | Cross-check vs. list price                                                            |
| Zoning / Permits  | Zoning class, STR by zoning, open permits, violations                        | Regulatory risk, STR eligibility                                                      |


## Data Hierarchy (Most Accurate Wins)
Rent:           lease doc > RentCast API > Zillow ZORI > HUD FMR
Property tax:   tax record doc > (rate% × price)
NFIP premium:   flood cert doc > FEMA API zone estimate
Market value:   appraisal doc > Zillow ZHVI metro


## Automatic Conflict Detection
The DocumentFactsBundle flags these automatically:
 - List price vs. appraised value (> 8% difference)
 - List price above CMA high estimate
 - SFHA zone confirmed but no flood insurance quote
 - Inspection major defects → raises maintenance + CapEx reserves

## Usage
Drop any combination of documents into the documents_dir folder — the pipeline classifies and extracts each one, then funnels real data directly into the financial model. No configuration needed; it infers the document type from content