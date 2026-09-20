# Interview Prep Pipeline Design

Here's my assessment of mirrorwork and whether it's a good fit for openresearch:

## Mirrorwork Fit Assessment for OpenResearch

### What Mirrorwork Is

Mirrorwork is a local-first, CLI-based career tool for senior software engineers searching for jobs. Its core features:

- **Job fit brutality check** — Candid assessment of experience-vs-JD match
- **Company-modelled interview prep** — Researches employer interview style, generates STAR-format answers from your profile
- **Spaced repetition learning** — SM-2 algorithm to track and resurface knowledge gaps
- **Application tracking** — Pipeline metrics

**Tech:** Python, Claude Code agents, MCP, Anthropic Claude API, local-first.

### Fit Assessment: Not a Natural Match

| Dimension        | OpenResearch                          | Mirrorwork                              |
|------------------|---------------------------------------|-----------------------------------------|
| Target user      | Executive / org leader                | Job-seeking software engineer           |
| Domain           | Org intelligence, stock research      | Career/hiring pipeline                  |
| LLM integration  | FastAPI server, multi-provider        | Claude Code agent + MCP                 |
| Data sources     | Jira, Linear, Notion, Slack, SEC, Yahoo Finance | Resume, JD text, web company research |
| Output           | Board briefings, research briefs      | Interview prep, fit verdicts            |

The personas don't overlap. OpenResearch serves executives making organizational decisions; mirrorwork serves engineers optimizing their job search. These are essentially opposite ends of the hiring relationship.

### Where There Could Be Crossover

There are two narrow integration angles worth considering:

- **VP People agent enhancement** — Mirrorwork's job-fit scoring logic (experience vs. JD gap analysis) could inform your VP People agent's talent assessment or hiring advisory capabilities. If your exec board is advising on org health, a "candidate quality signal" or "role spec alignment" tool could be relevant.
- **Architecture patterns worth borrowing** — The SM-2 spaced repetition approach for surfacing recurring org issues (your ConflictDetector already does episodic conflict tracking) is an interesting structural idea. Not a direct lift, but a design pattern worth considering for the planned Executive Heuristics Library.
- **Company research module** — Mirrorwork does company intelligence (interview culture, values). Your planned Executive Review Prep Assistant also involves org-level pattern reasoning. The approach to company research is related, even if the purpose differs.

### Recommendation: Skip the integration, consider the patterns

The codebase isn't directly usable — the user story, data model, and agent goals are misaligned with where OpenResearch is going. Bolting on a job-search tool to an executive intelligence platform would dilute focus.

However, two things from mirrorwork are worth a closer look:

- **SM-2 / spaced repetition** — Could be adapted for the planned Executive Heuristics Library to resurface recurring org risk patterns across review cycles
- **STAR-format structured reasoning** — A good pattern for how your board agents articulate findings (Situation → Task → Action → Result) in the planned BoardBriefing output

If your roadmap eventually expands to include a talent intelligence / executive hiring advisory module (which would fit naturally under the VP People agent), revisiting mirrorwork as a reference implementation would make more sense then.

## Comparison: OpenResearch Interview Prep vs InterviewMentor

https://github.com/PrepLabsAI/InterviewMentor

They solve different halves of the same problem — they're actually complementary, not competitors.

| Category        | Preparation Pipeline                                   | Mock Interview Simulator               |
| --------------- | ------------------------------------------------------ | -------------------------------------- |
| Core paradigm   | Preparation pipeline                                   | Mock interview simulator               |
| Input           | Your resume + a job description                        | You show up and practice               |
| Output          | Tailored brief, resume, STAR answers                   | Scorecard + performance rating         |
| Tech            | Python pipeline, FastAPI, Pydantic, LLM agents         | Markdown prompt files, zero code       |
| Persistence     | JSON stores (profile, tracker, SM-2 skills bank)       | Stateless (no memory between sessions) |
| Personalisation | Deep - every output is keyed to your actual experience | None - same prompt for everyone        |

### What OpenResearch Interview Prep Does Better

✅ **Candidate-centric personalisation**  
The entire pipeline is anchored to your MasterProfile. The fit analysis, STAR answers, tailored resume, and questions are all generated from your actual work history. InterviewMentor has no concept of who you are - it gives every user the same Uber system design problem.

✅ **Resume → role mapping**  
Node 5 (ResumeWriterAgent) rewrites your master profile as a JD-targeted resume with a transparency log (tailoring_notes). InterviewMentor can't do this at all - it has no input channel for your background.

✅ **Job fit intelligence**  
The JobFitAnalyzerAgent applies an 80/20 gap analysis: it identifies the 20% of missing qualifications causing 80% of rejection risk and flags deal_breakers. That tells you whether to apply, not just how to prepare. InterviewMentor skips this entirely.

✅ **Live company intelligence**  
CompanyResearcherAgent fires 3 Brave Search queries and injects live Glassdoor / engineering blog data into the brief before the LLM call. InterviewMentor's prompts use only training-data knowledge - no live web.

✅ **Long-term learning system**  
The SM-2 spaced repetition tracker (store/skills_store.py) seeds every question generated from a run into a reviewable bank. /api/learn/due tells you what to review today. InterviewMentor has no persistence - close the session and it's gone.

✅ **Application tracking and analytics**  
ApplicationStore logs every run with stage, outcome, and fit score. GET /api/tracker/insights computes win rate, funnel drop-off, and fit-score correlation. InterviewMentor has no concept of an application lifecycle.

✅ **Composable infrastructure**  
Because it's a proper pipeline on FastAPI, it integrates with Tolaria/Obsidian vault, the stock research tool, and the executive board. It can be exposed as an MCP tool (Phase 7). InterviewMentor is a standalone Claude Code plugin with no integration surface.

### What InterviewMentor Does Better

✅ **Mock interview simulation**  
This is its defining strength - and it's a gap in OpenResearch. InterviewMentor puts you in the interview: an adaptive AI interviewer asks follow-ups, responds to your answers, and adjusts difficulty in real time. OpenResearch generates prep materials before the interview but doesn't simulate the interview itself.

✅ **40+ specialised domains**  
50+ skill modules: arrays/hashmaps, dynamic programming, graph algorithms, distributed systems, Kubernetes, MySQL performance, ML system design, AI PM, leadership principles - breadth that would take months to match. OpenResearch's QuestionGeneratorAgent produces a single question set (15 questions: 5 behavioural + 5 technical + 3 culture + 2 curveball) per run.

✅ **4-level hint system**  
During practice, the interviewer can give a gentle nudge, a pattern suggestion, approach guidance, or a full walkthrough - adaptive to how stuck you are. OpenResearch generates answers for you (STAR format), but there's no interactive coaching loop.

✅ **Zero setup, zero infrastructure**  
No Python, no server, no API keys, no config. Clone the repo, run `claude --plugin-dir`, and start an interview in 30 seconds. OpenResearch requires a running FastAPI server, API keys (Anthropic, optionally Brave/NewsAPI), and a candidate profile already loaded.

✅ **Scorecard evaluation**  
Post-interview rubric scores you on Problem Understanding, Solution Approach, Code Quality, Complexity Analysis, Edge Cases, and Communication. OpenResearch's FitVerdict scores fit (0–10) against the JD but doesn't evaluate your actual performance in practice.

### Key Gaps in Each

| Gap                          | OpenResearch                                     | InterviewMentor                                |
| ---------------------------- | ------------------------------------------------ | ---------------------------------------------- |
| No mock interview loop       | ❌ You get answers but can't practice giving them | -                                              |
| No scorecard on live answers | ❌ SM-2 tracks retention, not performance quality | -                                              |
| No personalisation           | -                                                | ❌ Every user gets the same problem             |
| No resume processing         | -                                                | ❌ Can't rewrite your CV for a role             |
| No fit assessment            | -                                                | ❌ Can't tell you if the role is worth pursuing |
| No application tracking      | -                                                | ❌ No longitudinal view across applications     |
| No live web data             | -                                                | ❌ Company research is training-data only       |
| Setup friction               | ❌ Server + keys + config                         | -                                              |
| Stateless (no memory)        | -                                                | ❌ No SM-2, no learning curve                   |


## The Obvious Synthesis
The ideal interview prep workflow is OpenResearch first, InterviewMentor second:
1. POST /api/profile/add-resume          ← load your profile
2. POST /api/interview-prep              ← get fit score, tailored resume,
                                            company brief, STAR answers
3. Review the InterviewPrepBrief         ← know your story cold
4. /uber-interviewer (InterviewMentor)   ← simulate the actual interview
5. Score yourself on the rubric          ← identify weak dimensions
6. GET /api/learn/due                    ← review the questions you
                                            flagged as weak (SM-2)
**Steps 1–3 and 6 are OpenResearch; steps 4–5 are InterviewMentor**. Neither tool covers the full loop alone.

## Verdict

**Use OpenResearch Interview Prep when**: you have a specific JD, want to know if it's a fit, need a tailored resume, want STAR answers drawn from your real experience, and want to track your application pipeline over time.

**Use InterviewMentor when**: you want to drill a specific technical domain (system design, DP, Kubernetes), need adaptive live practice, or want an outside-in scorecard on how well you actually perform under pressure.

If you wanted to close the gap, the single highest-value addition to OpenResearch would be a **Node 6: MockInterviewAgent** — a follow-up session that takes the generated QuestionSet and runs an interactive round where it evaluates your spoken/typed answers, adapts its follow-ups, and produces a post-session scorecard appended to the ApplicationRecord.

## RAG / Document Ingestion Architecture

### Current state: no bulk ingestion for interview-prep

Interview-prep data (question bank, resume, candidate profile) is embedded into Chroma **one document per API call**, with no folder-drop or bulk-import path:

- `POST /v1/interview/answer-bank/{candidate_id}` embeds a single entry (title/content/category/tags) via `add_answer_bank_entry()` → `vector_store.upsert(doc_type="answer_bank")` — `memory/interview_memory.py:210-220`, route at `server.py:1505-1507`, body shape `AnswerBankEntryCreate` in `schemas/interview_memory.py:49-56`.
- Questions are embedded only as a side effect of live coaching (`record_question()`, `memory/interview_memory.py:302-345`) triggered by `POST /v1/interview/answer` — never as a bulk import.
- Resume/JD text has two separate, unlinked homes, both plain-text-in-JSON with no file upload:
  - `POST /api/profile/add-resume` (`server.py:1144-1164`, `AddResumeRequest` at `server.py:394-395`) — merges into the pre-interview `MasterProfile` used for JD-fit/tailoring.
  - `PUT /v1/interview/profile/{candidate_id}` (`server.py:1487-1494`, `InterviewProfile` in `schemas/interview_memory.py:29-34`) — stores `resume_text` + `job_description_text` as `profile.md` (`memory/interview_memory.py:131-152`); this is the copy actually injected into the system prompt for grounded live answers by `agents/interview/skills/live_interview_coach.py:79,153-170`.
- Backend: Chromadb (embedded, no server) via `store/chroma_vector_store.py`, subclassed in `memory/interview_vector_store.py:20,28-30`. One shared collection `"interview_memory"` filtered by `candidate_id` metadata, persisted at `data/interview_memory_vectors` (configurable via `interview_memory.data_dir` in `config.yaml`). Markdown+frontmatter source-of-truth files live under `data/interview_memory/<candidate_id>/`.
- Magika-based file-content verification (`integrations/file_type_check.py:37-51`, validates PDF/DOCX/TXT/MD + PNG/JPEG/WEBP/GIF by inspecting real bytes) exists but isn't wired into any interview-prep path — only into stock-document upload and image attachments.

### How the other two research features handle documents (for comparison)

| Feature | Mechanism | Bulk? |
|---|---|---|
| **Interview-prep** | One entry/file per API call (`answer-bank`, `add-resume`, `interview/profile`) | ❌ No |
| **Stock research — SEC filings** | `SECIngestAgent.fetch_chunks()` (`agents/stock/sec_ingest.py:30-65`) pulls 10-K/10-Q directly from SEC EDGAR via the `edgar` library, auto-chunks business/risk-factors/MD&A sections, replaces the ticker's vectors via `SECVectorStore.replace_ticker()`. Triggered transparently on first `POST /api/sec-insights` call for a ticker — no user upload at all. | ✅ Yes, but network-fetched, not local-folder |
| **Stock research — `/api/stock-document-insights`** | Single `UploadFile` per call (`server.py:526-559`), same one-file pattern as interview-prep | ❌ No |
| **Executive board** | `DocumentLoader.load_all()` (`integrations/documents.py:66-91`) scans a configured local folder (`self.folder_path.iterdir()`), reading every `.docx/.pdf/.txt/.md` up to `MAX_TOTAL_CHARS` and concatenating them. Wired via `executive_board.integrations.documents.folder_path` in `config.yaml`. | ✅ Yes — local folder scan |
| **Real estate** | `agents/realestate/document_ingestion.py` wraps `DocumentLoader` + `ScannedPDFOCR`; LLM classifies + extracts type-specific facts into `DocumentInsight`/`DocumentFactsBundle`. Folder configured via `real_estate_research.documents_dir` (default `data/realestate/docs/`) in `config.yaml`, and `POST /api/real-estate-research` loads it when provided. | ✅ Yes — local folder scan |

**Key finding:** `DocumentLoader.load_all()` already implements exactly the folder-scan/bulk-ingestion mechanism interview-prep is missing — it's just not wired to this feature yet. Two of three other document-consuming features (executive board, real estate) already reuse it; interview-prep and stock-document-insights are the two holdouts still requiring one API call per file.

### Proposed fix: reuse `DocumentLoader`, don't invent a new mechanism

Add local-folder RAG ingestion for two candidate-facing inputs, following the executive-board/real-estate precedent instead of a new bespoke pipeline:

1. **Question bank folder** (e.g. `data/interview_seed_questions/`) — sample questions the LLM can reuse or enhance rather than generating from scratch every time.
2. **Candidate grounding folder** (e.g. `data/candidate_profiles/<candidate_id>/`) — resume, project write-ups, incident postmortems, and other supplemental material the Pluely live-answer flow should ground technical and behavioral answers in.

This closes the ingestion gap without adding a second vector-store implementation or a second document-loading code path — but it must be combined with the per-document identity change below, since `DocumentLoader.load_all()` as it exists today (`integrations/documents.py:66-97`) concatenates every file into a single flattened blob (`"\n\n".join(parts)`, line 97) with only an in-text `=== filename ===` marker. That's incompatible with per-document selection and citation, so ingestion must move to a per-file, per-page pipeline instead of calling `load_all()` as-is.

## Full Plan: Per-Document Selection + Source Traceability

Goal: a user can (a) ingest documents into a candidate's corpus, (b) visually pick one or more specific documents to scope a question to, and (c) get an answer whose supporting claims point back to the exact document and page they came from.

### 1. Document identity & chunk metadata

Every ingested document gets a stable `doc_id` — a UUID assigned **once**, the first time a given filename/slot is ingested for a candidate. `doc_id` is *not* derived from file content: it identifies "this logical document" (e.g. "Alex's resume") across edits, not "this exact byte sequence". Content changes are tracked separately (see staleness tracking below) so that re-uploading an edited version of a document updates the same `doc_id` in place — mirroring the `SECVectorStore.replace_ticker()` replace-on-reingest pattern in `store/sec_vector_store.py` — instead of silently creating a duplicate, orphaned document.

A new per-candidate **document registry** (e.g. `data/interview_memory/<candidate_id>/documents/<doc_id>.json`) tracks: `doc_id`, `filename`, `doc_type` (`resume` / `candidate_document` / `seed_question` / `answer_bank_manual`), `page_count`, `ingested_at`, and the stored copy of the original file (needed later so the UI can open the exact page a citation points to) — plus the staleness fields below.

#### Staleness tracking: keeping vectors & graph in sync with document updates

A document can be re-uploaded (or, for folder-based ingestion, edited on disk) after its vectors — and any `CandidateGraph` edges that reference it (`memory/interview_graph.py`'s `grounded_by` edge type links questions to answer-bank/document entries by id) — have already been built. Without an explicit staleness signal, those vectors and graph edges silently go stale with no indication anything is wrong. The registry entry tracks:

```json
{
  "doc_id": "...",
  "content_hash": "sha256 of current file bytes",
  "source_modified_at": "mtime of the source file, or upload timestamp",
  "last_indexed_at": "when chunks for this content_hash were last embedded",
  "last_graph_synced_at": "when CandidateGraph edges for this doc_id were last rebuilt"
}
```

- **Detecting an update**: at ingestion (upload or folder re-scan), compute `content_hash` of the incoming file and compare it to the stored value for that `doc_id`. A mismatch means the document changed since it was last indexed.
- **On a detected change**: delete the existing chunks for `doc_id` (`_delete_by_where({"doc_id": ...})`, already available on `ChromaVectorStore`), re-parse/re-chunk/re-embed the new content, update `content_hash` and `last_indexed_at`, and mark `CandidateGraph` edges touching this `doc_id` for rebuild rather than leaving them pointing at superseded chunks.
- **Derived `stale` flag**: `GET /v1/interview/documents/{candidate_id}` exposes `stale: last_modified_at > last_indexed_at` (or `last_graph_synced_at`) per document, so the document-list UI can visibly flag "needs re-indexing" instead of silently serving answers grounded in outdated content.
- **Folder-based bulk ingestion** (the `scripts/ingest_interview_docs.py` script from the earlier ingestion-gap plan) becomes incremental for free: skip files whose `content_hash` already matches the registry, re-embed only the ones that changed, and flag registry entries whose source file has disappeared from the folder.

Ingestion stops flattening files together. Each file is parsed **per page** (or the closest available unit):
- PDF → `fitz` (PyMuPDF, already a dependency per existing `config.yaml`/CI checks) gives native per-page text extraction.
- Scanned PDF → existing `ScannedPDFOCR` (already used by `agents/realestate/document_ingestion.py`) already produces page-boundaried OCR text — reuse it rather than re-implementing OCR.
- DOCX → paragraph runs are grouped into pseudo-pages (e.g. every N paragraphs or by page-break run) since python-docx has no native page concept.
- TXT/MD → line-range pseudo-pages (e.g. every ~40 lines), since there's no page concept at all.

Each chunk (page text further split into ~300–500 token windows if a page is long) is upserted with metadata:

```json
{
  "candidate_id": "...",
  "doc_id": "...",
  "doc_type": "resume | candidate_document | seed_question | answer_bank_manual",
  "source_filename": "...",
  "page_number": 3,
  "chunk_index": 1
}
```

This is the metadata `InterviewVectorStore` is currently missing entirely (`memory/interview_vector_store.py:32-43` only stores `candidate_id`/`doc_type`/`topic`) — adding `doc_id` + `page_number` is the one change that makes both per-document scoping and citation possible.

Existing answer-bank entries (added via the current `POST /v1/interview/answer-bank/{candidate_id}`) have no file/page — they get a synthetic `doc_id` equal to their existing entry id, `doc_type="answer_bank_manual"`, `page_number=null`, so they remain uniformly selectable and citable at entry granularity alongside real files.

### 2. Graph updates: how documents plug into `CandidateGraph`

Documents must feed `CandidateGraph` (`memory/interview_graph.py`), not just the vector store — otherwise topic-relatedness (`related_topics()`, used by `memory/interview_memory.py:518,610,630` to pull in related context) never learns about document-grounded material.

**How graph updates already happen today (lazy, retrieval-driven):** `record_question()` (`memory/interview_memory.py:302-345`) is the only place edges are written. Every time a question is recorded it adds `question:<id> --tests_topic--> topic:<topic>`, and for each entry in `record.matched_sources` it adds `question:<id> --grounded_by--> answer_bank:<source.id>` (line 343). There's no separate "graph sync" step — the graph grows as a byproduct of whatever the retrieval step actually matched.

**Extending this to documents, not inventing a new mechanism:** `MatchedSource` (`schemas/answer_common.py:40-44`) is currently answer-bank-shaped only (`id`, `title`, `category`, `images`) — no way to represent "this citation came from a document page." It needs:

```python
class MatchedSource(BaseModel):
    id: str
    title: str
    category: str
    images: list[ImageAttachment] = Field(default_factory=list)
    source_type: Literal["answer_bank", "document"] = "answer_bank"
    doc_id: Optional[str] = None
    page_number: Optional[int] = None
    content_hash_at_citation: Optional[str] = None   # see staleness note below
```

Once retrieval can return document chunks as `MatchedSource(source_type="document", doc_id=..., page_number=...)`, `record_question()`'s existing loop needs one small change: target node becomes `document:<doc_id>` instead of always `answer_bank:<source.id>`. No new edge type is needed — `grounded_by` already means exactly this relationship, just from a wider set of source kinds. This is the same mechanism the `citations` field on `InterviewAnswer` (API changes, below) is populated from — one retrieval result feeds both the immediate answer's citation display *and* the graph edge, so they can't drift apart.

**Why `doc_id` stability (from the identity design above) matters here specifically:** because `doc_id` is a stable identifier assigned once and never changes across content edits, `document:<doc_id>` graph edges stay structurally valid even after the underlying document is updated and re-embedded — no edge rewrite is needed just because a document's *content* changed, only its vectors need re-embedding (see staleness tracking above).

**The real gap this doesn't close — stale historical citations:** a `QuestionRecord` written *before* a document was edited still has a `matched_sources` entry pointing at `page_number: 3`, but page 3's content may have shifted after re-ingestion. The `content_hash_at_citation` field above exists so the UI can detect this after the fact: if it doesn't match the document's *current* `content_hash` in the registry, the historical citation is flagged (e.g. "⚠ source document has changed since this was cited") rather than silently shown as if still accurate. This is a deliberate scope cut — fully re-grounding old answers against new document content is a re-run, not a sync, and is out of scope here.

**Optional, not required for v1 — eager graph population at ingestion time:** today, a document/answer-bank entry only gets linked into the graph the first time it's actually retrieved for a question. A newly ingested document (e.g. a resume upload) sits with zero graph edges until something cites it. If that's undesirable, ingestion could run one extra step after embedding: query the new chunks against existing `topic:*` nodes and add `related_to` edges for close matches, so the document is graph-visible immediately. Flagging as optional since it adds an ingestion-time similarity pass for a benefit (discoverability before first use) that may not matter given how quickly documents get cited in practice.

### 3. Embedding model: `nomic-embed-text-v1.5`, run in-process (no server)

Adopt it, with the concerns above resolved as follows:
- Load `nomic-ai/nomic-embed-text-v1.5` via `sentence-transformers` (`trust_remote_code=True`) **in-process**, not through an LM Studio/Ollama server — preserves the "no server, no cloud embeddings" invariant documented in `store/chroma_vector_store.py:5-6`.
- Implement as a custom Chroma `EmbeddingFunction` that applies the required asymmetric prefixes: `"search_document: "` when embedding chunks at ingestion, `"search_query: "` when embedding the user's question at retrieval — centralized in one wrapper so no call site can get it wrong.
- **Migration required**: 768-dim nomic vectors cannot coexist with the current 384-dim MiniLM vectors in the same collection. Re-embedding is a one-time offline pass over `interview_memory` (and `sec_filings`, if adopted there too) — run as part of the ingestion-pipeline rollout, not silently on first query.
- Tradeoff accepted: heavier dependency footprint (torch + einops + sentence-transformers) and a larger first-use model download (~500MB vs ~80MB) than the current default.

### 4. API changes

- `POST /v1/interview/documents/{candidate_id}` (new) — multipart file upload; runs the magika check (`integrations/file_type_check.py`), assigns/reuses `doc_id`, parses per-page, chunks, embeds, upserts, and writes the document-registry entry.
- `GET /v1/interview/documents/{candidate_id}` (new) — lists the registry: `doc_id`, `filename`, `doc_type`, `page_count`, `ingested_at`. Backs the document-list panel below.
- `POST /v1/interview/answer` gains an optional `document_ids: list[str] | None` field. When present, the Chroma query filter becomes `where={"candidate_id": ..., "doc_id": {"$in": document_ids}}` instead of just `{"candidate_id": ...}` — scoping retrieval to exactly the selected document(s). When absent, behavior is unchanged (searches the full candidate corpus).
- `InterviewAnswer` response schema gains `citations: list[Citation]`, where `Citation = {doc_id, filename, page_number, chunk_excerpt, doc_type}` — populated directly from the metadata of whichever chunks the retrieval step actually returned (`agents/interview/skills/live_interview_coach.py`'s prompt-assembly step must capture and pass through the chunk metadata it currently only uses internally, not just interpolate raw text into the prompt).

### 5. Desktop UI: document panel + RAG scoping control in chat

- **New `DocumentLibraryPanel`** (desktop app, alongside the existing `InterviewPanel`/`DocumentInsightsPanel`): lists documents from `GET /v1/interview/documents/{candidate_id}` as a checkbox list (filename, doc_type badge, page count, ingested date), plus an upload control that posts to the new ingestion endpoint. Selection state (`selectedDocIds`) is lifted so it can be read by the answer/chat flow.
- **RAG scoping control in the Q&A flow**: a "Grounding: All documents ▾" control above the question input (interview-prep currently has no chat surface at all per the desktop-app scan above — this is new UI, not a wiring change) that opens the same document list for in-place selection. Selected documents show as removable chips above the input. Whatever is selected is sent as `document_ids` on `POST /v1/interview/answer`; empty selection = search the whole corpus (current behavior).
- **Citation display**: each answer renders its `citations` as clickable source chips, e.g. `[1] resume.pdf — p.3`. Clicking opens the stored original file (from the document registry) to that page — full in-app PDF-page viewer is the target; a v1 fallback can show the cited chunk text plus filename/page in a modal if a page-jump viewer is out of scope for the first pass.

### 6. Rollout order

1. Chunk metadata schema (`doc_id`, `source_filename`, `page_number`) + document registry with staleness fields (`content_hash`, `source_modified_at`, `last_indexed_at`, `last_graph_synced_at`) — no behavior change yet, just makes data traceable and drift-detectable.
2. Per-page ingestion pipeline (replacing flattened `DocumentLoader.load_all()` for this feature) + new upload/list endpoints, incremental re-indexing on content-hash mismatch.
3. `MatchedSource` extended with `source_type`/`doc_id`/`page_number`/`content_hash_at_citation`; `record_question()`'s graph-edge loop extended to target `document:<doc_id>` nodes — makes documents graph-aware using the existing lazy, retrieval-driven mechanism.
4. Embedding model migration (nomic-embed-text-v1.5, in-process, with re-embed pass) — can land independently of (2)/(3)/(5) since it's orthogonal to selection/citation/graph.
5. `document_ids` filter on the answer endpoint + `citations` on the response.
6. Desktop UI: document panel (with a `stale` badge per document), chat-scoping control, citation chips (with a "source changed since cited" indicator where applicable).

## Optional Extension: Obsidian-Vault-Backed Memory, Manually Synced via GitHub

Scope, deliberately narrow: **manual, user-triggered sync** ("push my local memory, pull anything changed elsewhere") to let one person continue on a second device — not live multi-device sync, no realtime merge, no daemon watching for changes.

### Why this is feasible without new plumbing

Mutable memory files already carry the signal a manual sync needs: `updated_at` in YAML frontmatter, written on every edit (`memory/interview_memory.py:149` for `profile.md`, `:206` for answer-bank entries). Append-only files (`questions/*.md`, `assessments/*.md`) never need this — once written they don't change, so there's nothing to conflict on. That means only the mutable files require sync-conflict logic at all.

The existing Tolaria integration (`integrations/tolaria.py`) is not the mechanism to extend here — it's a one-way, local-HTTP push to Obsidian's Local REST API with no frontmatter/wikilinks and no read path (see prior research). Vault sync is git-based and bidirectional, so it's a separate code path, though it can reuse `memory/markdown_frontmatter.py` for frontmatter I/O.

### Sync algorithm (three-way comparison, not last-write-wins)

Track one additional timestamp per file beyond `updated_at`: `last_synced_at` — when this file was last successfully reconciled with the vault repo (stored in the document registry, or a small `sync_state.json` per candidate). On a manual "Sync" trigger:

1. `git pull` the vault repo (plain git subprocess, not the GitHub MCP server — that's for interactive/agent use, a sync script needs a direct, scriptable git operation).
2. For each mutable local file, compare `updated_at` (local) and `last_synced_at`:
   - **Local changed, vault unchanged since `last_synced_at`** → write local copy into the vault, `git add`/commit.
   - **Vault changed, local unchanged since `last_synced_at`** → pull the vault version into local storage; this is exactly a content-hash-mismatch event in the staleness design already specced — it triggers re-embedding and marks any `CandidateGraph` edges touching that record's chunks for resync, for free.
   - **Both changed since `last_synced_at`** → genuine conflict. Per the "not to the millisecond" scope, don't auto-resolve: write the incoming vault version alongside as `<name>.conflict-<timestamp>.md` and surface it in the UI for the user to reconcile by hand, rather than silently picking a winner and losing an edit.
3. `git commit` + `git push`. Update `last_synced_at` for every file just reconciled.

### What this deliberately does not do

- No file locking, no live watch/webhook — sync only happens when the user asks for it.
- No automatic conflict resolution — a genuine two-sided edit is surfaced, not merged.
- No change to how the app reads/writes memory locally day-to-day — sync is a boundary operation (pull before starting work on a new device, push before switching away), not something wired into every read/write.

This is intentionally scoped smaller than the core RAG plan above and can be built independently, once the staleness-tracking fields (rollout step 1) exist to hang the vault-changed detection off of.
