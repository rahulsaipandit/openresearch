import { useEffect, useState } from "react";
import {
  addToWatchlist,
  createAlert,
  deleteAlert,
  getAlerts,
  getWatchlist,
  getWatchlistQuotes,
  removeFromWatchlist,
  runStockResearch,
} from "../api";
import type { PriceAlert, Quote, ResearchBrief, WatchlistItem } from "../types";
import { ContentDialog } from "../components/ContentDialog";

// Live quotes are polled, not pushed — see docs/researchStockSolutions.md
// (adapted from OpenStock's getQuote()/checkStockAlerts() pattern, on a
// 5-minute cadence to match the server-side alert poller in server.py).
const QUOTE_POLL_INTERVAL_MS = 5 * 60 * 1000;

// Requirement #4: watchlist of up to 20 stocks, one-click analysis.
export function WatchlistPanel() {
  const [items, setItems] = useState<WatchlistItem[]>([]);
  const [quotes, setQuotes] = useState<Record<string, Quote>>({});
  const [alerts, setAlerts] = useState<PriceAlert[]>([]);
  const [newTicker, setNewTicker] = useState("");
  const [alertTicker, setAlertTicker] = useState("");
  const [alertCondition, setAlertCondition] = useState<"ABOVE" | "BELOW">("ABOVE");
  const [alertPrice, setAlertPrice] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [analyzing, setAnalyzing] = useState<string | null>(null);
  const [brief, setBrief] = useState<ResearchBrief | null>(null);

  async function refresh() {
    const res = await getWatchlist();
    setItems(res.watchlist);
  }

  async function refreshQuotes() {
    try {
      const res = await getWatchlistQuotes();
      setQuotes(Object.fromEntries(res.quotes.map((q) => [q.ticker, q])));
    } catch {
      // Quotes are a nice-to-have overlay — a failed poll shouldn't disrupt the page.
    }
  }

  async function refreshAlerts() {
    try {
      const res = await getAlerts();
      setAlerts(res.alerts);
    } catch {
      // Same as refreshQuotes — non-critical background refresh.
    }
  }

  useEffect(() => {
    refresh().catch((e) => setError(e instanceof Error ? e.message : String(e)));
    refreshQuotes();
    refreshAlerts();
    const interval = setInterval(refreshQuotes, QUOTE_POLL_INTERVAL_MS);
    return () => clearInterval(interval);
  }, []);

  async function handleAdd() {
    if (!newTicker.trim()) return;
    try {
      const res = await addToWatchlist(newTicker.trim());
      setItems(res.watchlist);
      setNewTicker("");
      setError(null);
      refreshQuotes();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  async function handleRemove(ticker: string) {
    const res = await removeFromWatchlist(ticker);
    setItems(res.watchlist);
  }

  async function handleAnalyze(ticker: string) {
    setAnalyzing(ticker);
    setError(null);
    try {
      const b = await runStockResearch(ticker, "quick");
      setBrief(b);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setAnalyzing(null);
    }
  }

  async function handleCreateAlert() {
    const price = parseFloat(alertPrice);
    if (!alertTicker.trim() || Number.isNaN(price)) return;
    try {
      const res = await createAlert(alertTicker.trim().toUpperCase(), alertCondition, price);
      setAlerts(res.alerts);
      setAlertTicker("");
      setAlertPrice("");
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  async function handleRemoveAlert(id: string) {
    const res = await deleteAlert(id);
    setAlerts(res.alerts);
  }

  return (
    <div>
      <h3>
        Watchlist ({items.length}/20)
      </h3>
      <div className="query-box">
        <input
          value={newTicker}
          onChange={(e) => setNewTicker(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleAdd()}
          placeholder="Add ticker, e.g. AAPL"
        />
        <button type="button" onClick={handleAdd} disabled={items.length >= 20}>
          Add
        </button>
      </div>
      {error && <div className="error-banner">{error}</div>}

      <ul className="watchlist-grid">
        {items.map((item) => {
          const quote = quotes[item.ticker];
          const changeClass =
            quote?.change_percent == null ? "" : quote.change_percent >= 0 ? "text-positive" : "text-negative";
          return (
            <li key={item.ticker} className="watchlist-row">
              <span className="ticker">{item.ticker}</span>
              {quote?.price != null ? (
                <span className={`quote ${changeClass}`}>
                  {quote.price.toFixed(2)}
                  {quote.change_percent != null &&
                    ` (${quote.change_percent >= 0 ? "+" : ""}${quote.change_percent.toFixed(2)}%)`}
                </span>
              ) : (
                <span className="quote quote-loading">—</span>
              )}
              <span className="added-at">added {new Date(item.added_at).toLocaleDateString()}</span>
              <button type="button" onClick={() => handleAnalyze(item.ticker)} disabled={analyzing === item.ticker}>
                {analyzing === item.ticker ? "..." : "Analyze"}
              </button>
              <button type="button" className="remove-btn" onClick={() => handleRemove(item.ticker)}>
                Remove
              </button>
            </li>
          );
        })}
        {items.length === 0 && <li className="empty-state">No stocks watched yet.</li>}
      </ul>

      <h4>Price Alerts</h4>
      <p className="disclaimer">Checked every 5 minutes against live prices.</p>
      <div className="query-box">
        <input
          value={alertTicker}
          onChange={(e) => setAlertTicker(e.target.value)}
          placeholder="Ticker, e.g. AAPL"
        />
        <select value={alertCondition} onChange={(e) => setAlertCondition(e.target.value as "ABOVE" | "BELOW")}>
          <option value="ABOVE">Above</option>
          <option value="BELOW">Below</option>
        </select>
        <input
          value={alertPrice}
          onChange={(e) => setAlertPrice(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleCreateAlert()}
          placeholder="Target price"
          type="number"
        />
        <button type="button" onClick={handleCreateAlert}>
          Create Alert
        </button>
      </div>

      <ul className="watchlist-grid">
        {alerts.map((alert) => (
          <li key={alert.id} className="watchlist-row">
            <span className="ticker">{alert.ticker}</span>
            <span>
              {alert.condition === "ABOVE" ? ">" : "<"} {alert.target_price}
            </span>
            <span>
              {alert.triggered
                ? `Triggered at ${alert.triggered_price} (${new Date(alert.triggered_at ?? "").toLocaleString()})`
                : "Active"}
            </span>
            <button type="button" className="remove-btn" onClick={() => handleRemoveAlert(alert.id)}>
              Remove
            </button>
          </li>
        ))}
        {alerts.length === 0 && <li className="empty-state">No price alerts set.</li>}
      </ul>

      <ContentDialog title={brief?.ticker ?? ""} open={brief !== null} onClose={() => setBrief(null)}>
        {brief && (
          <div>
            <p>
              <strong>{brief.verdict}</strong> — {brief.summary}
            </p>
          </div>
        )}
      </ContentDialog>
    </div>
  );
}
