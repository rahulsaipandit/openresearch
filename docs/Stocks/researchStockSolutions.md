# Research: OpenStock — Real-Time Stock Price Fetching & Tracking

Source: [Open-Dev-Society/OpenStock](https://github.com/Open-Dev-Society/OpenStock) (Next.js app)

## Data source

Finnhub REST API (`https://finnhub.io/api/v1`), authenticated via `NEXT_PUBLIC_FINNHUB_API_KEY`. No WebSocket connection to Finnhub is used — everything is plain HTTP polling.

## Core fetch logic

[`lib/actions/finnhub.actions.ts`](https://github.com/Open-Dev-Society/OpenStock/blob/main/lib/actions/finnhub.actions.ts):

- `getQuote(symbol)` calls `GET /quote?symbol=...` and explicitly uses `cache: 'no-store'` — "No caching for real-time price" is called out in a comment, so every call hits Finnhub fresh.
- `getCompanyProfile(symbol)` hits `/stock/profile2` but *is* cached for 24h (`next: { revalidate: 86400 }`) since company metadata rarely changes.
- `getWatchlistData(symbols)` fans out `Promise.all` over `getQuote` + `getCompanyProfile` per symbol to build the watchlist rows (price, change, changePercent, currency, name, logo, marketCap).
- These are all Next.js **Server Actions** (`'use server'`) — prices are fetched server-side, not directly from the browser.

## "Real-time" is really scheduled polling, not push

- The watchlist page ([`app/(root)/watchlist/page.tsx`](https://github.com/Open-Dev-Society/OpenStock/blob/main/app/(root)/watchlist/page.tsx)) is a server component that fetches watchlist/news data on each page load/request — no client-side `setInterval` polling loop or WebSocket subscription was found in `hooks/` or the watchlist components.
- Actual continuous tracking happens via an **Inngest cron job**, `checkStockAlerts` in [`lib/inngest/functions.ts`](https://github.com/Open-Dev-Society/OpenStock/blob/main/lib/inngest/functions.ts), scheduled `*/5 * * * *` (every 5 minutes). It:
  1. Loads active, untriggered, unexpired alerts from MongoDB.
  2. Dedupes symbols and calls `getQuote()` for each.
  3. Compares `quote.c` (current price) against each alert's `targetPrice`/`condition` (`ABOVE`/`BELOW`).
  4. Marks matching alerts `triggered: true` and logs (notification/email sending for triggers is stubbed — only `console.log`, not wired to Kit/email yet).

## Charting

Uses TradingView's own embedded widget ([`hooks/useTradingViewWidget.tsx`](https://github.com/Open-Dev-Society/OpenStock/blob/main/hooks/useTradingViewWidget.tsx)), which injects TradingView's script tag directly — that live-price/chart stream comes entirely from TradingView's client-side widget, not from OpenStock's own backend or Finnhub. A `utils.ts` helper (`formatSymbolForTradingView`) maps Finnhub's dot-suffix exchange codes (e.g. `2330.TW`) to TradingView's colon-prefix format (`TWSE:2330`) so the correct chart loads.

## Summary

No true real-time streaming (no WebSocket/SSE to Finnhub) — it's request-time REST polling for on-demand quotes (watchlist views, search) plus a 5-minute cron sweep for alert-checking, with TradingView's embedded widget handling actual live chart ticking independently.
