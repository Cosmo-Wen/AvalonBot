# A vs C replication on Claude Haiku, 40 paired seeds (2026-10-25)

Does the sol result (the belief graph helps good pass quests) hold on a second model? Every seat is
Claude Haiku through `claude -p` (`provider: claude_cli`). Condition B was dropped to save calls.
Seeds are the same deals as the [`gpt-6.1-sol` batch](../sol-ablation-2026-10-24/), so seed *i* is
one pair within Haiku and lines up with seed *i* on sol.

The primary metric was fixed before the run: good passed 3 quests, exact McNemar on the discordant pairs.

## Results

| | A `chat_only` | C `rule_graph` | sol A | sol C |
|---|---|---|---|---|
| **Good passed 3 quests** | **29/40** | **33/40** | 25/40 | 39/40 |
| ...then Merlin assassinated | 21/29 | 26/33 | 22/25 | 35/39 |
| Good wins | 8/40 | 7/40 | 3/40 | 4/40 |
| Mean quests passed | 2.63 | 2.75 | 1.98 | 2.93 |

Paired, A vs C on Haiku:

| Metric | A only | C only | Exact McNemar p |
|---|---|---|---|
| Good passed 3 quests | 5 | 9 | 0.42 |
| Good wins | 6 | 5 | 1.0 |
| Merlin assassinated | 7 | 12 | 0.36 |

What this says:
- **The quest effect does not replicate on Haiku.** C passes 3 quests in 4 more games than A, in the same
  direction as sol, but the difference is small and far from significant (14 discordant pairs against sol's 14
  all one way).
- **Haiku's baseline is already strong at quests.** A passes 3 quests in 29/40 games against sol's 25/40,
  which leaves less room for the graph to help.
- **Wins still hinge on Merlin.** The Assassin finds Merlin in 21 of 29 and 26 of 33 games that reach the
  assassination, less often than on sol (about 90%), so Haiku's good team wins more (8 and 7 against 3 and 4).
- The two commits behind these games agree: seeds 0–9 give A 7 and C 9, seeds 10–39 give A 22 and C 24.

## Data quality

- **No model errors and no retries** in any of the 80 games.
- **Provenance:** A seeds 0–9 and C seeds 0–13 are the Haiku pilot, played at `486bac6`
  (`merlin-vote-cover` branch, `merlin_strategy: default`). The rest were played on branch `cleanup`
  at `4fa6ba4`. For non-Percival games the prompts and agent logic are the same at both commits.
  `manifest_*.json` names `486bac6` because a resumed run keeps its manifest.
- **Cost:** A 2,671 calls (7.6M input, 1.2M output tokens), C 2,505 calls (7.2M input, 1.5M output tokens).
  Deduction accuracy is not comparable across conditions (see the sol README).

## Files

`comparison.json`, `pairs.csv`, `summary_*.json`, `manifest_*.json`, written by:

```bash
python experiments/compare_conditions.py --runs runs/haiku-ac --out experiments/haiku-ac-2026-10-25
```

Game logs are in `runs/haiku-ac/` (gitignored); archive them with the others on `archive/run-logs`.
