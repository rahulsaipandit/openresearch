"""
ProfileStore — persistent local storage for the master candidate profile.

All data is written to a single JSON file on disk. Thread-safe for the
single-server use case via a file lock on write.

Usage:
    store = ProfileStore()
    store.save(profile)
    profile = store.load()          # None if no profile yet
    exists  = store.exists()
"""

import json
import logging
import threading
from pathlib import Path
from typing import Optional

from schemas.profile import MasterProfile

logger = logging.getLogger(__name__)

_DEFAULT_PATH = Path("data") / "profile.json"
_lock = threading.Lock()


class ProfileStore:
    def __init__(self, path: Path | str = _DEFAULT_PATH):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    # ── Read ──────────────────────────────────────────────────────────────────

    def load(self) -> Optional[MasterProfile]:
        """Load the master profile from disk. Returns None if it doesn't exist."""
        if not self.path.exists():
            return None
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
            return MasterProfile(**data)
        except Exception as e:
            logger.error(f"ProfileStore.load failed: {e}")
            return None

    def exists(self) -> bool:
        return self.path.exists()

    # ── Write ─────────────────────────────────────────────────────────────────

    def save(self, profile: MasterProfile) -> None:
        """Persist the master profile to disk (atomic write)."""
        with _lock:
            tmp = self.path.with_suffix(".tmp")
            try:
                tmp.write_text(
                    profile.model_dump_json(indent=2),
                    encoding="utf-8",
                )
                tmp.replace(self.path)
            except Exception as e:
                tmp.unlink(missing_ok=True)
                logger.error(f"ProfileStore.save failed: {e}")
                raise

    def delete(self) -> None:
        """Remove the stored profile."""
        with _lock:
            self.path.unlink(missing_ok=True)

    @classmethod
    def from_config(cls, config_path: str = "config.yaml") -> "ProfileStore":
        import yaml
        with open(config_path) as f:
            cfg = yaml.safe_load(f)
        data_dir = cfg.get("interview_research", {}).get("data_dir", "data")
        return cls(Path(data_dir) / "profile.json")
