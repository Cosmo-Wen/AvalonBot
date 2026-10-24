# Avalon-LLM arena: Haiku pilot game and fixes

Reference material from the arena runner built on
[Avalon-LLM](https://github.com/jonathanmli/Avalon-LLM), kept here until the runner is ported onto
AvalonBot's engine. **Nothing in this folder changes how AvalonBot runs.**

## `game4-all-fixes/`: one full game transcript

A single 5-player game played by LLM agents through Claude Code in headless mode (`claude -p`) on a
Claude subscription, with no API key. It's the 4th of four pilot games, and the first with every fix
below.

| | |
|---|---|
| Model | Claude Haiku (`claude-haiku-5-5`) at `effort: low`, replies capped at 40 words |
| Seats | 0 Merlin, 1 Assassin, 2 Servant, 4 Minion: LLM agents. 3 Servant: Strategist search agent |
| Setup | `base_seed: 0`, game 0, roles and seats shuffled from the seed |
| Outcome | Evil wins on missions: quests pass, fail, fail, fail |
| Length | 31.5 min, 426 model calls (~4.0 s each), 14 team proposals |
| Tokens | 934k in / 85k out ($0.17 at list price, not billed on a subscription) |
| Code | Avalon-LLM commit `9a0dd43` on branch `arena-runner`, clean working tree |

It's one game, a pilot and not a result.

Files:
- `manifest.json`: the exact config, its hash and the code commit.
- `games/game_00000.jsonl`: one event per line. It holds every prompt and model response
  (`llm_call`), every speech, team proposal, vote and quest result, the end-of-game beliefs, and
  `game_end`.
- `results.jsonl`: the final result.

Read the discussion in order:

```bash
python -c "import json; [print(f\"P{e['data']['seat']}: {e['data']['text']}\") for e in map(json.loads, open('experiments/avalon-llm-haiku-pilot/game4-all-fixes/games/game_00000.jsonl')) if e['type'] == 'discussion']"
```

## `patches/`: the fixes, as Avalon-LLM commits

These patch **Avalon-LLM**, not AvalonBot. Apply them to an Avalon-LLM checkout at `2439c6b`:

```bash
git -C /path/to/Avalon-LLM checkout -b arena-runner 2439c6b
git -C /path/to/Avalon-LLM am /path/to/AvalonBot/experiments/avalon-llm-haiku-pilot/patches/*.patch
```

**`0001`: the arena runner, plus fixes to Avalon-LLM's game code.**
- **The runner** (`src/arena`):
  - seeded role, seat and leader shuffles
  - one JSONL event log per game
  - an async runner with retry, per-game resume and sharding
  - backends: `claude_cli` (Claude Code on your own login), `anthropic` (API key) and an offline `fake` model
- **Fixes to existing Avalon-LLM code:**
  - **Wrong speaker labels:** discussion lines were credited to the wrong player. Seat *i* was
    broadcast as "Player *i*+1", so seat 4 appeared as a nonexistent "Player 5" (`multi_agent/proxy.py`).
  - **Wrong point of view:** the search agent reasoned as the lowest-numbered acting player in votes,
    and with the quest leader's private information in discussion (`AvalonActorActionEnumerator`,
    `search_agent.py`).
  - **Shared game state:** `from_presets` stored game state on the class, so concurrent games shared
    roles (`engine.py`).
  - **Fixed seed:** the search agent's random generator was hard-coded to seed 12.

**`0002`: the search agent was mute.** It made its speeches with its planner, outside the proxy's
broadcast, so the other players never heard it.

## Why AvalonBot doesn't need these fixes

AvalonBot's own code avoids each of these bugs:
- **Speaker labels:** it labels speakers with 0-based seats (`avalon/agents.py`).
- **Game state:** its engine keeps its random generator and state on the instance.
- **Discussion:** every utterance goes to all agents through one event bus (`avalon/runner.py`), so no
  seat can be mute.
- **Point of view:** it has no Strategist search agent, so the point-of-view bug can't occur.

The patches matter when porting: if the runner or the search agent comes over from Avalon-LLM, it
should come with these fixes.
