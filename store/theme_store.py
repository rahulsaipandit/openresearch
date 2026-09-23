"""
ThemeStore — persistent storage for Opportunity Radar snapshots.

Same atomic-write JSON pattern as AlertStore/WatchlistStore/OptionsHistoryStore
— there is no SQL database anywhere else in this app, so this doesn't
introduce one for a single feature. Snapshots are keyed by the date the batch
job ran, so a future "yesterday vs. today" diff view is possible without a
storage change, even though nothing reads history yet — only latest().
"""

import json
import logging
import threading
from pathlib import Path

from schemas.opportunity_radar import OpportunityRadarResult

logger = logging.getLogger(__name__)

_DEFAULT_PATH = Path("data") / "opportunity_radar.json"
_lock = threading.Lock()
_MAX_SNAPSHOTS_KEPT = 30  # one month of daily runs is plenty until a diff view exists


class ThemeStore:
    def __init__(self, path: Path | str = _DEFAULT_PATH):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def save_snapshot(self, result: OpportunityRadarResult) -> None:
        with _lock:
            data = self._load()
            snapshots = [s for s in data.get("snapshots", []) if s.get("generated_at") != result.generated_at]
            snapshots.append(result.model_dump())
            snapshots.sort(key=lambda s: s["generated_at"])
            data["snapshots"] = snapshots[-_MAX_SNAPSHOTS_KEPT:]
            self._save(data)

    def latest(self) -> OpportunityRadarResult | None:
        snapshots = self._load().get("snapshots", [])
        if not snapshots:
            return None
        try:
            return OpportunityRadarResult(**snapshots[-1])
        except Exception as e:
            logger.error(f"ThemeStore.latest failed to parse snapshot: {e}")
            return None

    def _load(self) -> dict:
        if not self.path.exists():
            return {}
        try:
            with open(self.path, encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"ThemeStore.load failed: {e}")
            return {}

    def _save(self, data: dict) -> None:
        tmp = self.path.with_suffix(".tmp")
        try:
            tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
            tmp.replace(self.path)
        except Exception as e:
            tmp.unlink(missing_ok=True)
            logger.error(f"ThemeStore.save failed: {e}")
            raise

    @classmethod
    def from_config(cls, config_path: str = "config.yaml") -> "ThemeStore":
        import yaml
        with open(config_path) as f:
            cfg = yaml.safe_load(f)
        data_dir = cfg.get("stock_research", {}).get("data_dir", "data")
        return cls(Path(data_dir) / "opportunity_radar.json")
