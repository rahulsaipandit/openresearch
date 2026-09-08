import { useEffect, useState } from "react";
import { addToWatchlist, getWatchlist, removeFromWatchlist, runStockResearch } from "../api";
import type { ResearchBrief, WatchlistItem } from "../types";
import { ContentDialog } from "../components/ContentDialog";

// Requirement #4: watchlist of up to 20 stocks, one-click analysis.
export function WatchlistPanel() {
  const [items, setItems] = useState<WatchlistItem[]>([]);
  const [newTicker, setNewTicker] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [analyzing, setAnalyzing] = useState<string | null>(null);
  const [brief, setBrief] = useState<ResearchBrief | null>(null);

  async function refresh() {
    const res = await getWatchlist();
    setItems(res.watchlist);
  }

  useEffect(() => {
    refresh().catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, []);

  async function handleAdd() {
    if (!newTicker.trim()) return;
    try {
      const res = await addToWatchlist(newTicker.trim());
      setItems(res.watchlist);
      setNewTicker("");
      setError(null);
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
        {items.map((item) => (
          <li key={item.ticker} className="watchlist-row">
            <span className="ticker">{item.ticker}</span>
            <span className="added-at">added {new Date(item.added_at).toLocaleDateString()}</span>
            <button type="button" onClick={() => handleAnalyze(item.ticker)} disabled={analyzing === item.ticker}>
              {analyzing === item.ticker ? "..." : "Analyze"}
            </button>
            <button type="button" className="remove-btn" onClick={() => handleRemove(item.ticker)}>
              Remove
            </button>
          </li>
        ))}
        {items.length === 0 && <li className="empty-state">No stocks watched yet.</li>}
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
