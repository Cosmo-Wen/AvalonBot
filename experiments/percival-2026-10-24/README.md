# Percival experiment: game-by-game analysis

This report covers seven completed experiment games: P0 seeds 0–2 and P1 seeds 0–3. Smoke games and archived, failed, or interrupted attempts are excluded. Game numbers are zero-based, matching the log filenames. P0 seed 3 was stopped and is not scored. Only seeds 0–2 form matched comparisons.

## What the scores mean

Vote accuracy means approving an entirely good team or rejecting a team containing evil. Forced hammer votes are excluded. This measures whether Merlin's actions expose private knowledge, not whether an observer necessarily identifies Merlin. P(Merlin) in P0 is a single end-of-game LLM report. P1 probabilities are marginals of the four-world heuristic, recorded during play. Neither is a calibrated accuracy guarantee.

| Batch / game | Merlin / Percival / Morgana | Merlin vote accuracy | Percival vote accuracy | Final P(true Merlin) | Assassin shoots | Outcome |
|---|---|---:|---:|---:|---|---|
| P0 / 0 | P0 / P3 / P4 | 87.5% (7/8) | 87.5% (7/8) | 99.5% | P0: Merlin | Evil |
| P0 / 1 | P2 / P3 / P1 | 100% (4/4) | 100% (4/4) | 92.0% | P0: Servant | Good |
| P0 / 2 | P4 / P0 / P3 | 100% (3/3) | 100% (3/3) | 80.0% | P0: Percival | Good |
| P1 / 0 | P0 / P3 / P4 | 100% (8/8) | 75.0% (6/8) | 95.24% | P3: Percival | Good |
| P1 / 1 | P2 / P3 / P1 | 100% (6/6) | 66.67% (4/6) | 99.80% | P2: Merlin | Evil |
| P1 / 2 | P4 / P0 / P3 | 100% (10/10) | 80.0% (8/10) | 99.90% | P0: Percival | Good |
| P1 / 3 | P3 / P1 / P0 | 75.0% (6/8) | 100% (8/8) | 99.99% | P1: Percival | Good |

## Matched game 0

### P0: Percival solves the game but does not protect Merlin

Quest results were fail, fail, pass, pass, pass. Percival P3 initially proposed P1/P3, putting the Assassin on the opening team. When that failed, P3 knew that P1 supplied the fail: P3 knew their own alignment and card. Percival then consistently pushed the clean P0/P2/P3 trio and ended at 99.5% belief in the true Merlin P0.

Merlin approved the bad opening team, with a public justification that there was no public evidence against it. Afterward, Merlin voted correctly on every proposal and proposed the clean trio before it had succeeded. Merlin and Percival had the same 7/8 voting accuracy, so accuracy alone did not separate them.

The evil discussion explicitly made a timing distinction: Percival could identify the Assassin from their own failed quest, whereas Merlin's early clean-team selection and rejection of a bad team containing Merlin themselves looked like prior knowledge. The Assassin shot Merlin. This is a failure of the decoy despite successful Percival inference.

### P1: Percival becomes the Assassin's target despite imperfect votes

The quests were pass, fail, pass, pass. Percival P3 rejected their own clean P2/P3 opening proposal because the table assigned it 50% all-good probability, below the strict 55% cutoff. Percival also rejected the clean P0/P2/P3 trio at 48.92%, despite having advocated that trio in discussion. That rejection helped prevent the clean team being approved; it was one of several votes, not the only cause.

The later bad P0/P1/P2 team passed the vote and failed its quest. Percival's belief in P0 as Merlin rose to 95.24% at that team's public vote, before its quest result; it was unchanged immediately after the fail. Percival then supported the clean teams needed to win.

Merlin had a perfect 8/8 record and repeatedly challenged Percival's contradictory statements and votes. Nevertheless, both evil players called Percival's odd rejections possible deliberate cover for knowing the evil pair. The Assassin shot Percival. This is a decoy success, but the observed mechanism is suspicious inconsistency being interpreted as hidden knowledge, rather than two equally accurate good voters.

## Matched game 1

### P0: all good voters are equally accurate; the Servant takes the shot

All three quests passed. Merlin P2 and Percival P3 maintained the opening successful pair, added the Servant P0, and rejected the Assassin P4's attempt to replace Percival. Every good player voted correctly on all four non-hammer proposals.

Merlin used public-evidence language and defended the suspiciously overconfident attacks on P4, who Merlin privately knew was evil. The records are consistent with blending into the table, though they do not establish a private intention. Percival finished at 92% belief in Merlin.

Evil targeted the Servant P0, describing their quiet support for clean teams as more Merlin-like than P2/P3's conspicuous discussion. Merlin survived. Percival contributed sound teams, but the actual decoy was the Servant.

### P1: Percival identifies Merlin correctly but fails to resemble Merlin

All quests passed, although Quest 2 took all five proposal rounds and ended at the automatic-approval hammer.

Percival P3 reached 90.91% belief in P2 immediately after the opening vote. Morgana P1 had approved a team containing the other candidate P2; that behavior was strongly penalized in worlds where P1 was Merlin. This confidence came from the heuristic vote model, not a failed quest.

Despite believing P2 was Merlin, Percival rejected both the clean opening pair and the clean P0/P2/P3 trio that Percival themselves proposed. The trio's pre-vote all-good probability was only 45.45%: knowing which candidate is Merlin did not yet identify which non-candidate was the Assassin. The deterministic cutoff overrode the LLM's proposal and public support.

Merlin voted perfectly on all six non-hammer decisions. Evil explicitly contrasted Merlin's clean record with the Servant's bad approvals and Percival's rejections of clean teams. The Assassin shot Merlin. End-of-game P(true Merlin) was 99.80%, demonstrating that role identification and protecting Merlin are separate objectives.

## Matched game 2

### P0: chat-only Percival is already an effective decoy

All three quests passed without any rejected proposals. Merlin P4 opened with the clean P1/P4 pair; Percival P0 added themselves for the three-person quest. All good players had 100% voting accuracy.

Merlin's repeated successful-pair reasoning gave the same public rationale a non-informed good player could use. Percival, by contrast, selected the clean trio and challenged Morgana's unexplained suspicion of the Assassin. Evil described those actions as prior knowledge and shot Percival P0.

Percival's final P(true Merlin) was 80%. P0 therefore already produced the desired decoy effect in this seed; it is not unique to the four-world system.

### P1: initially fooled by Morgana, then a successful decoy

Quest results were pass, pass, fail, pass. The table initially favored Morgana P3 over Merlin P4, reaching 66.23% for Morgana after the opening vote. The true Merlin's opening proposal could have contained an Assassin under some possible worlds, so those worlds were penalized. Good-looking team selections do not necessarily increase a candidate's posterior in this model.

Percival P0 consequently proposed the bad P0/P1/P3 trio for Quest 2, but then rejected it: its all-good probability was 33.11%. This prevented their own bad proposal from passing, while creating an observable contradiction. Quest 2 ultimately used the clean trio at the hammer while P(Merlin=P4) was still about 50%.

On Quest 3, Percival supported the good P0/P1 pair but rejected another good pair, P1/P4, at 49.94% probability. Both good proposals were rejected by the table. The bad P1/P2 pair then passed and failed. Percival's belief in P4 rose to 90.89% at that public vote, before the fail; the fail itself did not move the probability at that moment. By the end, P(true Merlin) was 99.90%.

Merlin had a perfect 10/10 record. The Assassin nevertheless shot Percival, interpreting their rejection of evil teams—including their own proposal—as concealed knowledge. Again, the decoy effect is supported by evil's stated reasoning, but its mechanism is not simply Percival matching Merlin's voting accuracy. Compared with P0 on the same seed, P1 took longer, reached a hammer, and incurred an extra failed quest.

## Unpaired game 3: P1 only

The completed run's quest results were fail, fail, pass, pass, pass. Earlier quota-affected attempts are excluded.

Merlin P3 approved both opening teams despite knowing that the first contained Morgana P0 and the second contained Assassin P2. Their public reasons were to test teams without public evidence and to keep both members of the first failed quest off the next quest. This is the clearest behavioral example of Merlin concealing knowledge, although the logs cannot distinguish intentional camouflage from a model error with certainty. These approvals also put good one failed quest from defeat.

Percival P1 rejected both bad teams and every other evil-containing team, while approving every clean team: 8/8 accuracy. After the opening vote, the table was actually 85.71% confident that Morgana was Merlin; the failed quest returned it to roughly 50/50. Morgana's next proposal included the other candidate, which drove belief in the true Merlin to 90.91%. Subsequent votes and quest evidence moved it further; final P(true Merlin) was 99.99%.

Percival became the more visibly knowledgeable player, naming the correct evil pair as a working suspicion and selecting clean teams. Merlin finished at 75% accuracy, tied below Percival. Both evil players identified Percival as Merlin, and the Assassin shot Percival. This game most closely matches the intended mechanism: Merlin is less conspicuously accurate while Percival looks informed. It is unpaired because P0's corresponding game was stopped.

## Answers to the main questions

### Is Merlin disguising?

Merlin consistently disguises the *language*: tentative reads, requests for public evidence, warnings that passed quests clear nobody, and rationales based on continuity. It does not consistently disguise the *votes*. In the first three P1 games, Merlin was the uniquely most accurate good voter and never supported an evil-containing team. In the three P0 games, Merlin tied with other good voters rather than being uniquely highest.

P1 game 3 is the clearest exception: Merlin's two bad early approvals made Percival the highest-accuracy good voter, and evil targeted Percival. The prompt-only hidden-Merlin strategy is therefore inconsistent. Perfect accuracy also did not guarantee death: narrative and the timing of knowledge affected the Assassin's selection.

### How is Percival performing?

Role identification is strong at the end of these runs: P1 assigned the true Merlin 95.24%, 99.80%, 99.90%, and 99.99%. But it was confidently wrong early in games 2 and 3. These figures are heuristic posteriors, not empirical probabilities of correctness.

As a decoy, P1 drew the Assassin's shot in three of four games; P0 Percival drew it in one of three, and the P0 Servant drew it once. On the three matched seeds, however, both conditions had two good wins and one Assassin hit. No aggregate survival advantage is established by the matched results.

The largest implementation issue is policy coherence. Proposals and spoken endorsements are LLM-generated, but P1 votes use the hard all-good cutoff. Percival rejected their own proposal in three of the four completed P1 games, and contradicted an earlier spoken endorsement in the fourth. That is observable evidence the Assassin used, with different interpretations in different games. These wins do not yet establish the clean mechanism described in the plan.

## Recommended next iteration

1. Make Percival's proposals, public endorsements, and votes use one consistent policy. Expose the all-good calculation to the proposing/speaking decision or constrain proposed teams to ones the voter would support. Preserve the option to state cautious support without falsely promising approval.
2. Evaluate Merlin camouflage explicitly: non-hammer vote accuracy, rank, when each evil player becomes identifiable from public evidence, and whether evil's final argument actually distinguishes Merlin from Percival.
3. Diagnose early probability behavior and repeated, correlated soft evidence before changing factors. Passed quests intentionally contribute no hard eliminations, and proposals plus votes from the same candidate can repeatedly amplify a hypothesis. High confidence alone is not calibration.
4. If the policy changes, freeze a new experiment version and run a fresh paired comparison. Do not mix changed-policy games with these results or tune the fixed factors to these seven outcomes.

## Sources

`results.json` contains the completed-game metrics and final assassination targets used in this report. Raw run logs remain local and are not included in the repository. The seven completed games were run at medium reasoning with model `gpt-6.1-sol`, from implementation commit `a5abbbf`. Both batches are stopped; P0 game 3 was interrupted and excluded.

- P0: `runs/percival/p0/games/game_00000.jsonl` through `game_00002.jsonl`.
- P1: `runs/percival/p1/games/game_00000.jsonl` through `game_00003.jsonl`.
- Vote scores and final beliefs: completed `game_end.percival_metrics`.
- Behavioral evidence: public `discussion`, `team_proposed`, `team_votes`, logged tool arguments, and `evil_chat` / `assassination` events.
- Belief timing and all-good probabilities: `percival_beliefs` snapshots immediately following each public proposal/vote/quest result.
