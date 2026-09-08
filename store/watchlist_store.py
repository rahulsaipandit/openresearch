"""
WatchlistStore — persistent local storage for the stock watchlist.

Enforces the 20-ticker cap (requirement #4). Atomic JSON write, same pattern
as ProfileStore.
"""

import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from schemas.watchlist import WatchlistItem

logger = logging.getLogger(__name__)

_DEFAULT_PATH = Path("data") / "watchlist.json"
_MAX_ITEMS = 20
_lock = threading.Lock()


class WatchlistStore:
    def __init__(self, path: Path | str = _DEFAULT_PATH):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> list[WatchlistItem]:
        if not self.path.exists():
            return []
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
            return [WatchlistItem(**item) for item in data]
        except Exception as e:
            logger.error(f"WatchlistStore.load failed: {e}")
            return []

    def add(self, ticker: str, notes: Optional[str] = None) -> list[WatchlistItem]:
        ticker = ticker.upper().strip()
        with _lock:
            items = self.load()
            if any(i.ticker == ticker for i in items):
                return items
            if len(items) >= _MAX_ITEMS:
                raise ValueError(f"Watchlist is full ({_MAX_ITEMS} tickers max).")
            items.append(WatchlistItem(
                ticker=ticker,
                added_at=datetime.now(timezone.utc).isoformat(),
                notes=notes,
            ))
            self._save(items)
            return items

    def remove(self, ticker: str) -> list[WatchlistItem]:
        ticker = ticker.upper().strip()
        with _lock:
            items = [i for i in self.load() if i.ticker != ticker]
            self._save(items)
            return items

    def _save(self, items: list[WatchlistItem]) -> None:
        tmp = self.path.with_suffix(".tmp")
        try:
            tmp.write_text(
                json.dumps([i.model_dump() for i in items], indent=2),
                encoding="utf-8",
            )
            tmp.replace(self.path)
        except Exception as e:
            tmp.unlink(missing_ok=True)
            logger.error(f"WatchlistStore.save failed: {e}")
            raise

    @classmethod
    def from_config(cls, config_path: str = "config.yaml") -> "WatchlistStore":
        import yaml
        with open(config_path) as f:
            cfg = yaml.safe_load(f)
        data_dir = cfg.get("stock_research", {}).get("data_dir", "data")
        return cls(Path(data_dir) / "watchlist.json")
