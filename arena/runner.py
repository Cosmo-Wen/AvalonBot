import asyncio
import glob
import json
import os
import re
import subprocess
import time
import traceback
from typing import Awaitable, Callable, Dict, List, Optional, Tuple

from .backends import FatalBackendError, UsageLimitReached
from .config import ArenaConfig
from .events import EventLog, read_events
from .retry import backoff_delay, is_transient
from .seeding import GameSetup, deal

# outcomes of the models themselves: recorded as final and never retried or re-run
TERMINAL_STATUSES = {"completed", "agent_invalid_action", "context_limit", "refusal"}

PlayFn = Callable[[GameSetup, ArenaConfig, EventLog], Awaitable[Dict]]


def game_path(run_dir: str, game_idx: int) -> str:
    return os.path.join(run_dir, "games", f"game_{game_idx:05d}.jsonl")


def game_status(path: str) -> Optional[str]:
    r"""Status from the log's `game_end` event, or None if the game never finished."""
    if not os.path.exists(path):
        return None
    events = read_events(path)
    if events and events[-1]["type"] == "game_end":
        return events[-1]["data"].get("status")
    return None


def archive_partial(path: str) -> Optional[str]:
    r"""Move an unfinished/failed attempt aside so the game can be replayed from scratch."""
    if not os.path.exists(path):
        return None
    base = path[: -len(".jsonl")]
    taken = [int(m.group(1)) for p in glob.glob(f"{base}.attempt*.partial.jsonl")
             if (m := re.search(r"\.attempt(\d+)\.partial\.jsonl$", p))]
    dest = f"{base}.attempt{max(taken, default=-1) + 1}.partial.jsonl"
    os.replace(path, dest)
    return dest


def _git_sha() -> Optional[str]:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True,
                              check=True).stdout.strip()
    except Exception:
        return None


def _git_dirty() -> Optional[bool]:
    r"""True if tracked files have uncommitted changes, so `git_sha` alone doesn't reproduce the code."""
    try:
        out = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"],
                             capture_output=True, text=True, check=True).stdout
        return bool(out.strip())
    except Exception:
        return None


def ensure_manifest(cfg: ArenaConfig, run_dir: str, force: bool = False) -> str:
    r"""Create the run manifest, or check that an existing run uses the same game-affecting config."""
    os.makedirs(os.path.join(run_dir, "games"), exist_ok=True)
    path = os.path.join(run_dir, "manifest.json")
    run_id = os.path.basename(os.path.normpath(run_dir))
    if os.path.exists(path) and not force:
        with open(path) as f:
            manifest = json.load(f)
        if manifest["config_hash"] != cfg.config_hash():
            raise RuntimeError(
                f"{run_dir} was created with a different config (hash {manifest['config_hash']} != "
                f"{cfg.config_hash()}); use a new run dir or pass --force"
            )
        return manifest["run_id"]
    manifest = {
        "run_id": run_id,
        "created_at": time.time(),
        "config_hash": cfg.config_hash(),
        "git_sha": _git_sha(),
        "git_dirty": _git_dirty(),
        "config": cfg.dict(),
    }
    with open(path, "w") as f:
        json.dump(manifest, f, indent=2)
    return run_id


def write_pause(run_dir: str, reason: str):
    with open(os.path.join(run_dir, "paused.json"), "w", encoding="utf-8") as f:
        json.dump({"paused_at": time.time(), "reason": reason}, f, indent=2)


def clear_pause(run_dir: str):
    try:
        os.remove(os.path.join(run_dir, "paused.json"))
    except FileNotFoundError:
        pass


def load_play_fn(cfg: ArenaConfig) -> PlayFn:
    r"""Imports `cfg.play_fn` ("module:function"); lazily, so tests and `summarize` don't need it."""
    import importlib

    module, _, name = cfg.play_fn.partition(":")
    return getattr(importlib.import_module(module), name)


# matched by class name: importing src.server.tasks.avalon pulls in the whole agent stack
MODEL_FAILURES = {
    "AvalonAgentActionException": "agent_invalid_action",
    "AgentContextLimitException": "context_limit",
    "ModelRefusal": "refusal",
}


def _classify(exc: BaseException) -> Optional[str]:
    r"""Terminal status for model-caused failures; None means infra failure (retryable)."""
    for cls in type(exc).__mro__:
        if cls.__name__ in MODEL_FAILURES:
            return MODEL_FAILURES[cls.__name__]
    return None


def _append_result(run_dir: str, end: Dict):
    with open(os.path.join(run_dir, "results.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps(end) + "\n")
        f.flush()
        os.fsync(f.fileno())


async def run_game(cfg: ArenaConfig, run_dir: str, run_id: str, game_idx: int,
                   play_fn: PlayFn, log_fn=print) -> Dict:
    setup = deal(cfg, game_idx)
    path = game_path(run_dir, game_idx)
    attempt = 0
    while True:
        log = EventLog(path, run_id=run_id, game_idx=game_idx, attempt=attempt)
        try:
            result = await play_fn(setup, cfg, log)
            end = log.emit("game_end", **result)
        except asyncio.CancelledError:
            # leave the partial log in place; the next resume archives and replays it
            raise
        except (FatalBackendError, UsageLimitReached) as e:
            # run-level problems: no game_end, so the next resume replays this game
            log.emit("error", error=f"{type(e).__name__}: {e}", scope="run")
            raise
        except Exception as e:
            error = f"{type(e).__name__}: {e}"
            log.emit("error", error=error, traceback=traceback.format_exc(), transient=is_transient(e))
            status = _classify(e)
            if status is None and attempt < cfg.max_game_retries:
                delay = backoff_delay(attempt, cfg.backoff_base_s, cfg.backoff_max_s)
                log.emit("retry", scope="game", attempt=attempt, error=error, delay_s=delay)
                log.close()
                archive_partial(path)
                log_fn(f"[game {game_idx}] attempt {attempt} failed ({error}); retrying in {delay:.1f}s")
                await asyncio.sleep(delay)
                attempt += 1
                continue
            end = log.emit("game_end", status=status or "failed", error=error)
        finally:
            log.close()

        _append_result(run_dir, end)
        log_fn(f"[game {game_idx}] {end['data'].get('status')} "
               f"{end['data'].get('winner', '')} {end['data'].get('reason', '')}".rstrip())
        return end


def plan_games(cfg: ArenaConfig, run_dir: str, shard: Tuple[int, int]) -> Tuple[List[int], List[int]]:
    r"""Split this shard's games into (to_run, already_done), archiving any unfinished attempts."""
    shard_idx, num_shards = shard
    to_run, done = [], []
    for idx in range(cfg.num_games):
        if idx % num_shards != shard_idx:
            continue
        path = game_path(run_dir, idx)
        if game_status(path) in TERMINAL_STATUSES:
            done.append(idx)
            continue
        archive_partial(path)
        to_run.append(idx)
    return to_run, done


async def run(cfg: ArenaConfig, run_dir: str, shard: Tuple[int, int] = (0, 1), force: bool = False,
              play_fn: Optional[PlayFn] = None, log_fn=print) -> List[Dict]:
    shard_idx, num_shards = shard
    if not 0 <= shard_idx < num_shards:
        raise ValueError(f"invalid shard {shard_idx}/{num_shards}")
    run_id = ensure_manifest(cfg, run_dir, force=force)
    play_fn = play_fn or load_play_fn(cfg)

    to_run, done = plan_games(cfg, run_dir, shard)
    log_fn(f"run {run_id} shard {shard_idx}/{num_shards}: {len(done)} done, {len(to_run)} to run")

    clear_pause(run_dir)
    sem = asyncio.Semaphore(cfg.concurrency)

    aborted = asyncio.Event()

    async def guarded(idx: int):
        async with sem:
            if aborted.is_set():
                return None
            try:
                return await run_game(cfg, run_dir, run_id, idx, play_fn, log_fn)
            except (FatalBackendError, UsageLimitReached):
                aborted.set()  # before releasing the slot, so no queued game starts
                raise

    tasks = [asyncio.ensure_future(guarded(i)) for i in to_run]
    try:
        return list(await asyncio.gather(*tasks))
    except BaseException as e:
        # stop every other game too; their partial logs are replayed on resume
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if isinstance(e, UsageLimitReached):
            write_pause(run_dir, str(e))
        raise
