# Setup Guide

This guide walks you from a fresh clone to a running server in about 10 minutes.

---

## Prerequisites

- Python 3.11 or later
- At least one LLM API key **or** a local LLM running (see [Local LLM](#local-llm-lm-studio--ollama))
- `pip` (comes with Python)

---

## 1. Install Dependencies

If more than one Python version is installed on this machine, create the venv with an **explicit, pinned** interpreter rather than a bare `python` — this project is tested on Python 3.12, and a venv accidentally built on a different version can fail at import time with `ModuleNotFoundError: No module named 'pydantic_core._pydantic_core'` (pydantic_core ships version-specific compiled wheels, e.g. `cp312`, that don't match a different interpreter's ABI):

```bash
py -3.12 -m venv .venv          # Windows, if the py launcher is installed
.venv\Scripts\python.exe -m pip install -e .
```

Only one Python on this machine? Plain `pip install -e .` is fine:

```bash
pip install -e .
```

This installs the core dependencies: FastAPI, uvicorn, yfinance, httpx, pydantic, anthropic, openai, jinja2, pyyaml, structlog.

To also install optional document extraction support:

```bash
pip install python-docx pypdf
```

---

## 2. Configure `config.yaml`

Open `config.yaml` in the project root and fill in the sections you need.

### LLM (required — at least one provider)

```yaml
llm:
  provider_chain:
    - provider: anthropic
      model: claude-sonnet-4-6
      api_key: "sk-ant-YOUR_KEY_HERE"
```

Get your Anthropic key at [console.anthropic.com](https://console.anthropic.com).

For OpenAI instead:

```yaml
    - provider: openai
      model: gpt-4.1
      api_key: "sk-YOUR_KEY_HERE"
```

### Local LLM fallback (optional)

If you have LM Studio or Ollama running locally, add a second entry in the provider chain:

```yaml
    - provider: openai_compatible
      base_url: http://localhost:1234/v1   # LM Studio default port
      model: qwen3-27b                     # name of the model you have loaded
      api_key: lm-studio                   # any string — not validated
```

Ollama uses port `11434` by default:

```yaml
    - provider: openai_compatible
      base_url: http://localhost:11434/v1
      model: llama3.1:8b
      api_key: ollama
```

---

## 3. Stock Research Setup

The stock pipeline works out of the box with just Yahoo Finance (no key needed). Add optional keys for deeper data:

```yaml
stock_research:
  data_sources:
    yahoo_finance: true
    alpha_vantage_key: "YOUR_KEY"   # alphavantage.co — free tier: 25 req/day
    polygon_key: "YOUR_KEY"         # polygon.io — free tier: 5 req/min
    news_api_key: "YOUR_KEY"        # newsapi.org — free tier: 100 req/day
  cache_ttl_hours: 4
```

Free tiers are sufficient for personal use. SEC EDGAR filings are always free with no key.

---

## 4. Executive Board Setup

### Minimum setup (manual paste)

No integration keys are required. You can paste org data as plain text or JSON when calling `/api/board-session`.

### Jira

1. Go to [id.atlassian.com/manage-profile/security/api-tokens](https://id.atlassian.com/manage-profile/security/api-tokens)
2. Create an API token
3. Add to config:

```yaml
executive_board:
  integrations:
    jira:
      base_url: "https://yourorg.atlassian.net"
      api_token: "YOUR_JIRA_API_TOKEN"
      email: "you@yourorg.com"

  jira_project_keys:
    - "ENG"
    - "PRODUCT"
    - "INFRA"
```

### Linear

1. Go to [linear.app/settings/api](https://linear.app/settings/api)
2. Create a Personal API key
3. Add to config:

```yaml
    linear:
      api_key: "lin_api_YOUR_KEY"

  linear_team_keys:
    - "engineering"
    - "product"
    - "platform"
```

### Notion

1. Go to [notion.so/my-integrations](https://www.notion.so/my-integrations)
2. Create a new integration with **Read content** permission only
3. Share each database you want to query with the integration (open the database → Share → invite your integration)
4. Copy the database IDs from the URL: `notion.so/workspace/DATABASE_ID?v=...`

```yaml
    notion:
      api_key: "secret_YOUR_NOTION_TOKEN"
      database_ids:
        - "a1b2c3d4e5f6..."    # OKR tracker
        - "b2c3d4e5f6a1..."    # Risk register
        - "c3d4e5f6a1b2..."    # Project status
```

### Slack (read-only)

The Slack integration only reads messages — it never posts or modifies anything.

1. Go to [api.slack.com/apps](https://api.slack.com/apps) → Create New App → From Scratch
2. Under **OAuth & Permissions**, add these Bot Token Scopes:
   - `channels:history` — read messages from public channels
   - `channels:read` — list channels
   - `groups:history` — read messages from private channels (if needed)
3. Install the app to your workspace
4. Copy the **Bot User OAuth Token** (`xoxb-...`)
5. Invite the bot to each channel you want it to read (`/invite @yourbot`)
6. Find channel IDs: right-click a channel in Slack → View channel details → copy the ID at the bottom

```yaml
    slack:
      bot_token: "xoxb-YOUR_BOT_TOKEN"
      channel_ids:
        - "C01234ABCDE"    # #engineering-standup
        - "C09876ZYXWV"    # #product-weekly
        - "C05555MNOPQ"    # #cross-team-risks
      days_back: 7
```

### Word / PDF / Text Documents

Point to a folder containing meeting notes, status reports, or strategy docs:

```yaml
    documents:
      folder_path: "/path/to/your/docs/folder"
      file_extensions:
        - ".docx"
        - ".pdf"
        - ".txt"
        - ".md"
      max_file_mb: 10
```

Files larger than `max_file_mb` are skipped. Total text fed to the LLM is capped at 50,000 characters regardless of how many files are in the folder.

---

## 5. Start the Server

```bash
python server.py
```

Or with uvicorn directly:

```bash
uvicorn server:app --host 127.0.0.1 --port 7842
```

You should see:

```
  OpenResearch Server
  Running at http://127.0.0.1:7842
  Chrome extension endpoint: http://127.0.0.1:7842/api/
```

Verify it's running:

```bash
curl http://localhost:7842/api/health
```

Expected response:

```json
{
  "status": "ok",
  "stock_pipeline": true,
  "board_pipeline": true,
  "timestamp": "2026-05-17T10:00:00"
}
```

---

## 6. Quick Test

### Stock Research

```bash
curl -X POST http://localhost:7842/api/stock-research \
  -H "Content-Type: application/json" \
  -d '{"ticker": "AAPL", "depth": "quick"}'
```

`depth: "quick"` skips Alpha Vantage, Polygon, and SEC EDGAR — useful for a fast test.

### Executive Board (manual paste)

```bash
curl -X POST http://localhost:7842/api/board-session \
  -H "Content-Type: application/json" \
  -d '{
    "mode": "health_scan",
    "raw_paste": "Engineering team is 3 sprints behind on the payments project. Product team has conflicting priorities between the mobile roadmap and the API platform. Two open senior engineer roles unfilled for 6 weeks."
  }'
```

This returns a `session_id` immediately. Poll for the result:

```bash
curl http://localhost:7842/api/board-status/SESSION_ID
```

When `status` is `"done"`, the `result` field contains the full `BoardBriefing`.

### Test integration connections

```bash
curl -X POST http://localhost:7842/api/board-health \
  -H "Content-Type: application/json" \
  -d '{"check_jira": true, "check_linear": true, "check_notion": true, "check_slack": true}'
```

---

## 7. Board Session with Integrations

To pull live data from Jira + Notion + Slack into a weekly review:

```bash
curl -X POST http://localhost:7842/api/board-session \
  -H "Content-Type: application/json" \
  -d '{
    "mode": "weekly_review",
    "data_sources": ["jira", "notion", "slack"]
  }'
```

To include documents from a folder:

```bash
curl -X POST http://localhost:7842/api/board-session \
  -H "Content-Type: application/json" \
  -d '{
    "mode": "weekly_review",
    "data_sources": ["jira", "linear", "notion", "slack", "documents"],
    "document_folder": "/path/to/meeting-notes"
  }'
```

---

## 8. Interview Cognitive Memory (Pluely integration)

No separate server or process — this is the same FastAPI app started in step 5, exposing more routes under `/v1/interview/*` alongside the existing `/api/*` ones. Any local app that can make an HTTP request to `http://localhost:7842` can use it: `curl`, the Chrome extension (already covered by `cors_origins`), or Pluely (the desktop interview-coaching app this was built for — see `docs/openresearch-integration-requirements.md`). There's no auth on these endpoints yet, so anything on the same machine can call them.

Set up a candidate's profile and answer bank first:

```bash
curl -X PUT http://localhost:7842/v1/interview/profile/cand_demo \
  -H "Content-Type: application/json" \
  -d '{
    "candidate_id": "cand_demo",
    "resume_text": "Senior backend engineer, 8 years, distributed systems.",
    "job_description_text": "Staff engineer, platform team.",
    "custom_instructions": "Keep answers concise and specific."
  }'

curl -X POST http://localhost:7842/v1/interview/answer-bank/cand_demo \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Scaling the payments queue",
    "content": "We hit a throughput ceiling at 2k msgs/sec...",
    "category": "story",
    "tags": ["scaling", "distributed-systems"]
  }'
```

Ask a live question (streams back as Server-Sent Events):

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

`-N` disables curl's output buffering so you actually see the chunks arrive rather than the whole response at once — see `docs/openresearch-integration-requirements.md` §2 for why "arrive" here means chunked-after-generation, not true token streaming yet.

Run the pre-interview SM-2 drill skill (questions answered live above become drillable here too — both skills share the same candidate memory):

```bash
curl http://localhost:7842/v1/interview/skills

curl -X POST http://localhost:7842/v1/interview/skills/pre_interview_drill/apply \
  -H "Content-Type: application/json" \
  -d '{"candidate_id": "cand_demo", "args": {"action": "due_today"}}'
```

See `docs/openresearch-integration-requirements.md` §6/§6.2 for the full design and implementation-status notes, including what's still a placeholder (dedup/topic-guess thresholds, mastery-decay policy) versus load-bearing.

---

## Troubleshooting

### `Stock pipeline not initialized`

Your `llm.provider_chain` in `config.yaml` has no valid API key. Check that `api_key` is set and non-empty for at least one provider.

### `LLM returned empty response`

Usually means the model name is wrong or the API key doesn't have access to that model. Check the `model` field in your provider chain entry.

### Jira 401 Unauthorized

The email and API token combination is wrong. Make sure you're using a Jira API token (not your Atlassian account password) and the email matches your Atlassian account.

### Notion 401 Unauthorized

The integration token is correct but the database hasn't been shared with the integration. Open the database in Notion → Share → invite your integration by name.

### Slack `not_in_channel` error

The bot hasn't been invited to the channel. Run `/invite @yourbot` in the channel from a Slack client.

### Documents not loading

Check that `folder_path` exists and the files are `.docx`, `.pdf`, `.txt`, or `.md`. Files are silently skipped if they exceed `max_file_mb` — check the server log for "Skipping large file" messages.

### Local LLM returning errors

Make sure the model name in config matches exactly what LM Studio or Ollama shows. For LM Studio, check the model identifier in the Local Server tab. For Ollama, run `ollama list` to see loaded model names.

---

## Running as a Background Service (optional)

### Windows — using nssm

```powershell
nssm install openresearch "C:\Python311\python.exe" "C:\path\to\openresearch\server.py"
nssm set openresearch AppDirectory "C:\path\to\openresearch"
nssm start openresearch
```

### macOS/Linux — using a simple shell script

```bash
nohup python server.py > server.log 2>&1 &
echo $! > server.pid
```

Stop it:

```bash
kill $(cat server.pid)
```

---

## Next Steps

- Read [design.md](design.md) for the full architecture and design decisions
- Check [README.md](README.md) for the complete API reference and schema documentation
