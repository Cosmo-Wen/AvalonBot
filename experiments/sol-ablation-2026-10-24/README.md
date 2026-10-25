# Ablation on `gpt-6.1-sol`, 40 paired seeds (2026-10-24)

Every seat is `gpt-6.1-sol` on Boson. Only the good team's condition changes; evil always plays chat-only (A).

| | Condition | Good team keeps |
|---|---|---|
| A | `chat_only` | the transcript only |
| B | `belief_graph` | a belief graph; the model sets P(evil), checked against the evidence |
| C | `rule_graph` | a belief graph; P(evil) from the pair-counting rule |

Seed *i* is the same deal in every condition (roles, first leader, agent seeds:
[`configs/arena/paired_seeds_sol.json`](../../configs/arena/paired_seeds_sol.json)), so each seed is one pair.
Binary outcomes are compared with an exact McNemar test on the discordant pairs.

## Results

| | A | B | C |
|---|---|---|---|
| Good passed 3 quests | 25/40 | 35/40 | **39/40** |
| ...then Merlin assassinated | 22/25 | 32/35 | 35/39 |
| **Good wins** | **3/40** | **3/40** | **4/40** |
| Mean quests passed | 1.98 | 2.73 | 2.93 |
| Servant deduction accuracy at game end | 0.94 | 0.94 | 0.63 |

Paired, good passed 3 quests:

| | Discordant pairs | Exact McNemar p | Without seeds 13, 35, 39 (n = 37) |
|---|---|---|---|
| A vs B | B only 11, A only 1 | 0.006 | 0.012 |
| A vs C | C only 14, A only 0 | 0.0001 | 0.0002 |
| B vs C | C only 4, B only 0 | 0.125 | 0.125 |

Good wins: no difference in any comparison (p = 1.0; 2–3 discordant pairs each).

What this says:
- **The graph helps the good team pass quests**, by a lot and on the same deals: 14 of 40 pairs flip from
  failed to passed under C, none the other way. B gets most of that gain; C's lead over B is not significant.
- **It doesn't win games.** After 3 passed quests the Assassin names Merlin about 90% of the time in every
  condition, so the quest gains become assassinations. At this model strength, Merlin's exposure, not
  belief tracking, is what limits good's win rate.
- **Deduction accuracy is not comparable across conditions.** A is asked once at game end; B reports the
  beliefs it played with; C's are the rule's output, which settles less often on the exact evil pair (0.63).
- **B's beliefs were the model's own:** 357 of 362 updates were accepted at once and 5 after one re-ask;
  none fell back to the rule.

## Data quality

- **No fallback moves except 3 calls**: B seed 13 (a 503 during the final quest's belief extraction)
  and C seeds 35 and 39 (a 502 each). The fixes now retry them. Dropping those seeds changes no conclusion
  (table above).
- **C seeds 32, 34, 35, 36 and 39 were replayed** from scratch on the same deal after stalled connections
  or DNS failures in their first attempt. Each request is now bounded by `llm_timeout_s` and retried.
- **Throughput:** A and B ran side by side (3 requests in flight each, the gateway's limit of 6), then C at 6.
  The whole batch took about 7 hours (02:21–09:45 EDT).
- **Cost:** 8,674 calls, 13.2M input and 0.86M output tokens over the final 120 games (replayed attempts and
  the smoke test add more). B and C make about 1.1× A's calls and 1.2× its input tokens per game.

## Files

| File | What |
|---|---|
| `comparison.json` | Per-condition rates, tokens, errors; paired tests for each pair of conditions |
| `pairs.csv` | One row per seed: each condition's outcome, quests passed, calls, tokens, errors, belief paths |
| `summary_*.json` | `python -m arena summarize` for each run |
| `manifest_*.json` | Each run's config, config hash and git commit |
| `graphs/` | Belief-graph pages for seeds 0 and 2 in A, B and C; open `graphs/index.html` |

Game logs are not on `main`. They are archived on the
[`archive/run-logs`](https://github.com/Cosmo-Wen/AvalonBot/tree/archive/run-logs) branch
(`runs-sol.tar.xz`; restore with `tar -xJf runs-sol.tar.xz` from the repo root). The `gpt-6.1-sol`
endpoint is no longer available, so the `run` commands below are the original recipe, not something
that can be repeated. The analysis commands work on the restored logs:

```bash
python -m arena run --config configs/arena/sol_chat_only.yaml    --run-dir runs/sol/chat_only
python -m arena run --config configs/arena/sol_belief_graph.yaml --run-dir runs/sol/belief_graph
python -m arena run --config configs/arena/sol_rule_graph.yaml   --run-dir runs/sol/rule_graph
python experiments/compare_conditions.py --runs runs/sol --out experiments/sol-ablation-2026-10-24
python experiments/render_graphs.py --runs runs/sol --out runs/sol/graphs   # every game's graphs
python experiments/belief_moves.py runs/sol/belief_graph                   # B's P(evil) after each failed quest
```

On a graph page, pick a player and drag the slider: every view shows only what that player knew at that
point. The P(evil) shown is the pair-counting rule's, replayed from the log; B's own P(evil) values are
in the log's `record_observations` calls (`belief_moves.py` prints them).
