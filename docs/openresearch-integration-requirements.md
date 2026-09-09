
# Pluely ⇄ OpenResearch Integration Requirements

## Purpose

Pluely's Interview Assistant is being restructured so that **Pluely acts as a thin client**: it captures audio, detects when the interviewer has asked a question, and renders the conversation UI — but it no longer owns memory, retrieval, or answer generation itself. **OpenResearch becomes responsible for memory, RAG, and producing the actual answer text.** Pluely's job shrinks to: capture → detect → forward → display.

This document specifies what OpenResearch needs to support to be a drop-in backend for that role. It's written from Pluely's side of the contract — what it will send, what it needs back, and why — so it can be shared with whoever is building/configuring OpenResearch's side.

**Two things are settled and drive everything below:**
- **Transport is plain HTTP/REST**, not MCP. Pluely's frontend runs in a Tauri webview and cannot load Node-only packages (this ruled out MCP for every other integration considered before this one) — a plain HTTP endpoint is the only thing directly reachable from Pluely's existing request pipeline with no new bridging code.
- **Question detection stays in Pluely**, not OpenResearch. Pluely already runs a two-stage classifier (heuristic + LLM fallback) on transcribed interviewer speech and only forwards utterances it's decided are worth answering. OpenResearch does not need to decide *whether* something is a question — only *how to answer* one it's given.

**Two things are still open** and need to be settled between the two sides before implementation locks in (flagged again in §7):
- Whether résumé/JD/answer-bank data continues to be entered and stored in Pluely's own UI (then synced to OpenResearch), or whether that data now lives and is managed entirely on OpenResearch's side.
- The exact base URL, auth mechanism, and versioning scheme for the endpoint(s) below.

## Background: what Pluely is and how it works

For context on what's calling this API — Pluely is an open-source, privacy-first AI assistant desktop app (the positioning, in its own words, is "works seamlessly during meetings, interviews, and conversations without anyone knowing"). It's built as a **Tauri v2 application**: a Rust backend doing native OS work, with a React + TypeScript frontend rendered in an embedded webview. That Rust/webview split is exactly why this integration is HTTP rather than MCP (§ above) — the webview can't load the Node-only MCP SDK, but it can make an HTTP request like any web page can.

**Multi-window, invisible-by-design.** Pluely runs several native windows at once: a main always-on-top overlay (the live assistant UI), a dashboard window (settings/history/management), transient screen-capture windows, a teleprompter window, and — newest — a small local HTTP+WebSocket server for "Phone Mode" (lets a candidate pair their phone via QR code and drive the assistant from there while the desktop app hides). The overlay and dashboard windows are marked OS-level "content protected," so they're invisible to screen recording and screen-share tools (Zoom/Meet/Teams/OBS) — the core promise of the product.

**Audio pipeline (stays entirely inside Pluely — OpenResearch never touches raw audio).** Two independent capture paths feed a merged, time-ordered transcript: the candidate's own microphone (browser-side voice-activity detection) and the interviewer's system audio (native Rust loopback capture with its own lightweight VAD). Each path transcribes independently via a pluggable speech-to-text provider, then both streams are tagged (`mic` vs. `system`) and merged into one chronological view. **This is also where question detection happens** — a heuristic-plus-LLM classifier runs on transcribed interviewer speech, decides what's actually a question worth answering (as opposed to small talk), and only *that* — normalized question text, not raw audio, not every utterance — is what would reach OpenResearch under this integration.

**Chat/completion, today.** Historically, once a question (or any chat input) was ready to answer, Pluely built a system prompt (base instructions + résumé/JD + retrieved answer-bank entries + format/depth instructions, all resolved locally) and sent it to an AI provider — either a user-supplied one (any HTTP endpoint describable as a curl command, resolved with the user's own API key) or "Pluely API," a brokered/managed option for licensed users where Pluely's own backend supplies the upstream model and key. Responses stream back token-by-token and render live in the overlay. **This is the exact layer OpenResearch is being inserted into**: instead of Pluely assembling that enriched prompt itself and calling a model directly, it will call OpenResearch with the raw question + conversation history, and OpenResearch takes over everything from "what's relevant" through "here's the answer text."

**Local-first, until now.** Everything else in the app — chat history, settings, shortcuts, and (until this pivot) the Interview Assistant's résumé/JD/answer-bank data — is stored locally in SQLite, with an embedded retrieval engine (a small, in-process hybrid search index, no server) handling answer-bank matching on-device. That's the piece being removed and handed to OpenResearch; everything described in the rest of this document is that handoff's contract.

**Licensing.** Some Pluely features are gated behind a purchasable license, checked client-side (`hasActiveLicense`) with no server-side enforcement — worth knowing since the Interview Assistant (résumé/JD grounding, answer bank, Phone Mode) is one of the gated features, so a request reaching OpenResearch implies the candidate already has an active license, but nothing stops a modified client from calling this endpoint without one. If OpenResearch wants entitlement enforcement of its own, it shouldn't assume Pluely's client-side gate is sufficient.

## 1. What Pluely currently does locally, that OpenResearch now needs to own

This is the capability baseline — everything here was already built and working in Pluely before this pivot, so OpenResearch reproducing it (rather than a reduced version) is what keeps the feature at parity, not a regression:

| Capability | What it did in Pluely (now needs an OpenResearch equivalent) |
|---|---|
| Résumé/JD grounding | A candidate's résumé, the job description, and free-text custom instructions, injected as context for every answer |
| Personal answer bank | A growing library of behavioral stories / prepared answers / talking points, each with a title, content, category (`story`/`prepared_answer`/`talking_point`), and tags; the top 1–3 most relevant entries retrieved per question and used to ground the answer in the candidate's own words |
| Retrieval | Matching a question against the answer bank and any other stored context to decide what's relevant |
| Answer generation | Producing the actual response text, grounded in the above |
| Answer format | Three shapes the candidate can select: `full_text` (read-aloud sentences), `list` (bulleted key points), `keywords` (minimal words/phrases) |
| Answer depth | Three levels, independent of format: `one_liner`, `balanced`, `detailed` |
| Attribution | Reporting which specific answer-bank entries (by title) were used to ground a given answer, so the candidate can see it and the UI can render a "from your answer bank: X" badge |
| Conversation memory | Recall of earlier turns in the same interview session |
| Streaming | Token-by-token streaming of the answer as it's generated, not a single blocking response |

## 2. Required endpoint: answer a question

This is the one endpoint Pluely cannot function without.

**`POST /v1/interview/answer`** — **implemented**, in `server.py` (`interview_answer()`), backed by `agents/interview/skills/live_interview_coach.py`'s `LiveInterviewCoachSkill`.

**Request** — one deviation from the original sketch below: a `candidate_id` field was added. §6/§8 flagged candidate identity as unresolved on the Pluely/auth side, but the cognitive memory (§6) is candidate_id-scoped by design, so the implementation needs *some* field to key off of now. Pluely doesn't send this today — see the implementation-status note after §6.1 and open item §8.6, still unresolved on the product/auth side.

```json
{
  "session_id": "string — identifies this interview session, stable across turns",
  "candidate_id": "string — NEW, not in Pluely's contract yet; required by the implementation, see §8.6",
  "question": "string — the interviewer's question, already detected and normalized by Pluely",
  "conversation_history": [
    { "role": "interviewer" | "candidate", "content": "string", "timestamp": "ISO-8601" }
  ],
  "answer_style": {
    "format": "full_text" | "list" | "keywords",
    "depth": "one_liner" | "balanced" | "detailed"
  }
}
```

- `session_id` scopes conversation memory and (if résumé/JD/answer-bank data stays server-side, per the open item in §7) which candidate's profile to use.
- `conversation_history` is sent so OpenResearch doesn't need to separately track turn state if it doesn't want to — treat it as authoritative context, not just a hint.
- `answer_style` is set by the candidate in Pluely's UI (including mid-interview, from a paired phone) and must actually shape the response — not just be accepted and ignored. Concretely: `keywords` format needs the response to genuinely be short, separable phrases (Pluely's UI splits on newlines/commas/bullets and renders each as a chip — a response that comes back as a full paragraph will render as one long, wrong-looking chip).

**Response** — must support **streaming** (Server-Sent Events or chunked transfer, whichever is simpler on OpenResearch's side; Pluely's existing streaming consumption code can adapt to either). Each chunk carries incremental answer text; a final message carries metadata that isn't available until generation completes:

```json
{
  "answer_chunk": "string — incremental text, empty/absent on the final message",
  "done": false,
  "metadata": {
    "matched_sources": [
      { "id": "string", "title": "string", "category": "string" }
    ]
  }
}
```

- `metadata.matched_sources` is required for the attribution UI to keep working — it's exactly the list of answer-bank entries (or whatever OpenResearch's equivalent concept is) that grounded this specific answer. If OpenResearch's retrieval doesn't have a clean "these specific N items were used" concept, this needs to be shaped so Pluely can display *something* meaningful here — an empty list is acceptable when nothing was retrieved, but the field itself needs to exist.
- `done: true` on the final message, with `metadata` populated at that point (it does not need to be present on intermediate chunks).

**Latency**: this is a real-time interview aid — a candidate is waiting on this mid-conversation. Whatever retrieval strategy OpenResearch uses server-side, it needs a bounded latency budget for first-token time, not an open-ended "however long the graph traversal takes." A rough target worth designing against: **first token within ~2 seconds**, matching what a single-shot chat completion (no retrieval) already achieves today as the baseline to beat.

**Implementation gap, not glossed over**: `agents/api_utils.LLMClient` (this repo's shared LLM client) has no token-level streaming — it's a single blocking call that returns the complete text. The current implementation generates the full answer, *then* chunks it into SSE frames in `server.py`'s `_chunk_answer_text()`. This satisfies the wire contract above (incremental frames, final `done: true`) but does **not** yet hit the ~2s first-token target — the whole generation happens before the first byte is sent. Wiring real provider-level token streaming into `LLMClient` is a follow-up, tracked as a new open item (§8.8).

### 2.1 Image input/output — implemented

Prompted by a real product question: a candidate may want to share a desktop screenshot for context (a system-design diagram on screen, a coding problem, a whiteboard). **Implemented** on OpenResearch's side, both directions:

**Sending an image to `/v1/interview/answer` (input).** `AnswerRequest` gained an `images` field:

```json
{
  "session_id": "...",
  "candidate_id": "...",
  "question": "...",
  "conversation_history": [...],
  "answer_style": {...},
  "images": [
    { "media_type": "image/png", "data": "<base64>", "caption": null }
  ]
}
```

These images are **ephemeral** — passed straight to the LLM for that one answer (`agents/interview/skills/live_interview_coach.py`) and never persisted. A candidate's live screenshot isn't stored in the cognitive memory; only the resulting text answer is (in `questions/*.md`, per §6.1). If a later feature wants to review "what was on screen when this was asked," that's new scope, not covered here.

**Graceful degradation, not a hard requirement.** Not every model in a provider chain supports vision — in particular, a local model via `openai_compatible` might not. `LLMClient.create_multimodal()` (new method, `agents/api_utils.py`) tries each configured backend with the image attached; if every one fails on that call, it falls back to the plain text-only chain rather than erroring the whole request. The final SSE message's `metadata` carries `images_ignored: true` when this happened, so **Pluely should surface that to the candidate** ("your screenshot couldn't be used for this answer") rather than silently dropping it. Concretely: check `metadata.images_ignored` in the `done: true` frame.

**Receiving images back (output).** Answers ground themselves in the candidate's own answer-bank entries (§3), and those entries can now carry image attachments — e.g. a diagram that's part of a saved story. When an entry with an image grounds an answer, that image comes back in `metadata.matched_sources[].images`:

```json
{
  "matched_sources": [
    {
      "id": "e1",
      "title": "Scaling the payments queue",
      "category": "story",
      "images": [
        { "media_type": "image/png", "data": "<base64>", "caption": "throughput diagram" }
      ]
    }
  ],
  "images_ignored": false
}
```

This is retrieval, not generation — OpenResearch does not produce new images (no image-generation model is integrated). "Receiving an image" means Pluely can render whatever was already attached to the grounding source, not that the model draws something new.

**Answer-bank images** — §3's CRUD endpoints (`POST`/`PUT /v1/interview/answer-bank/{candidate_id}[/{entry_id}]`) now accept the same `images` field on the request body. On OpenResearch's side these are decoded and written as real files (`answer_bank/<entry_id>_images/<image_id>.<ext>`), not kept as base64 inside the markdown frontmatter — a multi-hundred-KB blob inline would defeat the point of storing this as human-readable markdown at all (§6.1). Frontmatter only carries `filename`/`media_type`/`caption`; the API layer re-reads and re-encodes to base64 on the way out, so from Pluely's side the wire format is base64 in, base64 out, regardless of how it's stored underneath.

**Deliberately not done in this pass**: image captions are not fed into the vector embedding used for retrieval (§6.1's dedup-consistency lesson — embedding text that doesn't exactly match what a duplicate-check compares against was a real bug once already; not repeating that pattern for a nice-to-have). This means an answer-bank entry's image is retrieved via its *text* content matching the question, not via any visual/caption similarity — a diagram with no accompanying text won't surface well. Revisit if that turns out to matter in practice.

## 3. Data OpenResearch needs to store and retrieve (if résumé/JD/answer-bank move server-side)

*Contingent on the open item in §7.1 — included here so the shape is ready either way.*

**Interview profile** (one active profile per session/candidate — this was a single-row, "replace on update" model in Pluely, not a versioned history):
- `resume_text: string`
- `job_description_text: string`
- `custom_instructions: string`

**Answer bank entries** (a growing list, CRUD — create/update/delete, list/search):
- `id`
- `title: string`
- `content: string`
- `category: "story" | "prepared_answer" | "talking_point"`
- `tags: string` (free-text, comma-separated in Pluely's original model — comma-separated or an array both work, just needs to be documented)
- `images: [{ media_type, data (base64), caption }]` — new, §2.1. Optional; empty list if the entry has no attached image.
- `created_at` / `updated_at`

If these are to be managed from Pluely's existing UI (Interview Profile and Answer Bank pages) rather than a new OpenResearch-side UI, standard CRUD endpoints are needed — **implemented**, in `server.py`, backed by `memory/interview_memory.py`'s `InterviewMemoryStore`:
- `GET/PUT /v1/interview/profile/{candidate_id}` (single resource, get/replace)
- `GET/POST /v1/interview/answer-bank/{candidate_id}` (list/create)
- `PUT/DELETE /v1/interview/answer-bank/{candidate_id}/{entry_id}` (update/delete)

Two deviations from the sketch above, both driven by candidate_id scoping (§6) being real now rather than a future open item: every path takes `candidate_id`, and `POST .../answer-bank/{candidate_id}` returns `409 Conflict` if the new entry's content is a near-duplicate of an existing one (`InterviewMemoryStore.find_near_duplicate_answer_bank_entry()` — the Mnemosyne-inspired dedup check from §6.1). `tags` is implemented as a real array, not the comma-separated string Pluely's original model used — needs a small mapping on Pluely's side if it sends the old shape.

## 4. Retrieval quality expectations

Pluely's own local implementation (before this pivot) used keyword/BM25 matching, which is known to under-match paraphrased questions — a story tagged "disagreement with manager" wouldn't reliably surface for "tell me about a conflict." **OpenResearch owning retrieval is expected to do meaningfully better than that baseline** (semantic/embedding-based matching, not just keyword search) — otherwise this pivot trades away a working local feature for a network dependency with no retrieval-quality upside. This should be validated with real answer-bank content and realistically-paraphrased questions before being treated as done.

## 5. Session lifecycle

- A session starts when the candidate begins an interview in Pluely and ends when they stop. OpenResearch should treat `session_id` as scoping both conversation history and (if applicable) which résumé/JD/answer-bank context to use — two different Pluely users, or the same user prepping for two different roles, must not have their context cross-contaminate.
- Pluely does not currently specify a session-expiry policy. OpenResearch should define one (e.g., TTL-based cleanup) and document it, since Pluely won't be sending an explicit "end session" signal in the initial version of this integration unless that's added.

## 6. Cognitive memory: candidate strength/weakness tracking

This is new scope beyond what Pluely did locally before this pivot (§1 has no equivalent) — it's the "do we know what this candidate is good/bad at" layer the integration is being asked to add. Settled via clarification during doc review:

- **Scope: cross-session, per-candidate profile.** This is not scoped to a single `session_id` the way conversation history (§2) is. A candidate practicing over multiple sessions — same role or different roles, days or weeks apart — should accumulate one running profile, not reset each session. This means OpenResearch needs a stable `candidate_id` (or equivalent) that outlives any single `session_id`, and `session_id`s need to be attributable back to a candidate. That mapping isn't defined yet — see open items below.
- **Assessment source: hybrid.** After each answered question, an LLM-judge scores the candidate's response against the question (topic, correctness/completeness, clarity) and updates that topic's running mastery estimate automatically — no candidate action required for the memory to update. The candidate can subsequently see and override/correct that judgment (e.g., in a Pluely dashboard view or post-session review), and an explicit override should take precedence over the automatic score for that entry going forward.
- **Feeds live generation, not just reporting.** The `/v1/interview/answer` endpoint (§2) should consult this memory during retrieval/generation for the *same* candidate, not only surface it in a post-interview summary. Concretely: for a question judged to land on a topic the candidate has scored as weak historically, the answer generation should lean more heavily on that candidate's own answer-bank content and prior good answers for that topic, rather than a generic response — the goal is to help the candidate reliably improve on their known gaps in situ, not just log that they exist.

**Data this implies** (additive to §3, same "contingent on §7.1" caveat about where candidate-facing CRUD/UI lives):

- **Topic mastery** — one evolving record per `(candidate_id, topic)`:
  - `topic: string` (needs a taxonomy or free-text-with-normalization decision — open item below)
  - `mastery_score: float` — running estimate, updated by the LLM-judge after each relevant answer
  - `sample_count: int` — how many judged answers fed the current estimate, so a single bad answer doesn't overwrite a well-established strength
  - `last_judged_at`, `candidate_override: float | null`, `override_reason: string | null`
- **Question history log** — one record per answered question, append-only:
  - `candidate_id`, `session_id`, `question_text`, `topic` (as classified), `answer_text` (or a reference to it), `judge_score`, `judge_rationale`, `matched_sources` (reuse §2's shape), `timestamp`
  - This is what lets a candidate (or the dashboard) answer "what was I already asked, and how did I do" — not just the aggregated mastery number.

**Open items specific to this** (in addition to §7's list):
- How `candidate_id` is established and how a `session_id` maps to one — is this a Pluely-side login/account concept, or does OpenResearch mint and own candidate identity?
- Topic taxonomy: fixed list (e.g., aligned to common interview categories — behavioral/system-design/domain-specific) vs. open-ended LLM-assigned topic strings that get fuzzy-matched/normalized over time. Free-text topics drift and fragment (e.g., "conflict resolution" vs. "handling disagreement") without some normalization step.
- Mastery decay: does an old judged answer on a topic count the same as a recent one, or should stale mastery estimates decay/require refresh, given a candidate may improve between practice sessions?
- Where the judge call sits in the latency budget — §2 targets ~2s to first token; the judge scoring pass (previous answer) should not block or add latency to the *next* question's answer, so it likely needs to run asynchronously after the answer is already streaming/complete.

### 6.1 Implementation sketch: markdown storage + vector + graph

Per explicit direction: this memory is stored as **markdown files with YAML frontmatter**, not JSON rows, with **vector search and a lightweight knowledge graph** added on top so topics, questions, and answer-bank entries can be linked, not just listed. Two existing, code-verified references shaped this, both already proven (not aspirational) rather than invented from scratch:

- `docs/packages/cognitiveBrain/memory` (a separate TypeScript cognitive-memory package reviewed for this design) has a real, working `MemoryEntry`/`PageFrontmatter` schema pair, an `ObsidianVaultProvider` that serializes frontmatter + body to `.md` files on disk, an Orama-based hybrid vector+BM25 search fused with real reciprocal-rank-fusion (RRF) math, and an in-process typed-edge knowledge graph (`InProcessGraph`) with a real 3-pass co-occurrence-to-typed-edge algorithm. Its own design doc's claims about a desktop-scale pgvector index and a Neo4j graph adapter are **not implemented** — those are `// TODO Phase 3+` comments with no corresponding class — so only the in-process/embedded versions of this pattern are reusable as proof, not the desktop-scale ones.
- `store/sec_vector_store.py` in *this* repo already sets the precedent for the right scale of vector store here: chromadb's local `PersistentClient` with its default on-device embedding model, no server, no cloud embedding API — deliberately chosen over heavier options because a candidate's answer bank / question history is a "handful of documents" corpus, the same category SEC filings were judged to be. The interview memory should follow that same precedent rather than introducing a new vector infra decision.

**Markdown storage layout** (one directory per candidate, mirroring `memory/experiment_memory.py`'s per-run-JSON-file convention but as markdown):

```
interview_memory/<candidate_id>/
  profile.md                     # résumé/JD/custom_instructions — frontmatter + body
  answer_bank/<entry_id>.md      # one file per answer-bank entry
  topics/<topic_slug>.md         # one file per topic — current-state summary, derived not authoritative (see below)
  assessments/<timestamp>_<hash>.md  # one file per judged assessment of a topic — append-only, never rewritten
  questions/<timestamp>_<hash>.md  # one file per answered question — append-only, never rewritten
  graph.json                     # serialized adjacency (edges only; nodes are the slugs/ids above)
```

Frontmatter should use a real YAML library (Python: `pyyaml` / `python-frontmatter`) rather than hand-rolled parsing — this is a specific, named weakness in the cognitiveBrain reference (its frontmatter parser is regex-based and only understands flat keys and simple arrays; nested structures would silently break it). There's no reason to inherit that limitation when adopting the pattern.

**Topic mastery is versioned facts, not a mutated field.** The first draft of this design had `topics/<slug>.md` hold a single mutable `mastery_score` field, overwritten on every judge update — that loses history (was this candidate always weak on capacity estimation, or did they regress after being strong three sessions ago?) and can't be corrected without destroying the prior state. Borrowed instead from Mnemosyne's TripleStore pattern (a temporal knowledge graph of versioned facts, evaluated alongside turbovec/LEANN — see below): each judged assessment is its own immutable, timestamped fact in `assessments/`, and `topics/<slug>.md` is a **derived, rebuildable summary** — current mastery is a query over assessment history (e.g. recency-weighted average, most-recent-wins, or whatever decay policy §6's open item settles on), not a field that gets clobbered in place.

Example `assessments/2026-09-01T142200Z_a1b2.md` (immutable fact):

```markdown
---
topic: system-design
candidate_id: cand_8f2a
question_ref: questions/2026-08-30_a1b2.md
judge_score: 0.55
source: llm_judge
candidate_override: null
timestamp: 2026-09-01T14:22:00Z
---

Under-scoped the capacity estimate by roughly 10x — didn't account for
read replication before proposing a shard count.
```

Example `topics/system-design.md` (derived summary, safe to regenerate):

```markdown
---
topic: system-design
candidate_id: cand_8f2a
mastery_score: 0.62
sample_count: 7
last_judged_at: 2026-09-01T14:22:00Z
derived_from: [assessments/2026-08-15_c3d4.md, assessments/2026-08-30_a1b2.md, ...]
related_topics: [distributed-systems, tradeoff-analysis]
---

Running notes on this candidate's system-design mastery: consistently
strong on component decomposition, weaker on capacity estimation
(under-scoped twice — see linked assessments).
```

The body being freeform markdown (not just structured fields) is what makes this "cognitive" rather than a plain database row — it's where the LLM-judge can accumulate qualitative notes across sessions, which is exactly the kind of synthesized-knowledge artifact `docs/packages/cognitiveBrain/docs/designCognitiveBrain.md` (§5.5, "Human-Readable Cognition") argues raw JSON can't hold. A candidate override (§6) is itself just another fact appended to `assessments/`, tagged `source: candidate_override` — it naturally takes precedence in the summary derivation without needing a separate override mechanism bolted on.

**Vector layer**: embed the body text of `topics/*.md`, `questions/*.md`, and `answer_bank/*.md` into one chromadb collection (metadata-filtered by `candidate_id`, mirroring `SECVectorStore`'s `ticker`-filtered single-collection design), so a paraphrased question retrieves the right topic notes and answer-bank entries regardless of exact wording — this is what actually satisfies §4's "meaningfully better than keyword matching" bar.

*Alternatives considered and rejected for the vector layer:* **LEANN** and **turbovec** were both evaluated — both are legitimate, high-quality projects (turbovec: 16.7k stars, MIT, cites an ICLR 2026 paper for its TurboQuant quantizer; LEANN: real 97%-storage-reduction results), but both are optimized for corpora of millions of documents where raw embedding storage is the actual bottleneck (LEANN's headline case is 60M Wikipedia chunks; turbovec's is a 10M-document, 4GB-vs-31GB comparison). A candidate's practice corpus is hundreds of markdown files — raw float32 vectors for that fit in kilobytes. Adopting either would mean a new native/Rust dependency and quantization-induced recall loss, bought for a storage saving that doesn't apply at this scale — the same reasoning `store/sec_vector_store.py`'s existing code comment already used to reject them for SEC filings. **Mnemosyne**'s SQLite-only, no-vector-DB approach (binarized embeddings + Hamming distance + FTS5, all in-process) was also considered — its zero-dependency footprint is appealing, but its own documented benchmarks note materially reduced pure-retrieval recall from binarization, a tradeoff that matters more here than in Mnemosyne's original setting: a missed retrieval means the wrong story surfaces live, mid-interview. chromadb, already proven in this repo at comparable scale, remains the better fit. Mnemosyne's **versioned-facts/temporal-graph structure** was still worth adopting independent of its storage engine — see the topic-mastery design above.

**Graph layer**: adopt `InProcessGraph`'s typed-edge idea, scoped down to what this domain needs — no need for the full node-type/edge-type vocabulary built for browsing/entity extraction:
- `question --tests_topic--> topic`
- `question --grounded_by--> answer_bank_entry`
- `topic --related_to--> topic` (co-occurrence across questions, computed the same way `InProcessGraph.inferTypedEdges()` does)
- `question --similar_to--> question` (paraphrase clusters, via the vector layer's nearest neighbors)

This graph is what lets the answer-generation step (§2) reason past a single topic match — e.g. surfacing a related topic's strong answer-bank entry when the current weak topic doesn't have one of its own — and it's small enough (per-candidate, hundreds not millions of edges) that an in-process adjacency structure serialized to `graph.json` is the right scale, not a graph database.

**What this deliberately does not carry over** from the cognitiveBrain reference: multi-platform (web/mobile/desktop) tiering, SKILL.md instruction injection, MCP vault sync, and the browser-automation-adjacent parts of that package are unrelated to this integration and are not being adopted — only the memory-representation patterns (frontmatter schema shape, hybrid search fusion, typed-edge graph, salience-style scoring) are relevant here.

### 6.2 Implementation status — built

Everything in §6.1 is implemented, plus one addition beyond the original sketch (the Skills layer, below). File map:

| Design element | File |
|---|---|
| Frontmatter read/write (real YAML, not hand-rolled) | `memory/markdown_frontmatter.py` |
| Vector layer (chromadb, `SECVectorStore` pattern) | `memory/interview_vector_store.py` |
| Typed-edge graph | `memory/interview_graph.py` |
| Candidate-scoped store tying it together | `memory/interview_memory.py` (`InterviewMemoryStore`) |
| LLM-judge (topic + score + rationale) | `agents/interview/memory_judge_agent.py` |
| Pydantic request/response/domain schemas | `schemas/interview_memory.py` |
| `/v1/interview/*` endpoints | `server.py` |
| Tests | `tests/test_interview_memory.py`, `tests/test_pre_interview_drill.py` (17 tests) |

**Addition beyond the original sketch: a Skills layer.** During implementation planning it became clear the memory needed more than one consumer — a live, in-interview answer flow and a separate pre-interview practice/drilling flow, both reading and writing the *same* candidate memory. `agents/interview/skills/base.py` defines a thin `Skill` interface (real code, not the cognitiveBrain reference's SKILL.md prompt-injection pattern — these skills need actual logic: retrieval, SM-2 scheduling, judge dispatch) plus a registry. Two skills exist:
- **`live_interview_coach`** (`live_interview_coach.py`) — the retrieval + generation flow behind §2's endpoint. Split into `apply()` (retrieval + generation, returns immediately) and `judge_and_record()` (runs as a background task *after* the answer has streamed back, so judge latency never sits on the next question's budget — directly resolving the open item that used to be in §6).
- **`pre_interview_drill`** (`pre_interview_drill.py`) — SM-2 spaced-repetition practice over previously-answered questions. Deliberately a **fresh implementation**, not a call into the existing `store/skills_store.py` (which stays untouched — it serves the pre-existing single-user, non-candidate-scoped JD/resume research feature, a different system). A question answered live becomes drillable practice material later because both skills operate on the same `questions/*.md`.

New endpoints beyond §2/§3's original scope: `GET /v1/interview/skills` (list registered skills) and `POST /v1/interview/skills/{skill_name}/apply` (generic dispatcher — e.g. `pre_interview_drill`'s `due_today`/`record_review` actions go through this rather than dedicated routes).

**One real bug caught by the tests, not by inspection**: the first version of `InterviewMemoryStore`'s ID generator derived its uniqueness suffix from `hashlib.sha256(...id(object())...)`. CPython can reuse the same address for a rapidly created and immediately garbage-collected object, so consecutive fast calls (exactly what a test loop — or real traffic — produces) generated **identical IDs**, silently overwriting each other's assessment/question files. Fixed by switching to `uuid.uuid4()`. Left in as a comment in `interview_memory.py` since it's a non-obvious footgun worth remembering, not just a fixed diff.

**Local exposure**: no new server or process — `/v1/interview/*` is exposed by the same single FastAPI app (`server.py`) as every other OpenResearch feature, at `http://127.0.0.1:7842` by default (`config.yaml`'s `server` section). There's no auth on any of it yet (ties back to open item §8.2). One real gap this surfaced and fixed in passing: the CORS middleware only allowed `GET`/`POST` (`allow_methods`), which would have silently blocked the new `PUT`/`DELETE` profile/answer-bank routes for any browser-based caller (the Chrome extension, or Pluely if it calls via webview `fetch()` rather than its Rust backend) — extended to include `PUT`/`DELETE`. See `docs/SETUP.md` §8 for curl examples of the full flow (set profile → add answer-bank entry → ask a live question → drill it later).

**Deviations and unresolved edges worth flagging back to whoever tunes this against real data**:
- The near-duplicate distance threshold (`_ANSWER_BANK_DEDUP_DISTANCE = 0.08`) and the pre-generation topic-guess threshold (`_TOPIC_GUESS_DISTANCE = 0.5`) in `interview_memory.py` are both placeholders — chromadb's default distance isn't a calibrated cosine similarity, so these need tuning against real answer-bank content before being trusted, exactly as §4 already said about retrieval quality generally.
- To keep retrieval fast enough to matter for §2's latency budget, the implementation guesses a question's topic via a *single cheap vector lookup* against already-embedded topic notes (no LLM call) before generating the answer, then lets the LLM judge assign the real topic afterward — these two can disagree, and reconciliation is just "the judge's classification wins," not anything more sophisticated.
- Mastery-decay (§6's open item) is still unresolved: `_recompute_topic_summary()` currently takes the most recent 5 assessments (or the most recent 3 candidate overrides) unweighted by age — a real recency-weighted decay policy is still to be designed, this is a placeholder that happens to behave reasonably.

## 7. Error handling & degradation

Pluely needs to know, structurally, when something has gone wrong versus when there's genuinely no answer:

- Standard HTTP error codes for transport/auth failures (4xx/5xx), with a JSON error body Pluely can surface to the candidate (`{ "error": "string — human-readable" }` at minimum).
- A distinction between "OpenResearch is unreachable" (network/timeout — Pluely should show a clear "can't reach your assistant backend" state) and "OpenResearch responded but found nothing relevant" (a normal, expected outcome for a question with no matching context — should still return a best-effort generated answer, not an error).
- Since the "fully delegate" decision means Pluely has **no local fallback** for this feature, an OpenResearch outage means the candidate gets no interview assistance at all, for as long as the outage lasts. Worth being explicit about that as a real operational stake, not a hypothetical — whatever uptime/retry expectations exist for this endpoint should be set with "someone is mid-interview relying on this" in mind, not casual dev-environment expectations.

## 8. Open items — need to be settled, not assumed

1. **Does résumé/JD/answer-bank management stay in Pluely's UI (writing through to OpenResearch) or move entirely to an OpenResearch-side UI?** This determines whether §3's CRUD endpoints are needed at all, or whether Pluely only ever calls §2's answer endpoint.
2. **Base URL, versioning, and auth.** Is this a per-user API key, a shared service token, mTLS, something else? Is this endpoint self-hosted per user (matching the "local-first" spirit of the rest of Pluely) or a shared/multi-tenant service?
3. **Privacy framing.** This pivot means full interview conversations — potentially including sensitive career/personal details — now leave Pluely and are processed by an external service by default, a real change from Pluely's existing "privacy-first, local-first" positioning (`docs/design.md`). Worth being explicit, on both sides, about what OpenResearch does and doesn't retain/log, since that's a claim Pluely's own UI may need to make to the candidate.
4. **Session-expiry policy** (§5) — needs a concrete answer, not left implicit.
5. **Streaming transport choice** — SSE vs. chunked HTTP — whichever is simpler for OpenResearch to implement; Pluely can adapt to either, but it needs to be picked, not left ambiguous.
6. **Candidate identity** (§6) — how `candidate_id` is established/authenticated, distinct from the per-interview `session_id`, since the cognitive memory profile is explicitly cross-session. **Still open on the product/auth side** — the implementation (§6.2) now requires a `candidate_id` on every request/path since it had to pick something concrete, but nothing yet defines where Pluely gets that value from (login? device ID? license key?) or authenticates it. Until this is settled, treat the current `candidate_id` field as a placeholder contract, not a finished identity system.
7. **Topic taxonomy** (§6) — fixed category list vs. open-ended/normalized LLM-assigned topics for mastery tracking. Implemented as open-ended (the LLM judge assigns a normalized string, reusing an existing label when it fits — §6.2), not yet validated against real usage for how much topic-label drift/fragmentation actually occurs in practice.
8. **Token-level streaming** (§2) — `LLMClient` has no provider-level streaming; the implemented endpoint pseudo-streams by chunking a fully-generated response. Needs real streaming support added to `agents/api_utils.LLMClient` (or a parallel streaming path) before the ~2s first-token target is actually achievable, not just contractually satisfied.
9. **Mastery-decay policy** (§6.2) — the implemented "last 5 assessments, unweighted" basis for current mastery is a placeholder, not a considered decay policy. Needs a real design (recency-weighted average? explicit half-life?) once there's real usage data to validate against.

## 9. Trying it locally — a walkthrough for Pluely's side

This is the practical sequence for pointing a local Pluely build at a running OpenResearch instance today, and — most importantly — what Pluely needs to send that it doesn't currently have a concept of.

**Step 1 — start OpenResearch.** `python server.py` from the OpenResearch repo root, with an LLM provider configured in `config.yaml` (cloud or local — e.g. LM Studio via the `openai_compatible` provider). Default: `http://127.0.0.1:7842`.

**Step 2 — confirm it's up.** `GET http://localhost:7842/api/health` — if `interview cognitive memory` failed to initialize (visible in the server's startup log), the LLM provider chain couldn't be reached and none of what follows will work.

**Step 3 — seed a candidate's profile and answer bank.** These are the §3 CRUD endpoints, now implemented at `/v1/interview/profile/{candidate_id}` and `/v1/interview/answer-bank/{candidate_id}` (§6.2). Until Pluely's own UI writes through to these, populate them directly to have something for the answer endpoint to ground against:

```bash
curl -X PUT http://localhost:7842/v1/interview/profile/cand_demo \
  -H "Content-Type: application/json" \
  -d '{
    "candidate_id": "cand_demo",
    "resume_text": "...",
    "job_description_text": "...",
    "custom_instructions": ""
  }'

curl -X POST http://localhost:7842/v1/interview/answer-bank/cand_demo \
  -H "Content-Type: application/json" \
  -d '{
    "title": "...",
    "content": "...",
    "category": "story",
    "tags": []
  }'
```

**Step 4 — call the answer endpoint.** This is §2's `POST /v1/interview/answer`, streaming SSE:

```bash
curl -N -X POST http://localhost:7842/v1/interview/answer \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "sess_1",
    "candidate_id": "cand_demo",
    "question": "Tell me about a time you scaled a system under load.",
    "conversation_history": [],
    "answer_style": {"format": "full_text", "depth": "balanced"}
  }'
```

**The one thing Pluely needs to actually add: `candidate_id`.** It's not in §2's original request shape — Pluely doesn't currently have any concept of a stable candidate identity to send, only the per-interview `session_id`. The implementation had to pick something concrete to key the cross-session cognitive memory (§6) on, so every request above now requires it. This is the same gap tracked as open item §8.6 — it's still unresolved *what value Pluely should actually send* (a logged-in account ID? a device ID? a license key?) and how/whether it should be authenticated, but structurally: **whatever request Pluely sends to `/v1/interview/answer`, and whatever calls it makes to the profile/answer-bank endpoints, now need a `candidate_id` field added that didn't exist in the pre-pivot design.** Until Pluely's side decides where that value comes from, testing against a hardcoded string (`cand_demo` above) is the only way to exercise the rest of the contract.
