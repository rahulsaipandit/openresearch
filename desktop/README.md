# OpenResearch Desktop (Tauri)

Shared desktop shell for all four OpenResearch verticals (Stock Research,
Executive Board, Interview Prep, Real Estate) — see
`docs/Finance-AI/docs/requirements.md` for the architecture decision this
implements (Tauri replaces the previously-planned, never-built Chrome
Extension).

The frontend talks directly to the existing FastAPI backend at
`http://127.0.0.1:7842` (`server.py`) — no new backend framework, just new
endpoints on the server that already exists.

## Setup

```bash
cd desktop
npm install
```

Requires Rust + Cargo (already present in this environment) and, on
Windows, the WebView2 runtime (preinstalled on Windows 11).

## Run

1. Start the Python backend first, from the repo root:
   ```bash
   python server.py
   ```
2. Then, from `desktop/`:
   ```bash
   npm run tauri dev
   ```

`npm run dev` alone runs just the Vite dev server in a regular browser tab
(useful for quick iteration without the native window).

## What's implemented

- **Stock Research** panel: natural-language query box (`/api/query`),
  structured result view with cited text, fundamentals table, bull/bear case.
- **Watchlist** panel: add/remove up to 20 tickers, one-click analyze.
- **Compare** panel: two-ticker side-by-side comparison with a P/E bar chart.
- **Trend** panel: five-year price chart, annual revenue/net-income chart,
  computed previous-year summary.
- **Board / Interview / Real Estate**: thin result-rendering panels calling
  their existing endpoints — no new backend logic, per requirements.md.

## Known gaps / not yet done in this pass

- **App icons** (`src-tauri/icons/`) are not generated — required for
  `tauri build` (a distributable bundle), not for `tauri dev`. Run
  `npm run tauri icon <path-to-a-1024x1024-png>` before attempting a release
  build.
- **Not yet build-tested end-to-end** (`cargo build` / `tauri dev`) in this
  session — only `npm install`, `tsc`, and `vite build` were run to validate
  the TypeScript/React code compiles cleanly. The Rust/Tauri side follows the
  standard Tauri v2 + Vite template structure but hasn't been compiled here.
- Earnings-call summarization (requirement #5) and the personal memory
  system have no backend endpoint yet, so there's no panel for them.
- Board/Interview/RealEstate panels render raw JSON for now — they're
  functional passthroughs, not polished result views.
