"""
OptionsHistoryStore — trailing put/call-ratio history so OptionsAnalyst can
flag "unusual" activity against a ticker's own recent average rather than
just an absolute number. Same atomic JSON-write pattern as AlertStore /
WatchlistStore — this app has no other persistence layer and one more
ticker-keyed JSON file doesn't warrant pulling in SQLite.
"""

import json
import logging
import threading
from datetime import date, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

_DEFAULT_PATH = Path("data") / "options_history.json"
_lock = threading.Lock()
_MAX_ROWS_KEPT = 60  # more than enough for a 30-day trailing average


class OptionsHistoryStore:
    def __init__(self, path: Path | str = _DEFAULT_PATH):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, ticker: str, iso_date: str, put_call_ratio: float | None) -> None:
        if put_call_ratio is None:
            return
        ticker = ticker.upper().strip()
        with _lock:
            data = self._load()
            rows = [r for r in data.get(ticker, []) if r.get("date") != iso_date]
            rows.append({"date": iso_date, "ratio": put_call_ratio})
            rows.sort(key=lambda r: r["date"])
            data[ticker] = rows[-_MAX_ROWS_KEPT:]
            self._save(data)

    def trailing_average(self, ticker: str, days: int = 30, exclude_today: bool = True) -> float | None:
        ticker = ticker.upper().strip()
        rows = self._load().get(ticker, [])
        cutoff = (date.today() - timedelta(days=days)).isoformat()
        today_iso = date.today().isoformat()
        values = [
            r["ratio"] for r in rows
            if r["date"] >= cutoff and not (exclude_today and r["date"] == today_iso)
        ]
        return sum(values) / len(values) if values else None

    def _load(self) -> dict:
        if not self.path.exists():
            return {}
        try:
            with open(self.path, encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"OptionsHistoryStore.load failed: {e}")
            return {}

    def _save(self, data: dict) -> None:
        tmp = self.path.with_suffix(".tmp")
        try:
            tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
            tmp.replace(self.path)
        except Exception as e:
            tmp.unlink(missing_ok=True)
            logger.error(f"OptionsHistoryStore.save failed: {e}")
            raise

    @classmethod
    def from_config(cls, config_path: str = "config.yaml") -> "OptionsHistoryStore":
        import yaml
        with open(config_path) as f:
            cfg = yaml.safe_load(f)
        data_dir = cfg.get("stock_research", {}).get("data_dir", "data")
        return cls(Path(data_dir) / "options_history.json")
