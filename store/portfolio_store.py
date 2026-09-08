"""
PortfolioStore — persistent local storage for portfolio holdings.

Same atomic-JSON-write pattern as WatchlistStore (store/watchlist_store.py).
Unlike the watchlist there's no ticker cap — a portfolio's size is bounded
by what the user actually holds, not an arbitrary UI limit.
"""

import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from schemas.portfolio import PortfolioHolding

logger = logging.getLogger(__name__)

_DEFAULT_PATH = Path("data") / "portfolio.json"
_lock = threading.Lock()


class PortfolioStore:
    def __init__(self, path: Path | str = _DEFAULT_PATH):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> list[PortfolioHolding]:
        if not self.path.exists():
            return []
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
            return [PortfolioHolding(**item) for item in data]
        except Exception as e:
            logger.error(f"PortfolioStore.load failed: {e}")
            return []

    def upsert(self, ticker: str, shares: float, cost_basis: Optional[float] = None) -> list[PortfolioHolding]:
        ticker = ticker.upper().strip()
        with _lock:
            items = self.load()
            existing = next((i for i in items if i.ticker == ticker), None)
            if existing is not None:
                items = [i for i in items if i.ticker != ticker]
            items.append(PortfolioHolding(
                ticker=ticker,
                shares=shares,
                cost_basis=cost_basis,
                added_at=existing.added_at if existing else datetime.now(timezone.utc).isoformat(),
            ))
            self._save(items)
            return items

    def remove(self, ticker: str) -> list[PortfolioHolding]:
        ticker = ticker.upper().strip()
        with _lock:
            items = [i for i in self.load() if i.ticker != ticker]
            self._save(items)
            return items

    def _save(self, items: list[PortfolioHolding]) -> None:
        tmp = self.path.with_suffix(".tmp")
        try:
            tmp.write_text(
                json.dumps([i.model_dump() for i in items], indent=2),
                encoding="utf-8",
            )
            tmp.replace(self.path)
        except Exception as e:
            tmp.unlink(missing_ok=True)
            logger.error(f"PortfolioStore.save failed: {e}")
            raise

    @classmethod
    def from_config(cls, config_path: str = "config.yaml") -> "PortfolioStore":
        import yaml
        with open(config_path) as f:
            cfg = yaml.safe_load(f)
        data_dir = cfg.get("stock_research", {}).get("data_dir", "data")
        return cls(Path(data_dir) / "portfolio.json")
