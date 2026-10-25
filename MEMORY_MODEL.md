# Player Memory Model

Every player keeps its own private memory of the game, stored as a small knowledge graph over a log of what it observed. This document defines that memory: what goes in it, who may write it, how beliefs are computed from it, and how it reaches the prompt. It replaces the earlier Belief Graph Spec and keeps that spec's core ideas: players and teams as nodes, evidence as edges, actions kept separate from talk, and the 6-pair rule.

## Principles

1. **One memory per player.** No memory is shared between seats, including memory of public events. Each player gets its own copy.
2. **A player remembers only three things:**
   - what it observed in public (what was said, proposals, votes, quest results)
   - what it privately knows (its role, who it saw at the start, its own quest cards)
   - what it thought (its own beliefs, notes, and reasons)
3. **No one else's thinking.** Another player's reasoning, notes, beliefs, or tool-call justifications never enter this player's memory. A player learns what others think only from what they said out loud.
4. **Every conclusion cites its evidence.** Each edge points to the log entries it came from, so a player can always go back to the exact words.
5. **Actions outweigh talk.** Votes, proposals, and quest results cost a player something, and talk doesn't. The two kinds of evidence stay separate so contradictions between them stay visible.

## Game facts the model relies on

Five players: Merlin, 2 Loyal Servants, the Assassin, and a Minion. Team sizes per quest are 2, 3, 2, 3, 3, and one Fail card fails any quest. The facts below follow from this.

- A failed quest with `k` Fail cards proves that at least `k` team members are evil. This is a fact about a group, not about any one player.
- A passed quest proves nothing, because evil players may choose to pass.
- A Loyal Servant knows it is good, so exactly 2 of its 4 opponents are evil. That leaves only 6 possible evil pairs.
- Merlin knows both evil players. The evil players know each other. Nobody else knows anything at the start.
- The engine auto-approves the 5th proposal of a quest. The official rule is that Evil wins after 5 rejections. Our variant must be stated in any write-up.

## Time and IDs

The engine calls the quest index `turn` and the proposal attempt `round_num`, both counted from 0. Everything in memory uses:

| Field | Meaning | Example |
| --- | --- | --- |
| `seq` | Global event number for the game, shared by all players | `#16` |
| `quest` | Quest number, counted from 1 (engine `turn` + 1) | `2` |
| `attempt` | Proposal attempt within the quest, counted from 1 (engine `round_num` + 1) | `1` |
| Team label | `Q{quest}.{attempt}` | `Q2.1` |

Every log entry has a `seq`, and every edge cites one or more of them in `sources`.

## The three layers

Each player's memory has three layers.

### Layer 1: Observation log

An append-only list of what this player saw or heard. Only the runner writes it, by delivering broadcast events.

| Entry | Fields |
| --- | --- |
| `utterance` | `seq`, `quest`, `attempt`, `speaker`, `text` |
| `proposal` | `seq`, `quest`, `attempt`, `leader`, `members` |
| `team_vote` | `seq`, `quest`, `attempt`, `votes` (each player's approve or reject), `approved` |
| `quest_result` | `seq`, `quest`, `members`, `fails`, `success` |
| `evil_chat` | `seq`, `speaker`, `text`. Evil players only, during the pre-assassination discussion (demo only) |

The log is never summarized away. Prompts show part of it, and the recall tools reach the rest.

### Layer 2: Private knowledge

Written once at setup, plus each quest card this player plays.

- `role` and `side`
- `seen_evil`: Merlin sees both evil players, and each evil player sees the other
- `my_quest_cards`: the card this player played on each quest it joined

### Layer 3: Own reasoning

Written only by this player's own calls:

- the knowledge graph (below)
- beliefs (`p_evil`, or `p_merlin` for evil in the demo)
- a short note per opponent, at most 15 words
- self edges: what this player claimed, and why it voted or proposed as it did

## Knowledge graph

### Nodes

**Player.** One node for each of the 5 seats, including the owner (`self`).

**Team.** One node per proposal, including rejected ones.

| Field | Meaning |
| --- | --- |
| `label` | `Q{quest}.{attempt}` |
| `leader`, `members` | From the proposal |
| `votes`, `approved` | From the team vote |
| `fails` | Number of Fail cards if the team went on a quest, otherwise null |

Messages are not nodes. They live in the observation log, and edges cite them by `seq`.

### Edges

Every edge has `id`, `seq` (when it happened), `quest`, `attempt`, and `sources` (a list of log `seq` values).

| Edge | From → To | Written by | Weight | Extra fields |
| --- | --- | --- | --- | --- |
| `member_of` | player → team | code | Hard if the team failed, none if it passed | |
| `proposed` | player → team | code | Medium | |
| `voted_approve` / `voted_reject` | player → team | code | Medium | |
| `accused` / `defended` | player → player | owner's extraction call | Weak | `quote` (at most 10 words) |
| `backed_team` / `opposed_team` | player → team | owner's extraction call | Weak | `quote` (at most 10 words) |
| `claimed_role` | player → self | owner's extraction call | Weak | `role`, `quote` |
| `i_said` | self → player or team | owner, from its own utterance | n/a | `quote` |
| `i_reasoned` | self → team | owner, from its own vote or proposal call | n/a | `reason` (at most 20 words) |

"Code" means the edge is computed deterministically from a broadcast event, inside the owner's memory. It is still that player's copy.

`backed_team` and `opposed_team` exist so that talk about a team can be checked against the same player's vote on that team.

### Contradiction flags

Code, not the LLM, sets a contradiction flag (⚠). The flag goes on a player who:

- `accused` Y, and later voted to approve a team containing Y
- `backed_team` T and then voted to reject T, or `opposed_team` T and then voted to approve T

The flag cites both edges. `defended` is not checked, because a player can reject a team containing someone they defended for many unrelated reasons.

## Who has which beliefs

| Seat | Memory (layers 1 to 3) | Beliefs | Why |
| --- | --- | --- | --- |
| Loyal Servant ×2 | Yes | `p_evil` over its 4 opponents | These are the agents the ablation measures |
| Merlin | Yes | None. It already knows the evil players | It still needs its log and self edges to stay subtle |
| Assassin, Minion | Yes | None in the ablation. `p_merlin` over the 3 good players in the demo only | The evil team must behave identically across conditions |

### Coherence rules

The beliefs must always be internally consistent:

- **`p_evil` values sum to 2** across a Servant's 4 opponents, because exactly 2 are evil.
- **`p_merlin` values sum to 1** across the 3 good players, because exactly 1 is Merlin.
- **Failed teams:** for each failed team, the `p_evil` values of its members, excluding the owner, sum to at least that team's `fails`.
- **Forced values:** any opponent who appears in no remaining possible pair has `p_evil` = 0, and any opponent in every remaining pair has `p_evil` = 1.

The surest way to meet these rules is to store beliefs as weights over the 6 possible evil pairs and derive each player's `p_evil` from them. Condition C does exactly that.

## Belief updates

### Possible pairs (all conditions)

1. List the 6 possible evil pairs among the owner's 4 opponents.
2. For each failed quest with `k` Fail cards, remove every pair with fewer than `k` members on that team, not counting the owner. If the owner was on a 2-person team that failed, this leaves only pairs containing the other member.
3. If the owner itself played Fail on that quest, subtract its own Fail from `k` first. A quest the owner failed alone adds no constraint, and the prompt shows it as "all played by you".
4. A passed quest removes nothing.
5. If no pair fits every failed quest, keep the pairs that fit the most, and mark the beliefs as inconsistent. This can only happen when a recorded game broke the rules. In pilot game 4, a Servant played Fail. The coherence check then enforces only the failed quests that every remaining pair fits.

Code maintains this list for each Servant in every condition. It is used to check beliefs and to print the constraint lines in the prompt.

### Condition C: rule-based beliefs

1. Give each possible pair weight 1.
2. For each failed quest, and each opponent who voted on that team:
   - if they voted to approve, multiply every pair containing them by `APPROVE_FAILED = 2.0`
   - if they voted to reject, multiply every pair containing them by `REJECT_FAILED = 0.5`
3. Normalize the weights so they sum to 1. An opponent's `p_evil` is the total weight of the pairs that contain them. Every pair has 2 members, so the four `p_evil` values sum to 2.

`proposed` edges are shown in the prompt and read by the LLM, but the rule doesn't use them. A leader's approve vote already counts, so adding the proposal would count it twice. Fix both factors before launch and never tune them on results.

### Condition B: LLM beliefs

The owner's extraction call (below) proposes new `p_evil` values. Code then checks them against the coherence rules:

1. Values must be in the range 0 to 1, and forced values must be exactly 0 or 1.
2. The four values must sum to 2, within 0.05.
3. Each failed team's members must sum to at least its `fails`, within 0.05.

If the check fails, code re-asks once and includes the specific error. If the second answer also fails, code uses the Condition C values for that update and logs `belief_fallback`. The fallback rate is reported as a metric.

### Evil `p_merlin` (demo only)

The evil graph uses the same nodes and edges over the 3 good players, with `p_merlin` summing to 1. It is off by default, so evil plays identically in every ablation condition. Turn it on with `merlin_graph=True` on the agents, as the web server's heuristic live game does. When it is on, evil players also read each discussion round into talk edges.

The signal is a good player who is too accurate. Code computes it with fixed factors, the same way as Condition C:

1. Give each good player weight 1.
2. For each team vote before the hammer round (the hammer team goes regardless, so those votes carry no signal):
   - an accurate vote (reject a team with evil on it, or approve a clean team) multiplies the voter's weight by `MERLIN_ACCURATE_VOTE = 1.5`
   - an inaccurate vote divides it by 1.5
   - a decisive reject that sank a team with evil on it (the team got exactly 2 approvals) multiplies it by a further `MERLIN_PIVOTAL_REJECT = 1.5`
3. For each good player who accused an evil player before any failed quest exposed that player, multiply by `MERLIN_EARLY_ACCUSATION = 2.0`. Each accuser and target pair counts once, because repeating an accusation is not new evidence.
4. Normalize so the values sum to 1.

Each evil player keeps its own `p_merlin`. The pre-assassination discussion goes into both evil players' logs as `evil_chat`, and nobody else hears it. The runner logs the Assassin's `p_merlin` just before the assassination and returns it as `assassin_p_merlin` for the demo panel. The heuristic Assassin shoots the top candidate. The LLM Assassin sees the graph in its prompt and falls back to the top candidate.

How well this works depends on how the good players talk. With the expressive heuristic dialogue on `main`, the Assassin hit Merlin 37% of the time with the graph on, versus 31% with it off (223 assassinations each, out of 600 seeded games). There, the heuristic Merlin plays much like a Servant (72% vs. 63% vote accuracy), so there is little to detect. With the plainer heuristic dialogue on `arena-engine`, Merlin names a real evil player from the first round, and the Assassin hit Merlin 72% of the time (68 of 94). Random guessing hits 33%. The real test is with LLM players.

## Update schedule

| Moment | What is written | Writer |
| --- | --- | --- |
| Setup | Layer 2 | Engine, then the runner delivers it to each player |
| Each utterance | `utterance` entry in every player's log | Runner |
| Owner speaks | `i_said` edges in the owner's own graph | Owner |
| End of a discussion round, before the proposal | Talk edges, notes, and (in condition B) `p_evil` | Each player's own extraction call |
| Proposal, team vote | Log entries, then `proposed` and vote edges | Runner, then code in each player's memory |
| Owner votes or proposes | `i_reasoned` edge | Owner |
| Quest result | Log entry, `member_of` edges, possible pairs; condition C beliefs | Runner, then code |
| Owner plays a quest card | `my_quest_cards` | Owner |

## Extraction call

There is one call per player per discussion round, and it runs only in that player's context.

**Input.** The owner's current prompt table (below), its own record, and the log entries for this discussion round with their `seq` values.

**Output.** JSON, through a tool call:

```json
{
  "edges": [
    {"type": "accused", "from": 4, "to": 2, "sources": [12], "quote": "Player 2's team looks too convenient"},
    {"type": "defended", "from": 1, "to": 3, "sources": [11], "quote": "Player 3 is fine, Q1 was bad luck"}
  ],
  "p_evil": {"1": 0.75, "2": 0.25, "3": 0.75, "4": 0.25},
  "notes": {"1": "proposed and approved the failed Q1.1", "4": "pushing hard against P2"}
}
```

`p_evil` is only read in condition B. Each edge's `from` must be the speaker of every entry it cites. Code drops any edge whose `sources` point to log entries the owner doesn't have.

## Prompt serialization

The engine renders each player's memory into the top of that player's own prompt. The example below is for Servant P0 after Q2.1, with condition C beliefs.

Events in this example:
- Q1.1: P1 proposed {1, 3}. P0, P1, and P3 approved, and P2 and P4 rejected. The quest got 1 Fail.
- Q2.1: P2 proposed {0, 2, 4}. P0, P2, and P4 approved, and P1 and P3 rejected. The quest passed.
- Talk: P2 accused P1 (#9). P0 said "P1 and P3 owe us an explanation" (#10). P1 defended P3 (#11). P4 accused P2 (#12), then approved P2's team.

Checking the beliefs: Q1.1 removes the pair {2, 4}. Approving Q1.1 doubles every pair containing P1 or P3, and rejecting it halves every pair containing P2 or P4. That gives weights {1,2}=1, {1,3}=4, {1,4}=1, {2,3}=1, {3,4}=1, for a total of 8. So P1 = (1+4+1)/8 = 0.75, P3 = (4+1+1)/8 = 0.75, P2 = (1+1)/8 = 0.25, and P4 = (1+1)/8 = 0.25. They sum to 2. Q2.1 passed, so it changes nothing.

```text
Constraints: Q1.1 {1,3} → 1 fail (at least 1 of P1, P3 is evil)
Player | P(evil) | Actions | Talk
P1 | 0.75 | proposed, approved Q1.1; on Q1.1 (fail); rejected Q2.1 | defended P3 (#11)
P2 | 0.25 | proposed, approved Q2.1; on Q2.1 (pass) | accused P1 (#9)
P3 | 0.75 | approved Q1.1; on Q1.1 (fail); rejected Q2.1 | quiet
P4 | 0.25 | rejected Q1.1; approved Q2.1; on Q2.1 (pass) | accused P2 (#12) ⚠ then approved Q2.1
Your record: approved Q1.1 ("first attempt, no information"); said "Let's be careful on the first quest." (#1); said "P1 and P3 owe us an explanation." (#10)
```

This is the exact output of `PlayerMemory.render_table()` for these events. The test suite reproduces this example. P2's `rejected Q1.1` has dropped off the row because only the 3 most recent actions that aren't failed-quest memberships are shown.

Rules for the table:

- **Constraints:** one line per failed quest, always shown.
- **Actions:** membership in any failed team is always shown, plus the 3 most recent other action edges.
- **Talk:** the 2 most recent talk edges, with the `seq` they cite.
- **⚠:** set by code, as defined above.
- **Your record:** the owner's most recent `i_said` and `i_reasoned` edges.
- **Beyond the table:** anything older is reached through the recall tools.

In conditions B and C, the table is followed by the log entries from the current and previous quest. In condition A, the table is replaced by the owner's full observation log and its own notes (see the ablation section below). Merlin and the evil players always get their full log plus their own record.

## Recall tools

Retrieval is an exact lookup over the owner's own memory. There is no shared store and no embedding search.

| Tool | Returns |
| --- | --- |
| `recall(player=None, from_seq=None, to_seq=None, kinds=None)` | Matching entries from the owner's observation log |
| `quote(seq)` | The full text of one log entry |
| `evidence(player)` | All edges about that player, each with its `sources` |
| `my_record(quest=None)` | The owner's own `i_said` and `i_reasoned` edges and quest cards |

Embedding search over the owner's own utterances is an option for later, but only if live voice games produce transcripts too long for the prompt.

## Isolation guarantees

- Each `Agent` owns its own `PlayerMemory`. The runner writes layer 1 only through `observe_event`, and only for broadcast events.
- Tool-call fields like `reasoning` and `reason` are written into the caller's own `i_reasoned` edges, and are never broadcast.
- Quest cards are broadcast only as a total `fails` count.
- `evil_chat` is delivered only to evil seats.
- **Test:** after a seeded game, no agent's `i_reasoned` text, notes, or belief values appear in any other agent's memory. Every edge's `sources` must point to entries in its owner's own log.

## Ablation conditions

The evil team is identical in every condition: same agents, prompts, and memory. Only the Loyal Servants change. Every Servant gets the same full observation log, the same private knowledge, and one extra LLM call per discussion round. That way, differences in results come from how memory is structured, not from how much the agent sees or how much compute it gets.

| Condition | Servant's prompt | Extra call per discussion round | `p_evil` from |
| --- | --- | --- | --- |
| A: log only | Full observation log, plus its own free-text notes | Reflection call that writes free-text notes | No beliefs. Asked for `p_evil` once, at game end, for the metrics |
| B: LLM graph | Graph table, recent log entries, recall tools | Extraction call | The extraction call, checked by code |
| C: rule graph | Graph table, recent log entries, recall tools | Extraction call (talk edges and notes only) | The Condition C rule |

### Metrics

- Good-team win rate, with 95% bootstrap confidence intervals
- Spy-identification accuracy: at game end, are a Servant's top-2 suspects exactly the two evil players?
- Brier score of the Servants' final `p_evil` values
- Merlin survival rate
- `belief_fallback` rate in condition B
- Contradiction-flag precision: how often a flagged player was actually evil

## Mapping to the code

| File | Change |
| --- | --- |
| `avalon/memory.py` (new) | `PlayerMemory` with the three layers, the observation log, and the recall functions |
| `avalon/belief_graph.py` | Team nodes, typed edges with `sources`, the pair table, Condition C rule, coherence checks, prompt table. Replace the current per-player nudges (+0.35 × fails ÷ team size on failure, −0.10 on pass), because they ignore the "exactly 2 evil" structure and treat a pass as evidence |
| `avalon/agents.py` | Replace `chat_history` with `PlayerMemory`. Add `i_said` and `i_reasoned` writes. Remove the 15-line history limit |
| `avalon/llm_agent.py` | Extraction call, reflection call (condition A), recall tools |
| `avalon/tools.py` | Extraction schema. Replace `update_belief` with the full extraction output |
| `avalon/runner.py` | Global `seq`, per-player delivery, `evil_chat` channel for the demo |
| `avalon/replay.py` (new) | Reenacts a recorded arena game (`games/game_*.jsonl`) into each player's memory and checks every step against the engine. Hand-labelled talk edges stand in for extraction |
| `tests/` | Isolation test, coherence-rule tests, a Condition C rule test that matches the example above. `test_replay_game4.py` replays pilot game 4 with `game4-all-fixes/talk_edges.json` |

## Out of scope

- Second-order beliefs, such as what P2 thinks P3 is
- Belief graphs for Merlin or the evil team in the ablation
- Learned weights. Everything is prompted or rule-based
- Shared memory, or memory carried across games


## Percival and Morgana

The optional five-role experiment uses Merlin, Percival, Servant, Assassin, and Morgana.
Percival's private knowledge contains an unlabeled pair of Merlin/Morgana candidates.
P0 retains that knowledge and chat history. P1 additionally owns `PercivalBelief`, a four-world
log-weight table whose P(Merlin), P(evil), and team probabilities are consistent marginals.
It updates only from delivered public proposals, completed votes (excluding forced hammer
votes), and quest outcomes. Discussion cannot eliminate or reweight worlds. Only failed
quests eliminate worlds; contradictory hard evidence raises an error without resetting weights.
The remaining Servant retains the existing six-pair condition-C model. Evil stays chat-only.
Private observer snapshots in arena logs are not delivered to any player.
