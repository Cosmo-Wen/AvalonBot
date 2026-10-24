# Avalon arena

Standalone runner for 5-player Avalon games between LLM agents:
- **Seeded setups:** role deal, seat assignment and starting leader all come from `(base_seed, game_idx)`.
- **Event logs:** one JSONL log per game.
- **Concurrent runs:** retries and per-game resume.

Each seat picks a provider:
- **`claude_cli`** (default): Claude Code in headless mode (`claude -p`) on each person's own Claude
  login. No API key needed.
- **`anthropic`**: the Claude API with an API key, for anyone who has one (see below).
- **`fake`**: a built-in scripted model that plays offline for free, which lets you check an install end to end.

Providers can be mixed in one game.

## Setup (macOS, Linux, Windows)

1. Install Claude Code, then run `claude` once and log in with your Claude account.
2. Python 3.10–3.12:
   ```bash
   python -m venv .venv
   source .venv/bin/activate          # Windows: .venv\Scripts\activate
   pip install -r requirements-arena.txt
   ```
3. Check everything, then play offline games (free, a few seconds each):
   ```bash
   python -m src.arena check
   python -m src.arena run --fake --num-games 2 --config configs/arena/avalon5.yaml --run-dir results/arena/fake
   ```
4. Check your login and each configured model (one tiny call per model), then play for real:
   ```bash
   python -m src.arena check --config configs/arena/avalon5.yaml
   python -m src.arena run --config configs/arena/avalon5.yaml --run-dir results/arena/run1
   python -m src.arena summarize --run-dir results/arena/run1
   ```

Run everything from the repository root.

## Configuration

See `configs/arena/avalon5.yaml`. Each seat has these fields:
- `agent`: `llm`, `search` or `recon`.
- `provider`: `claude_cli`, `anthropic` or `fake`.
- `model`: a Claude Code model alias or id. `haiku` stretches your usage furthest; `sonnet` and `opus` play better.
- Search/recon seats only:
  - `planner_model`: the model for the search agent's dialogue planner.
  - `planner_num_rollout` / `planner_node_budget`: its tree-search budget per decision. The default 100 is about 4 s of CPU per decision.

With `shuffle_seats`, participants are permuted across seats each game.

## Using a Claude API key (optional)

1. `pip install 'anthropic>=2.0.0'`
2. Set `ANTHROPIC_API_KEY`. An `ANTHROPIC_AUTH_TOKEN` or an `ant auth login` profile also works.
3. Give seats `provider: anthropic`:
   - `model`: an API model id (default `claude-opus-5-5`), or the aliases haiku / sonnet / opus.
   - `effort`: default `medium`.
4. Run `python -m src.arena check --config ...` to confirm the key and models.

Requests follow the current API:
- **No sampling parameters:** `temperature` and friends are rejected since API version 2026-10-21.
- **Explicit effort level.**
- **Automatic prompt caching:** each seat's transcript only grows, so later turns reuse earlier ones.
- **Refusals:** `fallbacks: "default"` reruns a declined request on another model, on models that support
  it (not Haiku). If the request is still declined, the game ends with status `refusal`.

Error handling:
- An exhausted credit balance (402) pauses the run like a usage limit.
- A rejected key stops it with a hint.
- Rate limits and overload are retried with backoff.

`cost_usd` for API seats is an estimate from a built-in price table (`API_PRICES` in `backends.py`);
check current pricing before relying on it.

## Usage limits, resume and scaling

- One game is about 150–250 model calls. A subscription's usage window allows only a limited number
  of games, especially on larger models.
- When the usage limit is hit, the run stops cleanly, writes `paused.json`, and exits with code 75.
  **Re-run the same command after the limit resets** to continue.
  - Finished games are skipped.
  - Unfinished games are replayed from scratch with the same seed.
  - The same applies after Ctrl-C or a crash.
- `concurrency` runs games in parallel within one process. Search agents' tree search is CPU-bound and
  takes turns process-wide, so for real parallelism split the run into processes with
  `--shard i/n` (same `--run-dir` or merged later). `summarize` merges all shards.
- `cli_max_parallel` caps concurrent `claude` processes.

Each `claude -p` call runs with tools, MCP servers and settings disabled, in an empty temp directory,
so no project files, hooks or plugins are involved.

Headless Claude Code on your own machine and login is a documented feature, but check Anthropic's
current consumer terms before relying on sustained automated runs.

## Output

`run-dir/manifest.json` holds the config, its hash and the git SHA. `run-dir/games/game_NNNNN.jsonl` holds
one event per line:
- `game_start` (seed, seats, roles)
- `discussion`, `team_proposed`, `team_votes`, `team_result`, `quest_votes`, `quest_result`, `assassination`
- `beliefs`
- `llm_call` (prompt, response, model, tokens, latency)
- `retry`, `error`
- `game_end`

`cost_usd` in logs: for `claude_cli`, Claude Code's list-price estimate (not billed on a subscription);
for `anthropic`, an estimate of what the API call cost.

## Tests

```bash
pytest tests/arena -q
```
