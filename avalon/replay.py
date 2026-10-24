"""
Reenacts a recorded Avalon-LLM arena game (`games/game_*.jsonl`) through AvalonBot.

Every event is delivered to each player's own PlayerMemory exactly as the runner would deliver it:
public events to everyone, quest cards only to the player who played them. The same events also
drive an AvalonEngine with the recorded roles and first leader, so any step the rules don't allow
(wrong leader, wrong team size, a good player playing Fail, ...) is reported as a violation.

Talk edges are not in the transcript. Pass hand-labelled ones (`talk_edges`) to stand in for each
player's extraction call; they are added after each discussion round, before the proposal.

Usage: py -3.12 -m avalon.replay <game.jsonl> [talk_edges.json] [--seat N]
"""

import json
import sys
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence

from .arena_adapter import ARENA_ROLES, ArenaGraphAdapter, Replay  # noqa: F401  (re-exported)
from .memory import PlayerMemory


def load_events(path: str) -> List[Dict[str, Any]]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def load_talk_edges(path: str) -> List[Dict[str, Any]]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)["edges"]


def replay_arena_game(
    events: Sequence[Dict[str, Any]],
    talk_edges: Iterable[Dict[str, Any]] = (),
    belief_mode: str = "rule",
    merlin_graph: bool = True,
    stop_after_seq: Optional[int] = None,
    on_step: Optional[Callable[[int, Dict[int, PlayerMemory]], None]] = None,
) -> Replay:
    """
    Feeds a recorded game into one PlayerMemory per seat, through `ArenaGraphAdapter`.
    `stop_after_seq` replays only events with seq <= that value, to inspect a player's memory partway
    through the game. `on_step(seq, memories)` is called after every event that adds a log entry.
    """
    adapter = ArenaGraphAdapter(talk_edges, belief_mode=belief_mode, merlin_graph=merlin_graph)
    for event in events:
        if stop_after_seq is not None and event["type"] != "game_start" and event["seq"] > stop_after_seq:
            break
        stepped = adapter.feed(event)
        if stepped and on_step is not None:
            on_step(event["seq"], adapter.memories)
    if adapter.state is None:
        raise ValueError("no game_start event")
    return adapter.state


def main(argv: Sequence[str]) -> None:
    args = list(argv)
    seat: Optional[int] = None
    if "--seat" in args:
        i = args.index("--seat")
        seat = int(args[i + 1])
        del args[i:i + 2]
    if not args:
        print(__doc__)
        return
    edges = load_talk_edges(args[1]) if len(args) > 1 else []
    replay = replay_arena_game(load_events(args[0]), edges)

    print(f"Roles: {', '.join(f'P{p} {r.name}' for p, r in sorted(replay.roles.items()))}")
    print(f"Violations: {replay.violations or 'none'}")
    for s, memory in sorted(replay.memories.items()):
        if seat is not None and s != seat:
            continue
        print(f"\n=== Player {s} ({replay.roles[s].name}) ===")
        print(memory.render_table())


if __name__ == "__main__":
    main(sys.argv[1:])
