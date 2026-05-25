# Design Document: Meta-Classifier — Self-Generating Classification System

**Date:** 2026-05-23
**Status:** Draft — Design Phase
**Scope:** AI system that observes incoming data, infers the classification schema, generates a specialized classifier on the fly, runs it, and surfaces the single most important insight — with optional human-in-the-loop refinement.

---

## 0. What the Meta-Classifier Is

The Meta-Classifier is a **self-adapting classification engine** built as a 5-stage meta-pipeline. Unlike a fixed classifier trained for a known label set, it generates a bespoke classifier fresh for each dataset — no predefined categories, no training data, no configuration required.

### The 5 Stages

```
Stage 1 — INGEST        Detect format (JSON, CSV, JSONL, PDF, plain text) and extract schema
Stage 2 — PROFILE       Identify the domain and the fields that carry the most signal
Stage 3 — DESIGN        Infer what categories should exist; generate detection logic
                        + recommended actions per category  ← the core insight
Stage 4 — RUN           Apply the classifier to every record with confidence scores
Stage 5 — SUMMARIZE     Surface the headline finding and the single most important next action
```

**The core insight (Stage 3):** Instead of a hardcoded decision tree, the LLM infers what the categories *should be* given the domain and patterns, then generates both the *detection logic* (how to recognize each category) and *recommended actions* (what to do when that category is found). Every dataset gets a completely different classifier tailored to its structure — error logs, support tickets, financial transactions, and user feedback each produce entirely different taxonomies.

### When to Use It

| Situation | Benefit |
|---|---|
| Unknown categories ahead of time | Discovers them from the data |
| Mixed data types (text, numbers, structs) | Generates a multi-modal scoring schema |
| Rapidly changing classification needs | Re-generates in seconds, not hours |
| Domain expert is not an ML engineer | Natural language feedback drives iteration |
| One-shot or few-shot datasets | No training data required |
| Need actionable output, not just labels | Each class carries a recommended action |

---

## 1. System Architecture

```
┌──────────────────────────────────────────────────────────────────────────┐
│                       Meta-Classifier — 5-Stage Pipeline                  │
│                                                                            │
│  Raw Input (JSON / CSV / JSONL / PDF / plain text)                        │
│      │                                                                     │
│      ▼                                                                     │
│  ┌──────────────────────────────────────────────────────────────────────┐ │
│  │  STAGE 1 — INGEST  (no LLM)                                          │ │
│  │  FormatDetector + SchemaExtractor                                    │ │
│  │  • Detect file/stream format: JSON array, CSV, JSONL, PDF, text     │ │
│  │  • Parse + normalize → list[dict]                                    │ │
│  │  • Extract column/field names and raw types                         │ │
│  └──────────────────────────────────┬───────────────────────────────────┘ │
│                                     │ list[dict] + RawSchema              │
│                                     ▼                                     │
│  ┌──────────────────────────────────────────────────────────────────────┐ │
│  │  STAGE 2 — PROFILE  (no LLM)                                         │ │
│  │  DataProfiler                                                        │ │
│  │  • Identify domain ("failed payment transactions", "support         │ │
│  │    tickets", "error logs", etc.) via heuristic keyword match        │ │
│  │  • Score each field by signal strength: cardinality, entropy,       │ │
│  │    null rate, value distribution                                     │ │
│  │  • Select top signal fields + representative 30-record sample       │ │
│  └──────────────────────────────────┬───────────────────────────────────┘ │
│                                     │ DataProfile                         │
│                                     ▼                                     │
│  ┌──────────────────────────────────────────────────────────────────────┐ │
│  │  STAGE 3 — DESIGN CLASSIFIER  ← THE CORE INSIGHT  (LLM)             │ │
│  │  ClassifierDesigner                                                  │ │
│  │  Given domain + sample records, asks Claude to:                     │ │
│  │  • Infer what categories SHOULD exist (not predefined)              │ │
│  │  • Write detection logic for each category                          │ │
│  │  • Write a recommended action for each category                     │ │
│  │  • Set confidence signals and tiebreak rules                        │ │
│  │  • Emit a complete ClassifierSpec as structured output              │ │
│  │                                                                      │ │
│  │  Result: a bespoke classifier — error logs, support tickets,        │ │
│  │  transactions, and feedback each produce a different taxonomy       │ │
│  └──────────────────────────────────┬───────────────────────────────────┘ │
│                                     │ ClassifierSpec (saved to store)     │
│                                     ▼                                     │
│  ┌──────────────────────────────────────────────────────────────────────┐ │
│  │  STAGE 4 — RUN  (batched LLM)                                        │ │
│  │  ClassifierRunner                                                    │ │
│  │  • Apply ClassifierSpec to every record                             │ │
│  │  • 10 records per batch, up to 3 parallel LLM calls                │ │
│  │  • Per record: label + confidence score + reasoning snippet         │ │
│  │  • Flag low-confidence records as REVIEW_NEEDED                     │ │
│  └──────────────────────────────────┬───────────────────────────────────┘ │
│                                     │ ClassificationReport                │
│                                     ▼                                     │
│  ┌──────────────────────────────────────────────────────────────────────┐ │
│  │  STAGE 5 — SUMMARIZE  (LLM)                                          │ │
│  │  SummaryAgent                                                        │ │
│  │  • Headline finding: the dominant pattern in the classified data    │ │
│  │  • Single most important next action (drawn from class actions)     │ │
│  │  • Distribution table + confidence histogram                        │ │
│  │  • Low-confidence records surfaced for review                       │ │
│  └──────────────────────────────────┬───────────────────────────────────┘ │
│                                     │ MetaClassifierOutput                │
│                         ┌───────────┘                                     │
│                         │  Optional feedback loop                         │
│                         ▼                                                 │
│  ┌──────────────────────────────────────────────────────────────────────┐ │
│  │  REFINEMENT AGENT  (LLM, on demand)                                  │ │
│  │  "Merge X and Y", "Split Z into A and B", "Ignore field F"          │ │
│  │  → patches ClassifierSpec (version++) → re-runs Stage 4+5 only     │ │
│  └──────────────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Components

### Stage 1 — Ingest: `agents/meta_classifier/ingestor.py`

Parses raw input into a normalized `list[dict]`. No LLM call — deterministic and fast.

**Supported formats:**

| Format | Detection | Parser |
|---|---|---|
| JSON array `[{...}, ...]` | starts with `[` | `json.loads` |
| JSON lines (JSONL) | newline-separated `{...}` | line-by-line `json.loads` |
| CSV | header row + comma/tab/pipe separated | `csv.DictReader` with dialect sniffing |
| PDF | `.pdf` extension or magic bytes | `pdfplumber` → text blocks → line splitting |
| Plain text | fallback | one record per non-empty line, stored as `{"text": line}` |

**Output: `IngestedData`**
```python
class IngestedData(BaseModel):
    format_detected: Literal["json", "jsonl", "csv", "pdf", "text"]
    records: list[dict]
    raw_schema: dict[str, str]          # field name → detected raw type
    total_records: int
    parse_warnings: list[str]           # truncation, encoding issues, etc.
```

---

### Stage 2 — Profile: `agents/meta_classifier/profiler.py`

Identifies the domain and ranks fields by signal strength. No LLM call.

**Responsibilities:**
- Compute per-field statistics: cardinality, null rate, value entropy, top-N values
- Score each field for *signal strength* (high-entropy free text = high signal; UUIDs/timestamps = low signal)
- Run a keyword-heuristic domain detector against field names and top values (e.g. `error_code`, `stack_trace` → "error logs"; `amount`, `merchant` → "transactions")
- Select representative 30-record sample (stratified across most-variable field if N > 500)

**Output: `DataProfile`**
```python
class FieldProfile(BaseModel):
    name: str
    dtype: Literal["string", "number", "boolean", "datetime", "enum", "free_text"]
    null_rate: float
    cardinality: int
    top_values: list[str]
    sample_values: list[Any]
    signal_score: float                 # 0.0–1.0; drives feature field selection
    is_candidate_feature: bool

class DataProfile(BaseModel):
    total_records: int
    field_profiles: list[FieldProfile]
    top_signal_fields: list[str]        # ordered by signal_score desc
    sample_records: list[dict]          # 30 representative records
    detected_domain: str | None         # "customer support tickets", "error logs", etc.
    existing_labels: list[str] | None   # if a label column was found
```

---

### Stage 3 — Design Classifier: `agents/meta_classifier/classifier_designer.py`

**The core insight.** A single LLM call that receives the domain and sample records, then generates a complete bespoke classifier — taxonomy, detection logic, and recommended actions.

**What makes this different from a lookup:** The LLM doesn't receive predefined categories. It infers what categories *should* exist given the domain and observed patterns, then writes detection logic for each. The same pipeline run on error logs vs. support tickets vs. transaction data produces completely different classifiers.

**LLM Prompt Pattern:**

```
You are a classification system designer.

Domain: {detected_domain}
Data fields with signal: {top_signal_fields}
Sample records: {30 records}

Your task:
1. Identify what concept is being classified (e.g. "type of customer complaint")
2. Infer 3–8 mutually exclusive, exhaustive categories that cover the data
3. For each category:
   a. Write a 1-sentence definition
   b. Write detection logic: which field values / patterns indicate this category
   c. Write a recommended action: what should happen when this category is found
   d. List 3–5 distinguishing signals
4. Write tiebreak rules for ambiguous records
5. List fields to ignore (IDs, timestamps, noise)

Respond as JSON per ClassifierSpec schema.
```

**Output: `ClassifierSpec`**
```python
class ClassDef(BaseModel):
    label: str
    definition: str
    detection_logic: str                # ← how to recognize this category
    recommended_action: str             # ← what to do when found
    distinguishing_signals: list[str]
    example_indices: list[int]          # indices into sample_records

class ScoringDimension(BaseModel):
    name: str
    description: str
    weight: float                       # 0.0–1.0; sums to 1.0 across all dims
    signals: list[str]

class TiebreakRule(BaseModel):
    condition: str
    prefer_class: str
    reasoning: str

class ClassifierSpec(BaseModel):
    spec_id: str                        # UUID, for caching / reuse
    created_at: datetime
    version: int                        # increments on each refinement
    subject: str                        # "What is being classified"
    rationale: str                      # Why this taxonomy fits the data
    classes: list[ClassDef]             # The generated taxonomy
    system_prompt: str                  # Full classification prompt for Stage 4
    feature_fields: list[str]
    ignore_fields: list[str]
    scoring_dimensions: list[ScoringDimension]
    tiebreak_rules: list[TiebreakRule]
    output_schema_code: str             # Pydantic class definition as a string
    confidence_threshold: float         # default: 0.6
    notes: str                          # Edge cases and ambiguities noted by LLM
```

**Spec persistence:** Saved to `store/classifier_specs/{spec_id}.json`. Reusable across runs — apply a spec to new data without regenerating.

---

### 2.4 Classifier Factory (`agents/meta_classifier/classifier_factory.py`)

Pure Python — no LLM call. Assembles the `ClassifierSpec` into a ready-to-run callable.

**Responsibilities:**
- Dynamically compile the `output_schema_code` into a live Pydantic class using `exec()` in a sandboxed namespace
- Build the feature extractor: a function `(record: dict) -> str` that selects `feature_fields`, formats them into a classification-ready text block
- Return a `CompiledClassifier` dataclass

```python
@dataclass
class CompiledClassifier:
    spec: ClassifierSpec
    output_model: type[BaseModel]       # compiled Pydantic class
    feature_extractor: Callable[[dict], str]
    system_prompt: str
```

**Safety:** The `exec()` call is run against a whitelist namespace — only `pydantic`, `typing`, and `datetime` are available. Any generated code that references other modules is rejected with a `SchemaCompilationError`.

---

### Stage 4 — Run: `agents/meta_classifier/classifier_runner.py`

Applies the `CompiledClassifier` to every record using batched LLM calls.

**Responsibilities:**
- Accept: `CompiledClassifier`, full dataset, batch size (default: 10 records per call)
- For each batch: build user message (formatted records), call LLM with `system_prompt`, parse structured output
- Retry failed batches with single-record fallback
- Emit per-record: label, confidence score, reasoning snippet, contributing signals
- Stream progress via callback (for API/UI use)

**Output: `RecordResult` per record**
```python
class RecordResult(BaseModel):
    record_id: str | int
    label: str
    confidence: float                   # 0.0–1.0
    reasoning: str                      # 1-2 sentence justification
    contributing_signals: list[str]     # which field values drove the decision
    recommended_action: str             # copied from the matched ClassDef
    needs_review: bool                  # confidence < threshold
```

**Batching strategy:**
- Default: 10 records per LLM call (balances context window vs. latency)
- If `total_records < 20`: single-call mode
- If `avg tokens per record > 500`: auto-reduce to 5 per batch
- Concurrent batches: up to 3 parallel LLM calls (configurable)

---

### Stage 5 — Summarize: `agents/meta_classifier/summary_agent.py`

One final LLM call that reads the full `ClassificationReport` and produces a human-ready summary.

**Responsibilities:**
- Identify the **headline finding**: the dominant or most surprising pattern in the classified data
- Determine the **single most important next action** — drawn from the recommended actions of the most prevalent or highest-severity class
- Produce a concise distribution table and confidence overview
- Flag specific low-confidence records worth human review

**LLM Prompt Pattern:**

```
You have just classified {N} records as {subject}.

Distribution: {label_distribution}
Avg confidence: {avg_confidence}
Low-confidence records: {low_confidence_count}

Based on these results:
1. What is the single headline finding — the most important thing to know?
2. What is the ONE next action someone should take right now?
3. Are there any surprising patterns or anomalies in the distribution?

Be concise. The headline should fit in one sentence. The next action should be specific.
```

**Output: `ClassificationSummary`**
```python
class ClassificationSummary(BaseModel):
    headline: str                       # "68% of support tickets are billing-related"
    next_action: str                    # "Route all Billing class records to finance team"
    distribution_table: dict[str, int]  # label → count
    confidence_overview: str            # prose: "High confidence overall; 12 records need review"
    anomalies: list[str]                # unexpected patterns worth investigating
    review_records: list[str | int]     # record IDs with low confidence
```

---

### 2.4 Classifier Factory (`agents/meta_classifier/classifier_factory.py`)

Pure Python — no LLM call. Assembles the `ClassifierSpec` into a ready-to-run callable.

**Responsibilities:**
- Dynamically compile the `output_schema_code` into a live Pydantic class using `exec()` in a sandboxed namespace
- Build the feature extractor: a function `(record: dict) -> str` that selects `feature_fields`, formats them into a classification-ready text block
- Return a `CompiledClassifier` dataclass

```python
@dataclass
class CompiledClassifier:
    spec: ClassifierSpec
    output_model: type[BaseModel]       # compiled Pydantic class
    feature_extractor: Callable[[dict], str]
    system_prompt: str
```

**Safety:** The `exec()` call is run against a whitelist namespace — only `pydantic`, `typing`, and `datetime` are available. Any generated code that references other modules is rejected with a `SchemaCompilationError`.

---

### 2.5 Classifier Runner (`agents/meta_classifier/classifier_runner.py`)

Applies the `CompiledClassifier` to every record in the dataset using batched LLM calls.

**Responsibilities:**
- Accept: `CompiledClassifier`, full dataset, batch size (default: 10 records per call)
- For each batch: build user message (formatted records), call LLM with `system_prompt`, parse structured output against `output_model`
- Retry failed batches with single-record fallback
- Track: label assigned, confidence score, reasoning snippet, field highlighting
- Stream progress via callback (for API/UI use)

**Output: `ClassificationResult` per record**
```python
class RecordResult(BaseModel):
    record_id: str | int
    label: str
    confidence: float                   # 0.0–1.0
    reasoning: str                      # 1-2 sentence justification
    contributing_signals: list[str]     # which field values drove the decision
    needs_review: bool                  # confidence < threshold

class ClassificationReport(BaseModel):
    spec_id: str
    spec_version: int
    run_id: str
    total_records: int
    classified_at: datetime
    results: list[RecordResult]

    # Aggregate statistics
    label_distribution: dict[str, int]
    confidence_histogram: dict[str, int]    # bucketed: 0-0.4, 0.4-0.6, 0.6-0.8, 0.8-1.0
    low_confidence_count: int
    review_needed_count: int
    avg_confidence: float

    # Provenance
    classifier_spec: ClassifierSpec
    data_profile: DataProfile
```

**Batching strategy:**
- Default: 10 records per LLM call (balances context window vs. latency)
- If `total_records < 20`: single-call mode, all records in one prompt
- If `avg tokens per record > 500`: reduce to 5 per batch automatically
- Concurrent batches: up to 3 parallel LLM calls (configurable via `config.yaml`)

---

### 2.6 Refinement Agent (`agents/meta_classifier/refinement_agent.py`)

Handles human-in-the-loop feedback to iterate on the taxonomy or scoring rules without full regeneration.

**Supported feedback operations:**

| Feedback Type | Example | Action |
|---|---|---|
| Merge classes | "Merge 'Bug Report' and 'Error Report'" | Removes one class, reassigns its examples |
| Split class | "Split 'General Inquiry' into 'Billing' and 'Technical'" | Adds two classes, refines definitions |
| Rename | "Call it 'Feature Request' not 'Enhancement'" | Label rename, updates prompt |
| Add class | "Add a class for 'Compliance Issues'" | Appends new ClassDef with signals |
| Remove class | "Drop the 'Misc' class, re-classify those as best fit" | Removes class, re-runs affected records |
| Reweight | "Ignore the 'subject' field, focus on 'body'" | Updates `feature_fields` |
| Override | "Record #42 should be 'Urgent', not 'Low Priority'" | Hard-coded override, excluded from re-run |

**Process:**
1. User provides feedback as natural language (or structured diff)
2. Refinement Agent calls LLM with current `ClassifierSpec` + feedback → produces a `SpecPatch`
3. Classifier Factory applies the patch → new `ClassifierSpec` with `version += 1`
4. Runner re-classifies only the affected records (or full dataset if taxonomy changed)
5. New `ClassificationReport` is generated and diffed against previous version

---

## 3. Data Flow (End-to-End)

```
Raw Input (JSON / CSV / JSONL / PDF / plain text)
        │
        ▼
━━━━━━━━━━━━━━━━ STAGE 1 — INGEST (no LLM) ━━━━━━━━━━━━━━━━
[Ingestor]
  • Detect format: JSON, JSONL, CSV, PDF, plain text
  • Parse + normalize → list[dict]
  • Extract raw field schema
  • Output: IngestedData
        │
        ▼ IngestedData
━━━━━━━━━━━━━━━━ STAGE 2 — PROFILE (no LLM) ━━━━━━━━━━━━━━━
[Profiler]
  • Identify domain via keyword heuristics
  • Score each field by signal strength
  • Select 30-record representative sample
  • Output: DataProfile (detected_domain, top_signal_fields, sample_records)
        │
        ▼ DataProfile
━━━━━━━━━━━━━━━━ STAGE 3 — DESIGN CLASSIFIER (LLM #1) ━━━━━━
[ClassifierDesigner]
  • Input: domain + sample records (~800–1500 tokens)
  • Infer taxonomy (no predefined categories)
  • Write detection_logic per class
  • Write recommended_action per class     ← unique to this system
  • Write system_prompt + scoring rules
  • Output: ClassifierSpec (~1200 tokens)
  • Spec saved to store/classifier_specs/{spec_id}.json
        │
        ▼ ClassifierSpec → CompiledClassifier (Factory, no LLM)
━━━━━━━━━━━━━━━━ STAGE 4 — RUN (LLM #2…N, batched) ━━━━━━━━━
[ClassifierRunner]
  • 10 records/batch, up to 3 parallel calls
  • ~300–2000 tokens input, ~200 tokens output per batch
  • Per record: label + confidence + reasoning + recommended_action
  • Low-confidence records flagged as REVIEW_NEEDED
  • Output: ClassificationReport
  • Report saved to store/classification_runs/{run_id}.json
        │
        ▼ ClassificationReport
━━━━━━━━━━━━━━━━ STAGE 5 — SUMMARIZE (LLM final call) ━━━━━━
[SummaryAgent]
  • Headline finding: dominant pattern in one sentence
  • Single most important next action
  • Anomaly detection over distribution
  • Output: ClassificationSummary (returned to user / API caller)
        │
        ▼ MetaClassifierOutput (full report + summary)
━━━━━━━━━━━━━━━━ OPTIONAL — REFINEMENT LOOP (LLM, on demand) ━
[RefinementAgent]
  • User feedback → SpecPatch
  • ClassifierSpec version++
  • Re-run Stage 4 + Stage 5 only (Stage 3 skipped)
  • Output: diff of ClassificationReport
```

---

## 4. Pipeline Orchestration (`pipelines/meta_classifier_pipeline.py`)

```python
async def run_meta_classifier(
    data: list[dict] | str | Path,
    *,
    domain_hint: str | None = None,      # override Stage 2 domain detection
    existing_spec_id: str | None = None, # skip Stages 1–3, reuse a saved spec
    batch_size: int = 10,
    max_classes: int = 10,
    min_confidence: float = 0.6,
    dry_run: bool = False,               # run Stages 1–3 only, return spec without classifying
    feedback: str | None = None,         # inline refinement (skips to Refinement Agent)
    on_progress: Callable | None = None, # streaming callback (stage name + pct complete)
) -> MetaClassifierOutput:
    ...

class MetaClassifierOutput(BaseModel):
    run_id: str
    spec_id: str
    spec_version: int
    report: ClassificationReport         # full per-record results
    summary: ClassificationSummary       # headline + next action
```

**Short-circuit paths:**

| Scenario | Stages run |
|---|---|
| Normal full run | 1 → 2 → 3 → Factory → 4 → 5 |
| `existing_spec_id` set | Factory → 4 → 5 (Stages 1–3 skipped) |
| `dry_run=True` | 1 → 2 → 3 only (returns spec, no records classified) |
| `feedback` on existing run | Refinement Agent → 4 → 5 only |

---

## 5. API Endpoints (`server.py` additions)

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/meta-classifier/run` | Full pipeline: infer + classify |
| `POST` | `/api/meta-classifier/infer-spec` | Generate `ClassifierSpec` only (dry run) |
| `POST` | `/api/meta-classifier/classify` | Apply existing spec to new data |
| `GET` | `/api/meta-classifier/specs` | List saved `ClassifierSpec`s |
| `GET` | `/api/meta-classifier/specs/{spec_id}` | Get spec detail |
| `POST` | `/api/meta-classifier/refine` | Apply feedback to a run, re-classify |
| `GET` | `/api/meta-classifier/runs/{run_id}` | Get `ClassificationReport` |

### Request: Full Pipeline Run

```json
POST /api/meta-classifier/run
{
  "data": [
    {"id": 1, "subject": "App crashes on login", "priority": "high"},
    {"id": 2, "subject": "Refund request for April", "priority": "medium"}
  ],
  "domain_hint": "customer support tickets",
  "batch_size": 10,
  "min_confidence": 0.65
}
```

### Response

```json
{
  "run_id": "run_abc123",
  "spec_id": "spec_xyz789",
  "spec_version": 1,
  "total_records": 2,
  "label_distribution": {
    "Technical Issue": 1,
    "Billing & Refunds": 1
  },
  "avg_confidence": 0.87,
  "low_confidence_count": 0,
  "results": [
    {
      "record_id": 1,
      "label": "Technical Issue",
      "confidence": 0.92,
      "reasoning": "Subject line indicates a crash bug during authentication flow.",
      "contributing_signals": ["crashes on login", "priority: high"],
      "needs_review": false
    }
  ],
  "classifier_spec": { ... }
}
```

### Request: Refinement

```json
POST /api/meta-classifier/refine
{
  "run_id": "run_abc123",
  "feedback": "Merge 'Technical Issue' and 'Bug Report' into one class called 'Product Defect'. Also add a new class for 'Account Access' covering login and password issues."
}
```

---

## 6. File & Folder Layout

```
openresearch/
├── agents/
│   └── meta_classifier/
│       ├── __init__.py
│       ├── ingestor.py              # Stage 1: format detection + parsing (no LLM)
│       ├── profiler.py              # Stage 2: domain ID + signal scoring (no LLM)
│       ├── classifier_designer.py   # Stage 3: LLM → ClassifierSpec (taxonomy + actions)
│       ├── classifier_factory.py    # Compile ClassifierSpec → CompiledClassifier (no LLM)
│       ├── classifier_runner.py     # Stage 4: batched LLM classification
│       ├── summary_agent.py         # Stage 5: LLM → headline + next action
│       └── refinement_agent.py      # Optional: feedback → SpecPatch → re-run 4+5
├── pipelines/
│   └── meta_classifier_pipeline.py  # Orchestration: run_meta_classifier()
├── schemas/
│   └── meta_classifier.py           # All Pydantic models for this system
└── store/
    ├── classifier_specs/             # Persisted ClassifierSpec JSON files
    └── classification_runs/          # Persisted ClassificationReport JSON files
```

---

## 7. Schema Overview (`schemas/meta_classifier.py`)

```
Stage 1 output:
  IngestedData
    └── raw_schema: dict[str, str]

Stage 2 output:
  DataProfile
    └── FieldProfile[]         (signal_score, dtype, top_values, ...)

Stage 3 output:
  ClassifierSpec
    ├── ClassDef[]             (label, definition, detection_logic,
    │                           recommended_action, distinguishing_signals)
    ├── ScoringDimension[]
    └── TiebreakRule[]

Factory output (not persisted):
  CompiledClassifier
    ├── ClassifierSpec
    ├── output_model           (dynamic Pydantic type from output_schema_code)
    └── feature_extractor      (Callable[[dict], str])

Stage 4 output:
  ClassificationReport
    ├── RecordResult[]         (label, confidence, reasoning,
    │                           recommended_action, needs_review)
    ├── label_distribution
    ├── confidence_histogram
    └── ClassifierSpec         (provenance)

Stage 5 output:
  ClassificationSummary
    ├── headline               "68% of records are billing-related"
    ├── next_action            "Route Billing class to finance team immediately"
    ├── distribution_table
    └── review_records[]       low-confidence record IDs

Top-level response:
  MetaClassifierOutput
    ├── ClassificationReport
    └── ClassificationSummary

Refinement:
  SpecPatch
    ├── add_classes: ClassDef[]
    ├── remove_labels: str[]
    ├── merge: dict[str, str]  # old_label → surviving_label
    ├── update_feature_fields: list[str] | None
    └── overrides: dict[str, str]  # record_id → forced_label
```

---

## 8. Configuration (`config.yaml` additions)

```yaml
meta_classifier:
  # LLM for spec generation (needs strong reasoning — use best available)
  spec_llm:
    provider: anthropic
    model: claude-opus-4-7

  # LLM for per-record classification (can use a faster/cheaper model)
  classifier_llm:
    provider: anthropic
    model: claude-haiku-4-5-20251001

  # Runner settings
  batch_size: 10
  max_concurrent_batches: 3
  min_confidence: 0.60
  max_classes: 10
  max_sample_records: 30          # records fed to Schema Inferencer
  spec_cache_ttl_hours: 72        # how long to keep specs hot in memory

  # Storage
  spec_store_path: store/classifier_specs
  run_store_path: store/classification_runs
```

**Two-tier LLM strategy:** The spec generation calls (Observer → Generator) run once and use the most capable model. The classification calls (Runner) may be thousands of records and use a faster, cheaper model. Both tiers respect the provider fallback chain in the root `llm` config.

---

## 9. Caching & Reuse

**Spec caching:** Once a `ClassifierSpec` is generated for a domain/dataset shape, it can be reused:
- A hash of `(feature_fields, class_labels, domain_hint)` forms a cache key
- On a new run, if a matching spec exists with `version >= 1` and was created within `spec_cache_ttl_hours`, it is reused
- Reuse skips the two generation LLM calls — only Runner calls are made

**Spec library:** Over time, the `store/classifier_specs/` directory becomes a library of reusable classifiers. A future `/api/meta-classifier/specs/search` endpoint will let users find specs by domain, label names, or field shape.

---

## 10. Error Handling & Edge Cases

| Scenario | Handling |
|---|---|
| Data has no text fields | Observer flags `no_text_features`; Inferencer switches to numeric/categorical classification mode |
| LLM returns invalid JSON | Retry with stricter prompt (add "respond ONLY with valid JSON"); fall back to raw parse after 2 retries |
| Schema compilation fails | `SchemaCompilationError` with the offending code snippet; pipeline falls back to a generic flat label schema |
| Record batch exceeds context limit | Auto-reduce batch size, log warning |
| All records low-confidence | Trigger automatic refinement suggestion: "Taxonomy may be too broad; consider splitting classes" |
| Spec version conflict | Runs are always linked to a specific `spec_id + version`; old runs are never overwritten |
| Empty data input | Raise `ValueError` with a clear message before any LLM calls |

---

## 11. Integration with OpenResearch

The Meta-Classifier is a **general utility pipeline** — it can be applied within any existing research area or standalone:

### Example integrations

**Stock Research:** Classify earnings call transcripts into sentiment categories (Bullish / Bearish / Neutral / Cautious) without a predefined rubric — the classifier infers the taxonomy from the transcript corpus.

**Interview Prep:** Classify a set of job descriptions into role archetypes (IC-heavy / Leadership / Hybrid / Specialist) to help profile-match at scale.

**Board Briefings:** Classify Slack messages or Jira tickets into organizational concern categories (Morale Risk / Delivery Risk / Resourcing / Strategic) to feed structured signal into board agents.

**Standalone:** Accept any CSV or JSON array via the API — the pipeline infers, generates, and classifies with no prior configuration.

---

## 12. Implementation Phases

### Phase 1 — Core 5-Stage Pipeline (MVP)
- [ ] `schemas/meta_classifier.py` — all Pydantic models including `ClassificationSummary`, `MetaClassifierOutput`
- [ ] `ingestor.py` — Stage 1: format detection + parsing (JSON, JSONL, CSV, PDF, text)
- [ ] `profiler.py` — Stage 2: domain detection + signal scoring
- [ ] `classifier_designer.py` — Stage 3: LLM → ClassifierSpec with `detection_logic` + `recommended_action`
- [ ] `classifier_factory.py` — compile spec → CompiledClassifier
- [ ] `classifier_runner.py` — Stage 4: batched LLM classification
- [ ] `summary_agent.py` — Stage 5: headline + single next action
- [ ] `meta_classifier_pipeline.py` — `run_meta_classifier()` orchestration
- [ ] `POST /api/meta-classifier/run` endpoint

### Phase 2 — Persistence & Reuse
- [ ] `store/classifier_specs/` persistence + spec cache key hashing
- [ ] `store/classification_runs/` persistence
- [ ] `GET /api/meta-classifier/specs` + `GET /api/meta-classifier/runs/{id}`
- [ ] `POST /api/meta-classifier/classify` (reuse saved spec, skip Stages 1–3)
- [ ] `GET /api/meta-classifier/specs/{spec_id}` detail view

### Phase 3 — Refinement Loop
- [ ] `refinement_agent.py` — feedback → SpecPatch
- [ ] Patch application + `version++` in ClassifierFactory
- [ ] `POST /api/meta-classifier/refine` endpoint
- [ ] Report diffing (label changes before vs. after refinement)

### Phase 4 — Integrations & Polish
- [ ] Two-tier LLM config (Stage 3 uses best model; Stage 4 uses fast model)
- [ ] `on_progress` streaming callback (stage name + % complete)
- [ ] Spec library search endpoint
- [ ] Domain-specific example buttons (error logs, support tickets, transactions, feedback)
- [ ] Integration hooks for stock / interview / board pipelines
- [ ] Evaluation harness: when ground-truth labels exist, compute accuracy, F1, confusion matrix

---

## 13. Key Design Decisions

| Decision | Choice | Rationale |
|---|---|---|
| 5-stage pipeline | Ingest → Profile → Design → Run → Summarize | Separates deterministic work (Stages 1–2, no LLM cost) from generative work; makes each stage independently testable |
| No predefined categories | LLM infers taxonomy from data | The core power: error logs, tickets, transactions, feedback each get a completely different classifier |
| Recommended action per class | Bundled into ClassDef at design time | Transforms output from "label" to "what to do" — making the result immediately actionable, not just descriptive |
| Single headline + one next action | Forced constraint in Stage 5 | Prevents analysis paralysis; user gets one clear thing to act on, not a wall of statistics |
| Format-agnostic ingestor | JSON/JSONL/CSV/PDF/text in Stage 1 | Users shouldn't have to pre-process data; any format is accepted |
| Schema compilation | `exec()` in sandboxed namespace | Dynamic Pydantic models enable fully typed structured outputs for any generated taxonomy |
| Batch classification | Multiple records per LLM call | Order-of-magnitude cheaper and faster than one-record-per-call |
| Spec persistence | JSON files (not DB) | Consistent with OpenResearch's store pattern; human-readable; specs become a reusable library |
| Two-tier LLMs | Separate models for Stage 3 vs. Stage 4 | Stage 3 is one-time, high-reasoning → best model. Stage 4 is bulk, simpler → fast model |
| Refinement | Patch-based, skips Stage 3 | Preserves the validated taxonomy; users see a clear diff; no cost of full regeneration |
| Confidence flagging | Per-record, threshold-configurable | Surfaces uncertainty explicitly rather than hiding it in a label |
