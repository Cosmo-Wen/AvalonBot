# Hiding Merlin from the Assassin (2026-10-24)

In the gpt-6.1-sol ablation, good passed 3 quests far more often with a belief graph, but the Assassin then
found Merlin about 90% of the time in every condition. This folder records why, and what was tried.

## Why the Assassin finds Merlin: votes

The Assassin knows who is evil, so it can grade every good player's team votes against the truth (approve a
clean team, reject one with evil). Servants vote on public evidence; Merlin votes on what they saw.
`experiments/merlin_vote_leak.py` does that grading offline, on the existing logs
([`sol_C_vote_leak.txt`](sol_C_vote_leak.txt) for gpt-6.1-sol condition C):

| gpt-6.1-sol, games with an assassination | C | B | A |
|---|---|---|---|
| Merlin's vote accuracy | 0.99 | 0.98 | 0.99 |
| Servants' vote accuracy | 0.78 | 0.78 | 0.81 |
| Merlin is the most accurate voter | 39/39 | 35/35 | 25/25 |
| An Assassin that names the top voter would hit (ties split) | 34/39 | 29.7/35 | 19/25 |
| The real Assassin hit | 35/39 | 32/35 | 22/25 |
| The real Assassin's target was a top voter | 38/39 | 34/35 | 25/25 |

Grading votes alone reproduces the Assassin's hit rate. Most misses are games where every good player voted
perfectly, so votes couldn't tell them apart. A first try that only hid Merlin's *speech*
(`merlin_strategy: hidden`, seed 0) confirmed it: Merlin stopped naming evil, and the Assassin found Merlin
from the votes instead.

## What was tried (Haiku, every seat on `claude -p --model haiku`, seeds 0-9, paired with Haiku C)

| `merlin_strategy` | Merlin's votes |
|---|---|
| (C, default) | the model's own |
| `cover` | the public-evidence counting rule, as a Servant in Merlin's seat could compute it; real knowledge only to reject evil at match point |
| `cap` v1 | the truth, unless that would make Merlin the most accurate good voter in this game; then reject a clean team (the "cheap" error). Always the truth on evil at match point |
| `cap` v2 | as v1, but also the truth when evil has 2 fails, on a quest's 4th and 5th proposal, on any team Merlin is on, and after one cheap error per quest |

Votes and team picks for `cover` and `cap` are made by code, with no extra model calls. Merlin's speech keeps
the hidden-speech rules in every variant.

Seeds 0-9 ([`strategies_seeds_0-9.json`](strategies_seeds_0-9.json)):

| | C | cover | cap v1 | cap v2 |
|---|---|---|---|---|
| Passed 3 quests | 9/10 | 8/10 | **4/10** | 8/10 |
| Assassin hits Merlin, after 3 passed | 7/9 | 4/8 | 3/4 | 7/8 |
| Good wins | 2 | 4 | 1 | 1 |
| Merlin's vote accuracy (Servants ~0.6) | 1.00 | 0.81 | 0.84 | 0.97 |
| Merlin top voter (alone at the top) | 10 (7) | 10 (6) | 8 (4) | 10 (8) |
| Merlin's wrong votes: approved evil / rejected clean | 0 / 0 | **7 / 1** | 0 / 13 | 0 / 2 |
| Servants' wrong votes: approved evil / rejected clean | 30 / 9 | 35 / 2 | 45 / 5 | 41 / 6 |

None of these differences is significant at 10 pairs. On the fair comparison for Assassin hits, the seeds
where both C and cover passed 3 quests (n = 7), it is 5 hits against 4 (exact McNemar p = 1.0): most of the
7/9 to 4/8 gap came from which games reached an assassination. The final cover results are below.

## Cover vs C: final results

Haiku seeds 0-13 ([`haiku_cover_seeds_0-13.json`](haiku_cover_seeds_0-13.json)); seeds 14-39 were stopped by the
Claude Code session limit and not run. gpt-6.1-sol seeds 0-7 ([`sol_cover_seeds_0-7.json`](sol_cover_seeds_0-7.json)),
paired with the existing sol C batch; 8 games of API credit stay reserved for the demo. Every finished game is free
of model errors.

| | Haiku C | Haiku cover | sol C | sol cover |
|---|---|---|---|---|
| Games | 14 | 14 | 8 | 8 |
| Passed 3 quests | 12 | 11 | 8 | 7 |
| Good wins | 2 | 4 | 2 | 3 |
| Merlin's vote accuracy | 1.00 | 0.84 | 0.99 | 0.86 |
| Servants' vote accuracy | 0.57 | 0.57 | 0.82 | 0.68 |
| Merlin top voter (alone at the top) | 14 (11) | 14 (10) | 8 (5) | 8 (6) |
| Merlin's wrong votes: approved evil / rejected clean | 0 / 0 | 7 / 3 (70%) | 1 / 0 | 5 / 3 (63%) |
| Servants' wrong votes: approved evil / rejected clean | 44 / 14 (76%) | 55 / 3 | 14 / 6 (70%) | 26 / 10 |

Assassin hits, only on seeds where both C and cover passed 3 quests (the Assassin acts only then):

| | n | C hits | cover hits | C only | cover only | exact McNemar p |
|---|---|---|---|---|---|---|
| Haiku | 9 | 7 | 6 | 3 | 2 | 1.0 |
| gpt-6.1-sol | 7 | 5 | 4 | 2 | 1 | 1.0 |
| Both, pooled | 16 | 12 | 10 | 5 | 3 | 0.73 |

What this says:
- **No significant effect.** The cover is one hit lower on each model (12 of 16 against 10 of 16 pooled), and good
  wins rise from 4 to 7 of 22 games, but nothing is near significance at these sizes.
- **Quests hold.** One fewer 3-quest game on each model; the match-point override protects the deciding votes.
- **The errors are the right kind.** 63-70% of the covered Merlin's wrong votes approve an evil team, close to the
  Servants' 70-76% in C. The error-type explanation holds.
- **The mechanism goal is not met: Merlin is still the top voter in every game.** Merlin's accuracy falls (1.00 to
  0.84, 0.99 to 0.86), but the Servants' falls with it on gpt-6.1-sol (0.82 to 0.68): without Merlin's real-knowledge
  votes steering the table, the Servants approve more evil teams too. Voting by the exact public counting rule is
  also more accurate than real Servants are. A Merlin that votes like an ideal Servant still out-votes actual ones.

So the cover does not hide Merlin's votes; at best it blurs them, and the hit-rate gain is within noise. Hiding
Merlin from a vote-grading Assassin would need Merlin to vote like the Servants actually do in that game (their
error rate and kind), not like an ideal Servant, and without the cheap-error shortage that sank the cap.

## Negative result: a relative accuracy cap fails

The cap targets the Servants' accuracy in the same game, so it adapts to any model with nothing to tune.
It fails for two reasons, both visible above:

1. **The safe errors don't exist.** A cheap error needs a clean team that Merlin isn't on, early in a quest.
   Across all 10 cap v2 games there were 5 such votes. Cap v1 found its inaccuracy elsewhere, rejecting its
   own proposals and late clean teams, and lost the quests that decided the game (4/10 passed; twice in Q5
   Merlin's rejection was the deciding vote). Cap v2 protects those votes and is back to 8/10, but with
   nothing left to spend, Merlin votes the truth (0.97) and the Assassin hits 7/8, like C.
2. **They are the wrong kind.** Servants' wrong votes are mostly approving an evil team: 77% in Haiku C, 78%
   in gpt-6.1-sol C (98 of 126). A Merlin whose only errors reject clean teams doesn't look like a Servant
   even at a Servant's accuracy. The cover errs like a Servant (7 of 8 wrong votes approve evil, early, when
   one fail isn't decisive), which is why it is the strategy carried forward.

## Reproduce

```bash
python experiments/merlin_vote_leak.py runs/sol/rule_graph runs/sol/belief_graph runs/sol/chat_only
python experiments/merlin_strategies.py --baseline runs/haiku/rule_graph \
    runs/haiku/rule_graph_cover runs/haiku/rule_graph_cap_v1 runs/haiku/rule_graph_cap --seeds 0-9
python experiments/merlin_strategies.py --baseline runs/haiku/rule_graph runs/haiku/rule_graph_cover --seeds 0-13
python experiments/merlin_strategies.py --baseline runs/sol/rule_graph runs/sol/rule_graph_cover --seeds 0-7
```

Cap v1 is commit `abc5f84`, cap v2 is `e71d3b8`. Both ran with `configs/arena/haiku_rule_graph_cap.yaml`;
v1's logs were moved to `runs/haiku/rule_graph_cap_v1` (the code changed, the config hash didn't).
