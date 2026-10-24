import asyncio
import glob
import json
import os

import pytest

from arena.__main__ import summarize
from arena.events import read_events
from arena.retry import is_transient, retry_async
from arena.runner import game_path, run

from .conftest import make_cfg


class AvalonAgentActionException(Exception):
    pass


def fake_result(setup):
    return {
        "status": "completed",
        "winner": "good",
        "reason": "missions_and_assassin_missed",
        "quest_results": [True, True, True],
        "seats": [
            {"seat": i, "name": s.name, "agent": s.agent, "model": s.model, "role": setup.role_names[i],
             "side": "evil" if setup.role_names[i] in ("Assassin", "Minion") else "good",
             "won": setup.role_names[i] not in ("Assassin", "Minion"), "deduction_acc": 0.6}
            for i, s in enumerate(setup.seat_specs)
        ],
    }


def make_play_fn(calls, fail=None):
    r"""fail(game_idx, attempt_count) -> exception to raise, or None to succeed."""
    async def play(setup, cfg, log):
        n = calls.setdefault(setup.game_idx, 0)
        calls[setup.game_idx] = n + 1
        log.emit("game_start", seed=setup.seed, roles=setup.role_names,
                 participants=setup.seat_participants, leader=setup.quest_leader)
        await asyncio.sleep(0)
        exc = fail(setup.game_idx, n) if fail else None
        if exc is not None:
            raise exc
        return fake_result(setup)
    return play


def results(run_dir):
    with open(os.path.join(run_dir, "results.jsonl")) as f:
        return [json.loads(l) for l in f]


def test_runs_all_games_and_summarizes(tmp_path):
    cfg, run_dir, calls = make_cfg(), str(tmp_path / "run"), {}
    ends = asyncio.run(run(cfg, run_dir, play_fn=make_play_fn(calls), log_fn=lambda *_: None))
    assert len(ends) == 6 and set(calls) == set(range(6))
    for i in range(6):
        events = read_events(game_path(run_dir, i))
        assert [e["type"] for e in events] == ["game_start", "game_end"]
    assert len(results(run_dir)) == 6
    summary = summarize(run_dir)
    assert summary["statuses"] == {"completed": 6}
    assert sum(v["games"] for v in summary["by_participant"].values()) == 30


def test_transient_failure_is_retried(tmp_path):
    cfg, run_dir, calls = make_cfg(), str(tmp_path / "run"), {}
    fail = lambda idx, n: TimeoutError("slow") if idx == 2 and n == 0 else None
    asyncio.run(run(cfg, run_dir, play_fn=make_play_fn(calls, fail), log_fn=lambda *_: None))
    assert calls[2] == 2
    final = read_events(game_path(run_dir, 2))
    assert final[-1]["data"]["status"] == "completed" and final[0]["attempt"] == 1
    partials = glob.glob(os.path.join(run_dir, "games", "game_00002.attempt*.partial.jsonl"))
    assert len(partials) == 1
    assert [e["type"] for e in read_events(partials[0])] == ["game_start", "error", "retry"]


def test_retries_exhausted_marks_failed_and_resume_reruns(tmp_path):
    cfg, run_dir, calls = make_cfg(max_game_retries=1), str(tmp_path / "run"), {}
    always = lambda idx, n: RuntimeError("boom") if idx == 1 else None
    asyncio.run(run(cfg, run_dir, play_fn=make_play_fn(calls, always), log_fn=lambda *_: None))
    assert calls[1] == 2
    assert read_events(game_path(run_dir, 1))[-1]["data"]["status"] == "failed"

    calls2 = {}
    asyncio.run(run(cfg, run_dir, play_fn=make_play_fn(calls2), log_fn=lambda *_: None))
    assert calls2 == {1: 1}
    assert read_events(game_path(run_dir, 1))[-1]["data"]["status"] == "completed"


def test_model_failure_is_terminal_and_not_retried(tmp_path):
    cfg, run_dir, calls = make_cfg(), str(tmp_path / "run"), {}
    fail = lambda idx, n: AvalonAgentActionException("bad team") if idx == 0 else None
    asyncio.run(run(cfg, run_dir, play_fn=make_play_fn(calls, fail), log_fn=lambda *_: None))
    assert calls[0] == 1
    assert read_events(game_path(run_dir, 0))[-1]["data"]["status"] == "agent_invalid_action"

    calls2 = {}
    asyncio.run(run(cfg, run_dir, play_fn=make_play_fn(calls2), log_fn=lambda *_: None))
    assert calls2 == {}


def test_resume_after_interrupt_replays_same_setup(tmp_path):
    cfg, run_dir, calls = make_cfg(concurrency=1), str(tmp_path / "run"), {}
    hang = asyncio.Event()

    async def interrupted(setup, cfg_, log):
        if setup.game_idx == 3:
            log.emit("game_start", seed=setup.seed, roles=setup.role_names,
                     participants=setup.seat_participants, leader=setup.quest_leader)
            await hang.wait()  # never set: simulates a game in flight at Ctrl-C
        return await make_play_fn(calls)(setup, cfg_, log)

    async def main():
        task = asyncio.create_task(run(cfg, run_dir, play_fn=interrupted, log_fn=lambda *_: None))
        while not os.path.exists(game_path(run_dir, 3)):
            await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(main())
    first_start = read_events(game_path(run_dir, 3))[0]["data"]
    assert set(calls) == {0, 1, 2}

    calls2 = {}
    asyncio.run(run(cfg, run_dir, play_fn=make_play_fn(calls2), log_fn=lambda *_: None))
    assert calls2 == {3: 1, 4: 1, 5: 1}
    replay_start = read_events(game_path(run_dir, 3))[0]["data"]
    assert replay_start == first_start
    assert os.path.exists(os.path.join(run_dir, "games", "game_00003.attempt0.partial.jsonl"))


def test_sharding(tmp_path):
    cfg, run_dir = make_cfg(), str(tmp_path / "run")
    c0, c1 = {}, {}
    asyncio.run(run(cfg, run_dir, shard=(1, 2), play_fn=make_play_fn(c1), log_fn=lambda *_: None))
    assert set(c1) == {1, 3, 5}
    asyncio.run(run(cfg, run_dir, shard=(0, 2), play_fn=make_play_fn(c0), log_fn=lambda *_: None))
    assert set(c0) == {0, 2, 4}
    assert summarize(run_dir)["statuses"] == {"completed": 6}


def test_growing_num_games_on_resume(tmp_path):
    run_dir = str(tmp_path / "run")
    asyncio.run(run(make_cfg(num_games=2), run_dir, play_fn=make_play_fn({}), log_fn=lambda *_: None))
    calls = {}
    asyncio.run(run(make_cfg(num_games=4), run_dir, play_fn=make_play_fn(calls), log_fn=lambda *_: None))
    assert set(calls) == {2, 3}


def test_config_change_refuses_resume(tmp_path):
    run_dir = str(tmp_path / "run")
    asyncio.run(run(make_cfg(num_games=1), run_dir, play_fn=make_play_fn({}), log_fn=lambda *_: None))
    with pytest.raises(RuntimeError, match="different config"):
        asyncio.run(run(make_cfg(num_games=1, base_seed=99), run_dir, play_fn=make_play_fn({}),
                        log_fn=lambda *_: None))


def test_retry_async():
    attempts = []

    async def flaky():
        attempts.append(1)
        if len(attempts) < 3:
            raise ConnectionError("reset")
        return "ok"

    assert asyncio.run(retry_async(flaky, max_retries=5, base=0, cap=0)) == "ok"
    assert len(attempts) == 3

    async def broken():
        raise ValueError("not transient")

    with pytest.raises(ValueError):
        asyncio.run(retry_async(broken, max_retries=5, base=0, cap=0))


def test_is_transient_by_name():
    class RateLimitError(Exception):
        pass

    assert is_transient(RateLimitError())
    assert is_transient(asyncio.TimeoutError())
    assert not is_transient(KeyError("x"))


def test_usage_limit_pauses_run_and_resume_finishes(tmp_path):
    from arena.backends import UsageLimitReached

    cfg, run_dir, calls = make_cfg(concurrency=2), str(tmp_path / "run"), {}
    fail = lambda idx, n: UsageLimitReached("limit will reset at 5pm") if idx == 2 else None
    with pytest.raises(UsageLimitReached):
        asyncio.run(run(cfg, run_dir, play_fn=make_play_fn(calls, fail), log_fn=lambda *_: None))
    assert calls[2] == 1  # never retried
    assert os.path.exists(os.path.join(run_dir, "paused.json"))
    assert read_events(game_path(run_dir, 2))[-1]["type"] == "error"  # no game_end: replayed on resume
    done_before = {i for i in range(6) if os.path.exists(game_path(run_dir, i))
                   and read_events(game_path(run_dir, i))[-1]["type"] == "game_end"}

    calls2 = {}
    asyncio.run(run(cfg, run_dir, play_fn=make_play_fn(calls2), log_fn=lambda *_: None))
    assert set(calls2) == set(range(6)) - done_before and 2 in calls2
    assert not os.path.exists(os.path.join(run_dir, "paused.json"))
    assert summarize(run_dir)["statuses"] == {"completed": 6}


def test_fatal_backend_error_aborts_run(tmp_path):
    from arena.backends import NotLoggedIn

    cfg, run_dir, calls = make_cfg(concurrency=1), str(tmp_path / "run"), {}
    fail = lambda idx, n: NotLoggedIn("run claude and log in") if idx == 0 else None
    with pytest.raises(NotLoggedIn):
        asyncio.run(run(cfg, run_dir, play_fn=make_play_fn(calls, fail), log_fn=lambda *_: None))
    assert calls == {0: 1}


def test_manifest_records_code_version(tmp_path):
    asyncio.run(run(make_cfg(num_games=1), str(tmp_path / "run"), play_fn=make_play_fn({}), log_fn=lambda *_: None))
    with open(tmp_path / "run" / "manifest.json") as f:
        manifest = json.load(f)
    assert "git_sha" in manifest and manifest["git_dirty"] in (True, False, None)
