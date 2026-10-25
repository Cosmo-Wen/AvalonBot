# AvalonBot run logs (archive)

Raw JSONL game logs behind the results in `experiments/` on `main`. They are not regenerable:
the sol batch was 8,674 calls on `gpt-6.1-sol` (Boson), which is no longer available.

| File | Contents |
|---|---|
| `runs-sol.tar.xz` | `runs/sol/`: A `chat_only`, B `belief_graph`, C `rule_graph` (40 paired seeds, 2026-10-24); also `rule_graph_cover` and `rule_graph_hidden`, superseded Merlin-strategy runs |
| `runs-haiku.tar.xz` | `runs/haiku/`: Haiku pilot via Claude Code (A, B, C); `rule_graph_cap*` / `rule_graph_cover` are superseded Merlin-strategy runs |
| `runs-smoke-throughput.tar.xz` | Smoke tests and the Boson throughput measurements |

Not included: the Percival P0/P1 logs (only `experiments/percival-2026-10-24/p1_game_00003.jsonl`
survives in git; the rest live on another machine).

Each run's `manifest.json` records its config and `git_sha`. The Haiku runs and the superseded
Merlin-strategy runs point at commits on the `merlin-vote-cover` branch (e.g. `486bac6`), which is
kept unmerged for that reason. Several Haiku manifests say `git_dirty: true`.

Restore: `tar -xJf runs-sol.tar.xz` from the repo root. Verify: `sha256sum -c SHA256SUMS`.
