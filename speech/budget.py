"""
Boson AI API Call Budget & Usage Tracker.

Safeguards against runaway costs and ensures overnight or benchmark runs
stay strictly within safe limits (default 500 API calls).
Tracks call counts, timestamped logs, and bytes/characters synthesized.
"""

import os
import json
import time
from pathlib import Path
from typing import Dict, Any, Optional

DEFAULT_BUDGET_LIMIT = int(os.getenv("BOSON_MAX_CALLS", "500"))


class BosonBudgetTracker:
    """
    Persisted budget tracker for Boson API calls.
    """

    def __init__(
        self,
        max_calls: int = DEFAULT_BUDGET_LIMIT,
        log_file: Optional[Path] = None,
    ):
        self.max_calls = max_calls
        self.log_file = log_file or Path("audio_cache") / "budget_tracker.json"
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        self._load()

    def _load(self):
        if self.log_file.exists():
            try:
                data = json.loads(self.log_file.read_text(encoding="utf-8"))
                self.calls_count = data.get("total_calls", 0)
                self.history = data.get("history", [])
            except Exception:
                self.calls_count = 0
                self.history = []
        else:
            self.calls_count = 0
            self.history = []

    def _save(self):
        try:
            data = {
                "max_calls": self.max_calls,
                "total_calls": self.calls_count,
                "remaining_calls": max(0, self.max_calls - self.calls_count),
                "history": self.history[-100:],  # keep last 100 entries for audit
            }
            self.log_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception as e:
            print(f"[Budget Tracker Warning] Failed to save budget log: {e}")

    def can_call(self) -> bool:
        """Returns True if the budget limit has not been exceeded."""
        return self.calls_count < self.max_calls

    def remaining_budget(self) -> int:
        """Returns remaining number of permitted API calls."""
        return max(0, self.max_calls - self.calls_count)

    def record_call(
        self,
        endpoint: str,
        voice: str,
        text_length: int,
        status_code: int,
        byte_size: int = 0,
        extra: Optional[Dict[str, Any]] = None,
    ):
        """
        Records an API call. Increments total calls if status_code indicates success or billed request.
        """
        self.calls_count += 1
        entry = {
            "timestamp": time.time(),
            "iso_time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "endpoint": endpoint,
            "voice": voice,
            "chars": text_length,
            "bytes": byte_size,
            "status": status_code,
            "total_calls_so_far": self.calls_count,
        }
        if extra:
            entry.update(extra)
        self.history.append(entry)
        self._save()

    def reset(self):
        """Resets the usage counter."""
        self.calls_count = 0
        self.history = []
        self._save()

    def get_summary(self) -> Dict[str, Any]:
        return {
            "total_calls": self.calls_count,
            "max_calls": self.max_calls,
            "remaining": self.remaining_budget(),
            "limit_reached": not self.can_call(),
        }


# Global singleton instance
global_budget_tracker = BosonBudgetTracker()
