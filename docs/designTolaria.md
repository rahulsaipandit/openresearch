# Tolaria Session Completion Summary

All three routes are registered. Here's a summary of everything that was built:

## What was completed

### Gap 1 — Tailored resume generation ✅
**New files:**
- `agents/interview/resume_writer.py` — ResumeWriterAgent, Node 5 of the interview pipeline. Takes master profile + JD + FitVerdict, rewrites as a JD-targeted resume. Never fabricates experience — reframes and reorders real achievements. Includes a `tailoring_notes` transparency log.

- `schemas/interview.py` — added `TailoredResume` schema (8 fields: summary, highlighted_skills, experience_bullets, cover_letter_opener, full_resume_md, tailoring_notes); `InterviewPrepBrief` now has an optional `tailored_resume` field.

**Updated:**
- `pipelines/interview_pipeline.py` — extended from 4 to 5 nodes. Node 5 runs on `depth="full"` only. Quick mode still runs nodes 1–4. Progress counter updates to reflect the mode.

### Gap 2 — Live company research ✅
**New file:** `agents/mcp_client.py` — MCPClient with two tools:
- `brave-search` — direct HTTP to Brave Search API (same endpoint as the MCP server wraps). 3 queries per company: interview process, engineering culture, and interview experience.
- `fetch` — direct HTTP GET + HTML-strip. No key required.
Graceful fallback: if `brave_search_key` is blank, `is_available("brave-search")` returns False and agents silently use LLM knowledge. No exception, no warning spam.

**Updated:** `agents/interview/company_researcher.py` — now accepts optional `mcp` param. Runs `_gather_web_context()` before the LLM call; injects search results as a "LIVE WEB RESEARCH — prioritise over training knowledge" block in the prompt.
**Config:** `mcp.brave_search_key` in `config.yaml`. Get a free key at api.search.brave.com (2,000 req/month free tier).

### Gap 3 — Pattern analysis on outcomes ✅
**Updated:** `store/application_store.py` — `ApplicationStore.insights()` method. Pure analytics, no LLM calls. Returns:
- win rate, offer count
- stage funnel (how many applications reached each stage)
- most common failure stage
- fit score vs outcome correlation (avg for offers vs rejections, gap)
- application velocity (last 30 days)
- top 5 companies by fit score
- 5 plain-English action items derived from the patterns

**New endpoint:** `GET /api/tracker/insights` — registered in `server.py`.

### Bonus — Tolaria vault integration ✅
**New file:** `integrations/tolaria.py` — TolariaClient writes Markdown notes to a Tolaria (or Obsidian Local REST API) vault via `PUT /vault/<path>`. Falls back to local `output/` directory if the server is unreachable. Includes `render_interview_brief()` and `render_stock_brief()` Markdown renderers.

**New flag on existing endpoints:**
- `POST /api/interview-prep` — add `"export_to_tolaria": true` to auto-save the prep brief + tailored resume to `vault/interview/` and `vault/resumes/`
- `POST /api/stock-research` — add `"export_to_tolaria": true` to auto-save the research brief to `vault/stock/`
- `POST /api/export/tolaria` — standalone export endpoint (stub for future use)

**Config:** `mcp.tolaria.server_url`, `api_key`, `vault_folder`, `local_fallback_dir` in `config.yaml`. Set `enabled: true` once Tolaria is running (default `http://localhost:27123`).

## Mirrorwork parity after this session
| Area                  | Before                  | Now                                      |
|-----------------------|-------------------------|------------------------------------------|
| Tailored resume       | ❌ Not built            | ✅ ResumeWriterAgent (Node 5)            |
| Live company research | ⚠️ LLM knowledge only   | ✅ Brave Search → LLM synthesis          |
| Pattern analysis      | ⚠️ Data only            | ✅ GET /api/tracker/insights             |
| Vault export          | ❌ Not built            | ✅ Tolaria / Obsidian Local REST         |
| Overall parity        | ~75%                    | ~95%                                     |

## Update @docs/design.md to reflect the changes made and mark features as complete
All the matches are legitimate — `decisions_pending` is a schema field name, Phase 5 Chrome extension items are genuinely still pending, and Phase 7 MCP server items are correctly marked planned. The document is consistent.

### Here's a summary of every change made to docs/design.md

| Location                                      | What changed |
|-----------------------------------------------|--------------|
| Status line (header)                          | Phase 6 "core complete" → "complete (all gaps closed)" |
| Scope line (header)                           | Added Tolaria MCP ✅ |
| Architecture diagram — pipeline node count    | (4 nodes) for Interview → (5 nodes) |
| Architecture diagram — endpoint list          | Added /api/tracker/insights and /api/export/tolaria rows |
| §2 Local API Server endpoint table            | Updated interview-prep signature, added /api/tracker/insights, added Tolaria export note |
| §6.1 MCPClient description                    | Replaced "planned: agents/mcp_client.py" with accurate description of what's built and the Phase 7 upgrade path |
| §6.3 MCP per Research Area table              | Added Status column; Interview Prep marked ✅ Done with accurate description; Stock/Board marked Planned |
| §6.4 Build Plan                               | Completely rewritten with actual vs. planned status column; all Phase 6 steps marked ✅ Done; Phase 7 steps marked Planned |
| §6.5 Tolaria Vault Integration                | New section — vault folder layout, config block, fallback behaviour |
| §8 header                                     | "Phase 6 core" → "Phase 6 full" |
| §8 Pipeline block                             | 4-node → 5-node; Node 5 (ResumeWriter) described; Tolaria export step added |
| §8 Output Schema                              | Added TailoredResume class; InterviewPrepBrief.tailored_resume field |
| §8 API Endpoints                              | Added GET /api/tracker/insights; updated interview-prep signature |
| §9 Phase 6                                    | Expanded to show all six gaps closed — live web, resume writer, insights, Tolaria |
| §10 Open Questions                            | Items 7, 8, 9 marked Resolved with implementation details |
