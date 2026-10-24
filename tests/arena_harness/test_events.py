import json

import numpy as np
import pytest

from arena.events import EventLog, read_events


def test_round_trip(tmp_path):
    path = str(tmp_path / "g" / "game.jsonl")
    with EventLog(path, run_id="r", game_idx=4, attempt=1) as log:
        log.emit("game_start", seed=[0, 4])
        log.emit("team_proposed", team=frozenset({1, 2}), leader=np.int64(3), ok=np.bool_(True))
    events = read_events(path)
    assert [e["type"] for e in events] == ["game_start", "team_proposed"]
    assert [e["seq"] for e in events] == [0, 1]
    assert all(e["run_id"] == "r" and e["game_idx"] == 4 and e["attempt"] == 1 for e in events)
    assert sorted(events[1]["data"]["team"]) == [1, 2]
    assert events[1]["data"]["leader"] == 3 and events[1]["data"]["ok"] is True


def test_truncated_last_line_is_ignored(tmp_path):
    path = str(tmp_path / "game.jsonl")
    with EventLog(path, run_id="r", game_idx=0) as log:
        log.emit("a")
        log.emit("b")
    with open(path, "a") as f:
        f.write('{"type": "c", "da')
    assert [e["type"] for e in read_events(path)] == ["a", "b"]


def test_corrupt_middle_line_raises(tmp_path):
    path = tmp_path / "game.jsonl"
    path.write_text('{"type": "a"}\n{bad\n' + json.dumps({"type": "b"}) + "\n")
    with pytest.raises(json.JSONDecodeError):
        read_events(str(path))
