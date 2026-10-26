# Percival P0 vs P1 on Claude Haiku, 40 paired seeds (2026-10-25)

Turns the [7-game `gpt-6.1-sol` Percival pilot](../percival-2026-10-24/README.md) into a paired comparison.
Every seat is Claude Haiku through `claude -p`. Roles: Merlin, Percival, Servant vs Assassin, Morgana.
Seed *i* is the same deal in both runs, so each seed is one pair.

| | Percival plays |
|---|---|
| P0 `chat_only` | from the transcript, like any LLM seat |
| P1 `four_world` | the four-world belief table, with the proposal-consistent rule: it proposes its most likely all-good team and approves that team, anything as good, or anything above 0.55 (`avalon/percival.py`) |

The analysis was fixed before the run (`experiments/compare_percival.py`): good-team win is primary
(exact McNemar on the discordant pairs); 3 quests passed, the Assassin's hit rate and Merlin's
vote-accuracy rank are secondary.

## Results

| | P0 | P1 |
|---|---|---|
| **Good wins** | **13/40** | **20/40** |
| Good passed 3 quests | 32/40 | 40/40 |
| Mean quests passed | 2.73 | 3.00 |
| Assassin shoots Merlin / Percival / Servant | 19 / 8 / 5 (of 32) | 20 / 9 / 11 (of 40) |
| Merlin's mean vote-accuracy rank (1 = most accurate, most exposed) | 1.21 | 1.39 |
| Percival's final P(true Merlin) | 0.66 | 0.94 |

Paired:

| Metric | Pairs | P0 only | P1 only | Exact McNemar p |
|---|---|---|---|---|
| **Good wins** | 40 | 3 | 10 | **0.092** |
| Good passed 3 quests | 40 | 0 | 8 | 0.008 |
| Assassin hit Merlin (both reached it) | 32 | 5 | 3 | 0.73 |

Merlin's rank was higher (less exposed) under P1 in 16 pairs and under P0 in 7; 17 tied.

What this says:
- **P1 gets good to the assassination every time.** All 40 P1 games pass 3 quests, against 32 for P0, and no
  pair goes the other way (p = 0.008). Percival picking its most likely all-good team, and backing it,
  is what drives this.
- **The primary result points to P1 but is not significant.** P1 wins 7 more games (10 pairs to 3, p = 0.09).
  Most of the gain comes from reaching the assassination more often, not from hiding Merlin better.
- **Merlin is not much safer.** The Assassin finds Merlin in 59% of P0 assassinations and 50% of P1's,
  and on the 32 pairs where both reached it, the hit rate doesn't differ (p = 0.73). Merlin is a bit less
  exposed by votes under P1 (rank 1.39 vs 1.21), and the Assassin shoots Percival about as often in both (8 and 9).
- **Read with care:** P1 changes two things at once, Percival's beliefs and its control of proposals, so this
  can't say which one helped. And this is not the 2026-10-24 P1: that version let the LLM pick teams.

## Data quality

- **No model errors in any completed game.** 19 games (P0 seeds 27–39, P1 seeds 33–39) first failed on Claude
  Code's session limit and were replayed from scratch on the same deal after the reset. The run kept failing
  games instead of stopping, because the limit message wasn't recognised; that is fixed in `arena/backends.py`.
- **Code:** branch `cleanup` at `4fa6ba4` for both runs (the session-limit fix touches only error handling).
- **Cost:** P0 2,492 calls (7.2M input, 1.4M output tokens), P1 2,054 calls (5.6M input, 1.1M output tokens).
  P1 makes fewer calls because its proposals and votes need no model call.

## Files

`comparison.json`, `pairs.csv`, `summary_*.json`, `manifest_*.json`, written by:

```bash
python -m arena run --config configs/arena/haiku_percival_p0.yaml --run-dir runs/haiku-percival/p0
python -m arena run --config configs/arena/haiku_percival_p1.yaml --run-dir runs/haiku-percival/p1
python experiments/compare_percival.py --runs runs/haiku-percival --out experiments/percival-haiku-2026-10-25
```

Game logs: `runs-haiku-percival.tar.xz` on the `archive/run-logs` branch.
