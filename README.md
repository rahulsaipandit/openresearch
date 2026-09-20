# openresearch

Openresearch is an autonomous ML research assistant that turns a dataset and a goal into a tested set of baselines, clear comparisons, and a research starter pack you can build on. It is designed for researchers and builders who want credible experiments without spending days wiring the pipeline.

## Why openresearch

Most research time is not spent on modeling. It is spent on wiring data, running repeated baselines, chasing errors, and formatting results. openresearch automates that first pass so you can focus on ideas and analysis instead of plumbing.

Use it when you need:
- Fast, reproducible baselines
- Clear tradeoffs across methods
- A structured report with artifacts you can share
- A research draft you can refine

## What you get

After a run, openresearch writes a research starter pack to the output directory:
- `data_report.html` for EDA, diagnostics, and dataset risks
- `method_comparison.html` to compare metrics and runtime
- `notebooks/` with one notebook per method for reproducibility
- `best_model/` with saved artifacts and metadata
- `paper_draft.docx` as an editable draft outline

## How it works

```
Problem statement
  -> Problem Analyst
  -> EDA Agent
  -> Method Formulator
  -> Code Generator
  -> Execution Agent (Kaggle kernels)
  -> Evaluator
  -> Paper Writer
```

## Features

- Problem analysis that infers task type and target
- Dataset diagnostics for missing values, leakage, imbalance, and size risks
- Automatic method selection based on dataset characteristics
- Parallelized Kaggle execution with retries and timeouts
- Robust error capture and failure summaries
- Clear scoring across performance, speed, interpretability, and robustness

## Requirements

- Python 3.11+
- Kaggle account and API token
- LLM API key (Anthropic, OpenAI, or [MiniMax](https://platform.minimax.io))

## Quickstart

### 1. Install

```bash
pip install autoresearch
```

### 2. Configure

Edit `config.yaml` and add your keys plus your problem and data source.

```yaml
api_keys:
  anthropic: "YOUR_KEY"
  openai: "YOUR_KEY"
  minimax: "YOUR_KEY"           # optional — https://platform.minimax.io
  kaggle_username: "YOUR_USERNAME"
  kaggle_key: "YOUR_KAGGLE_KEY"

problem:
  statement: "Predict churn from customer features"
  data_source:
    type: "kaggle"
    identifier: "username/dataset"
```

### 3. Run

```bash
autoresearch run
```

## Running the API server (Pluely / desktop app integration)

Beyond the CLI pipeline above, this repo also runs as a local FastAPI server (`server.py`) — the backend for the desktop app (`desktop/`) and for the Pluely Interview Assistant integration (candidate-scoped cognitive memory: résumé/JD grounding, answer bank, live retrieval-grounded answers).

**Quick run (after the 1st install):**

```powershell
.venv\Scripts\python.exe server.py
```

Always invoke `.venv\Scripts\python.exe` by its full path — don't `.\activate` and then run bare `python.exe`. If this machine has more than one Python installed, activation can leave `python` resolving to the wrong one, and a mismatched interpreter silently recreates a broken venv (see the pinned version note below).

### 1. Install dependencies into a project venv

If more than one Python version is installed on this machine, **pin the version explicitly** — a bare `python -m venv .venv` picks whatever `python` happens to resolve to, which can silently create a venv on the wrong version. `pydantic_core` (a pinned FastAPI/Pydantic dependency) ships version-specific compiled wheels (e.g. `cp312`), so a venv built on the wrong interpreter fails at import time with `ModuleNotFoundError: No module named 'pydantic_core._pydantic_core'` — the underlying `.pyd` simply doesn't match the interpreter's ABI. This project is tested on **Python 3.12**:

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -e .
```

(No `py` launcher, or only one Python installed? Plain `python -m venv .venv` is fine — just confirm with `python --version` first.)

### 2. Configure an LLM provider

Edit `config.yaml`'s `llm.provider_chain` — a cloud provider (Anthropic/OpenAI/MiniMax) or a local model via LM Studio/Ollama (`provider: openai_compatible`). See `docs/SETUP.md` for details.

### 3. Start the server

```bash
.venv\Scripts\python.exe server.py
```

```
OpenResearch Server
Running at http://127.0.0.1:7842
```

### 4. Verify it's up

```bash
curl http://localhost:7842/api/health
```

### What Pluely talks to

- `POST /v1/interview/answer` — the live-coaching endpoint (Server-Sent Events streaming), accepts an optional `images` field for a candidate's screenshot
- `GET/PUT /v1/interview/profile/{candidate_id}` — résumé/JD/custom instructions
- `GET/POST /v1/interview/answer-bank/{candidate_id}`, `PUT/DELETE .../{entry_id}` — the candidate's personal answer bank (stories, prepared answers, talking points; entries can carry attached images)
- `GET /v1/interview/skills`, `POST /v1/interview/skills/{skill_name}/apply` — e.g. `pre_interview_drill`'s SM-2 spaced-repetition practice

Full request/response contracts, a step-by-step curl walkthrough, and open integration items are in `docs/SETUP.md` (§8) and `docs/openresearch-integration-requirements.md`.

## Running the desktop UI

The desktop app (`desktop/`) is a Tauri + React frontend for the API server above. Start the backend first, then the UI in a separate terminal.

**1. Start the backend** (from the repo root):

```powershell
.venv\Scripts\python.exe server.py
```

**2. Run the desktop app:**

```powershell
cd desktop
npm install   # first time only
npm run tauri dev
```

This launches the native Tauri window with the Vite dev server behind it, talking to the FastAPI backend at `http://127.0.0.1:7842`.

To iterate on the frontend alone in a browser (skipping the native shell), use `npm run dev` instead and open the printed Vite URL — note that Tauri-specific APIs (via `@tauri-apps/api`) won't be available outside the native shell.

## Typical workflow

1. Provide a plain English problem statement
2. Point to a dataset (Kaggle, local CSV, or HuggingFace)
3. openresearch runs EDA and proposes methods
4. Kernels execute in parallel with progress tracking
5. You receive a report, notebooks, and a best model

## Use cases

- Academic baselines for new datasets
- Internal model selection with limited engineering time
- Fast feasibility checks before investing in large experiments

## Examples

See `examples/` for sample configs and expected outputs.

## Contributing

See `CONTRIBUTING.md`.

## License

MIT
