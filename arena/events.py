import json
import os
import time
from typing import Any, Dict, List

import numpy as np

SCHEMA_VERSION = 1


def _default(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, (np.ndarray, set, frozenset, tuple)):
        return list(o.tolist() if isinstance(o, np.ndarray) else o)
    if hasattr(o, "dict"):
        return o.dict()
    return str(o)


class EventLog:
    r"""Append-only JSONL event log for one game attempt.

    Every event is flushed and fsync'd so a crash loses at most the line being written.
    """

    def __init__(self, path: str, run_id: str, game_idx: int, attempt: int = 0):
        self.path = path
        self.run_id = run_id
        self.game_idx = game_idx
        self.attempt = attempt
        self.seq = 0
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self._f = open(path, "a", encoding="utf-8")

    def emit(self, type: str, **data: Any) -> Dict[str, Any]:
        event = {
            "v": SCHEMA_VERSION,
            "run_id": self.run_id,
            "game_idx": self.game_idx,
            "attempt": self.attempt,
            "seq": self.seq,
            "ts": time.time(),
            "type": type,
            "data": data,
        }
        self._f.write(json.dumps(event, default=_default, ensure_ascii=False) + "\n")
        self._f.flush()
        os.fsync(self._f.fileno())
        self.seq += 1
        return event

    def close(self):
        if not self._f.closed:
            self._f.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def read_events(path: str) -> List[Dict[str, Any]]:
    r"""Read a JSONL event log, ignoring a truncated final line from an interrupted write."""
    events = []
    with open(path, encoding="utf-8") as f:
        lines = f.readlines()
    for i, line in enumerate(lines):
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            if i == len(lines) - 1:
                break
            raise
    return events
