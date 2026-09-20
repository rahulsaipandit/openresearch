"""
AlertStore — persistent local storage for stock price alerts.

Checked every 5 minutes by the background poller started in server.py's
lifespan. Adapted from OpenStock's Inngest-cron `checkStockAlerts` pattern
(docs/researchStockSolutions.md), using a plain asyncio loop instead since
this is the only scheduled job in the app and doesn't warrant pulling in a
job-scheduling framework. Atomic JSON write, same pattern as
WatchlistStore.
"""

import json
import logging
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from schemas.alert import PriceAlert

logger = logging.getLogger(__name__)

_DEFAULT_PATH = Path("data") / "alerts.json"
_lock = threading.Lock()


class AlertStore:
    def __init__(self, path: Path | str = _DEFAULT_PATH):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> list[PriceAlert]:
        if not self.path.exists():
            return []
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
            return [PriceAlert(**item) for item in data]
        except Exception as e:
            logger.error(f"AlertStore.load failed: {e}")
            return []

    def add(self, ticker: str, condition: str, target_price: float) -> list[PriceAlert]:
        ticker = ticker.upper().strip()
        with _lock:
            items = self.load()
            items.append(PriceAlert(
                id=uuid.uuid4().hex[:12],
                ticker=ticker,
                condition=condition,
                target_price=target_price,
                created_at=datetime.now(timezone.utc).isoformat(),
            ))
            self._save(items)
            return items

    def remove(self, alert_id: str) -> list[PriceAlert]:
        with _lock:
            items = [i for i in self.load() if i.id != alert_id]
            self._save(items)
            return items

    def mark_triggered(self, alert_id: str, price: float) -> None:
        with _lock:
            items = self.load()
            for item in items:
                if item.id == alert_id:
                    item.triggered = True
                    item.active = False
                    item.triggered_at = datetime.now(timezone.utc).isoformat()
                    item.triggered_price = price
            self._save(items)

    def active_alerts(self) -> list[PriceAlert]:
        return [i for i in self.load() if i.active and not i.triggered]

    def _save(self, items: list[PriceAlert]) -> None:
        tmp = self.path.with_suffix(".tmp")
        try:
            tmp.write_text(
                json.dumps([i.model_dump() for i in items], indent=2),
                encoding="utf-8",
            )
            tmp.replace(self.path)
        except Exception as e:
            tmp.unlink(missing_ok=True)
            logger.error(f"AlertStore.save failed: {e}")
            raise

    @classmethod
    def from_config(cls, config_path: str = "config.yaml") -> "AlertStore":
        import yaml
        with open(config_path) as f:
            cfg = yaml.safe_load(f)
        data_dir = cfg.get("stock_research", {}).get("data_dir", "data")
        return cls(Path(data_dir) / "alerts.json")
