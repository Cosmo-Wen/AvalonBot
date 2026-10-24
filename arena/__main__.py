import argparse
import asyncio
import glob
import json
import os
import sys
from collections import Counter, defaultdict

from .backends import FatalBackendError, UsageLimitReached, make_backend, resolve_claude_bin
from .config import load_config, load_env_file
from .events import read_events
from .runner import load_play_fn, run


def _parse_shard(s: str):
    i, n = s.split("/")
    return int(i), int(n)


def summarize(run_dir: str) -> dict:
    r"""Aggregate final `game_end` events across all (sharded) game logs in a run dir."""
    percival_ends = []
    statuses = Counter()
    winners = Counter()
    by_name = defaultdict(lambda: {"games": 0, "wins": 0, "deduction_acc": 0.0})
    by_agent_role = defaultdict(lambda: {"games": 0, "wins": 0})
    usage = defaultdict(lambda: {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0})
    for path in sorted(glob.glob(os.path.join(run_dir, "games", "game_*.jsonl"))):
        if ".partial." in path:
            continue
        events = read_events(path)
        if not events or events[-1]["type"] != "game_end":
            statuses["unfinished"] += 1
            continue
        end = events[-1]["data"]
        statuses[end["status"]] += 1
        names = {s["seat"]: s["name"] for s in events[0]["data"].get("seats", [])} if events[0]["type"] == "game_start" else {}
        for e in events:
            if e["type"] == "llm_call":
                u = usage[names.get(e["data"].get("seat"), "unknown")]
                u["calls"] += 1
                u["input_tokens"] += e["data"].get("input_tokens", 0)
                u["output_tokens"] += e["data"].get("output_tokens", 0)
                u["cost_usd"] += e["data"].get("cost_usd", 0.0)
        if end["status"] != "completed":
            continue
        if end.get("percival_metrics") is not None:
            percival_ends.append(end)
        winners[f"{end['winner']}:{end['reason']}"] += 1
        for seat in end["seats"]:
            n = by_name[seat["name"]]
            n["games"] += 1
            n["wins"] += int(seat["won"])
            if seat.get("deduction_acc") is not None:
                n["deduction_acc"] += seat["deduction_acc"]
                n["scored"] = n.get("scored", 0) + 1
            r = by_agent_role[f"{seat['agent']}:{seat['model']} as {seat['role']}"]
            r["games"] += 1
            r["wins"] += int(seat["won"])

    def rate(d):
        out = {}
        for k, v in sorted(d.items()):
            row = {"games": v["games"], "wins": v["wins"], "win_rate": round(v["wins"] / v["games"], 3)}
            if "deduction_acc" in v:  # averaged over the games where this player reported beliefs
                scored = v.get("scored", 0)
                row["deduction_acc"] = round(v["deduction_acc"] / scored, 3) if scored else None
            out[k] = row
        return out

    from avalon.percival_metrics import summarize_percival
    return {
        **({"percival_experiment": summarize_percival(percival_ends)} if percival_ends else {}),
        "statuses": dict(statuses),
        "outcomes": dict(winners),
        "by_participant": rate(by_name),
        "by_agent_and_role": rate(by_agent_role),
        # cost_usd is what Claude Code reports at list prices; on a subscription it is not billed
        "usage_by_participant": {k: {**v, "cost_usd": round(v["cost_usd"], 4)} for k, v in sorted(usage.items())},
    }


async def _check(cfg) -> bool:
    ok = True
    print(f"python {sys.version.split()[0]}: " + ("ok" if sys.version_info >= (3, 10) else "need >= 3.10"))
    ok &= sys.version_info >= (3, 10)
    try:
        if cfg is not None:
            load_play_fn(cfg)  # imports the game and agent stack
        print("imports: ok")
    except Exception as e:
        print(f"imports: FAILED ({type(e).__name__}: {e})")
        return False
    if cfg is None:
        return ok
    if any(s.provider == "claude_cli" for s in cfg.seats):
        try:
            print(f"claude CLI: {resolve_claude_bin(cfg.claude_bin)}")
        except FatalBackendError as e:
            print(f"claude CLI: {e}")
            return False
    # one tiny call per distinct (provider, model) a seat will use
    targets = {}
    for s in cfg.seats:
        if s.provider != "fake":
            targets[(s.provider, s.model)] = s
    for (provider, model), spec in sorted(targets.items()):
        backend = None
        try:
            backend = make_backend(spec, cfg, seed=0, model=model)
            c = await backend.complete("Answer tersely.", [("user", "Reply with exactly: OK")])
            print(f"{provider} {model}: ok -> {c.model}, reply {c.text!r}, {c.input_tokens} in / {c.output_tokens} out tokens, {c.duration_s}s")
        except Exception as e:
            print(f"{provider} {model}: FAILED ({type(e).__name__}: {e})")
            ok = False
        finally:
            if backend is not None:
                backend.close()
    return ok


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m src.arena")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_run = sub.add_parser("run", help="play (or resume) a batch of games")
    p_run.add_argument("--config", required=True)
    p_run.add_argument("--run-dir", required=True)
    p_run.add_argument("--shard", type=_parse_shard, default=(0, 1), help="i/n: run games with idx %% n == i")
    p_run.add_argument("--concurrency", type=int, help="override config concurrency")
    p_run.add_argument("--num-games", type=int, help="override config num_games")
    p_run.add_argument("--force", action="store_true", help="resume even if the config hash changed")

    p_run.add_argument("--fake", action="store_true", help="use the offline fake model for every seat (install check)")

    p_sum = sub.add_parser("summarize", help="aggregate results of a run dir")
    p_sum.add_argument("--run-dir", required=True)

    p_chk = sub.add_parser("check", help="check the install, the Claude Code login and each configured model")
    p_chk.add_argument("--config")

    args = parser.parse_args(argv)
    load_env_file(".env")  # local secrets, e.g. OPENAI_API_KEY / OPENAI_BASE_URL (gitignored)
    if args.cmd == "summarize":
        print(json.dumps(summarize(args.run_dir), indent=2))
        return 0
    if args.cmd == "check":
        ok = asyncio.run(_check(load_config(args.config) if args.config else None))
        print("all checks passed" if ok else "some checks failed")
        return 0 if ok else 1

    cfg = load_config(args.config)
    if args.fake:
        for seat in cfg.seats:
            seat.provider = "fake"
    if args.concurrency is not None:
        cfg.concurrency = args.concurrency
    if args.num_games is not None:
        cfg.num_games = args.num_games
    try:
        asyncio.run(run(cfg, args.run_dir, shard=args.shard, force=args.force))
    except KeyboardInterrupt:
        print("\nInterrupted. Re-run the same command to resume; unfinished games will be replayed.",
              file=sys.stderr)
        return 130
    except UsageLimitReached as e:
        print(f"\nUsage limit reached ({e}). Re-run the same command after it resets to resume.", file=sys.stderr)
        return 75
    except FatalBackendError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    except (RuntimeError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
