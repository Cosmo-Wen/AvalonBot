# arena: batch runner

Runs many seeded 5-player Avalon games and records each as a JSONL event log. The game itself is
pluggable: `play_fn` in the config names a function `play(setup, cfg, log) -> game_end payload`. In
AvalonBot that's `avalon.arena_play:play_game` (the default), which plays AvalonBot's engine and
agents.

Vendored from the arena built on [Avalon-LLM](https://github.com/jonathanmli/Avalon-LLM) (only
`src/arena`, with its own history). The Avalon-LLM game loop, its session wrapper, and the Strategist
search agent were dropped here.

What it does:
- **Seeded setups:** role deal, seat assignment and first leader all come from
  `(base_seed, game_idx)`. Configs that differ only in `condition` get the same deals.
- **Event logs:** one append-only JSONL log per game, fsync'd per event.
- **Concurrent games:** a semaphore caps parallel games (`concurrency`).
- **Retries:** transient failures can be retried (`max_game_retries`).
- **Per-game resume:** finished games are skipped, unfinished ones replayed.
- **Pause on limits:** a usage limit or exhausted allowance pauses the run (`paused.json`, exit code
  75) and a re-run resumes it. A rejected key stops it.
- **Sharding:** `--shard i/n` splits the games across processes or machines; `summarize` merges them.

Run from the repository root:

```bash
python -m arena check     --config configs/arena/sol_chat_only.yaml
python -m arena run       --config configs/arena/sol_chat_only.yaml --run-dir runs/sol/chat_only [--shard 0/2]
python -m arena summarize --run-dir runs/sol/chat_only
```

The CLI loads a local `.env` (gitignored) before running.

Model backends (`backends.py`) are text-only completions with logging, retry rules and error
classification:
- **`claude_cli`:** Claude Code headless, on the user's own login.
- **`anthropic`:** the Claude API.
- **`openai`:** any OpenAI-compatible Responses API.
- **`fake`:** an offline model.

AvalonBot's LLMAgent needs tool calls, so it talks to the endpoint itself, and the backends serve
`check` and text-only play functions. In AvalonBot games, `provider: openai` seats are LLMAgents and
`provider: fake` seats are the offline HeuristicAgent.

Per-game log events: `game_start` (seed, seats, roles, condition), `discussion`, `team_proposed`,
`team_votes`, `team_result`, `quest_votes` (cards), `quest_result`, `evil_chat`, `assassination`,
`llm_call` / `llm_error` (prompt, response, tokens, latency), `beliefs` (final P(good) rows, belief
paths), `belief_graphs` (each player's graph rebuilt from these events), `error`, `game_end`.
