# AvalonBot: Architecture, Design Decisions & Technical Log

This document provides a comprehensive log of the architectural choices, engineering trade-offs, and technical discoveries made during the design and development of **AvalonBot**. It is maintained so collaborators and future contributors can understand the system design and the research methodology.

> The voice layer (Boson Higgs TTS and Realtime), the LiveKit avatars and the talking-face clips were removed after the hackathon. Their design notes are in git history, before the commit that removed `speech/`.

---

## 1. Executive Summary & Project Mission

**AvalonBot** is an LLM social-deduction benchmark with a playable web table.

### The Two Core Pillars
1. **Scientific Benchmark (Ablation Study):** Evaluating whether structured external state tracking (**Belief Graphs**) outperforms unstructured, raw token context (**Chat History**) in high-entropy social deduction environments (*The Resistance: Avalon*).
2. **Live Play:** A human takes one seat in the browser and plays against the agents by typing, while spectators watch each agent's belief graph update.

```mermaid
flowchart TD
    subgraph Core Engine ["Core Engine (Single Source of Truth)"]
        GE[avalon.engine.AvalonEngine]
        BG[avalon.belief_graph.BeliefGraph]
    end

    subgraph Agents ["Agent Layer"]
        HA[HeuristicAgent]
        LLM[LLMAgent (Cond A / B)]
        HUM[HumanAgent]
    end

    subgraph Web ["Web Table"]
        WS[server.ws_server (FastAPI WebSocket)]
        UI[frontend (React spectator UI)]
    end

    GE -->|Broadcast Events| Agents
    Agents -->|Tool Calls: propose, vote, assassinate| GE
    GE -->|Events| WS
    WS <--> UI
    HUM <-->|Typed lines and actions| WS
```

---

## 2. Avalon-LLM Analysis & Engine Architecture

### Analysis of the Original Codebase (`Avalon-LLM` / `AvalonBench`)
Before writing AvalonBot, we conducted an in-depth audit of the MIT `Avalon-LLM` repository:
- **Strengths:** Established prompt architectures, state serialization techniques, and game metric formulations (Win Rate, Brier score, Spy-ID accuracy, and Merlin survival).
- **Critical Flaw Discovered:** The original `Avalon-LLM` codebase stored mutable game state in **class attributes (`cls`)** rather than per-instance attributes (`self`). In asynchronous or parallel evaluation, multiple game instances cross-contaminated each other's player lists, quest outcomes, and vote records.
- **Latency Bottleneck:** Generating long chain-of-thought monologues for all 5 players created turn latencies of 15–30 seconds—unusable for interactive human play.

### AvalonBot Architectural Decisions
1. **Zero-Leakage State Machine (`avalon/engine.py`):**
   - Clean, purely instance-based Python state machine.
   - Enforces strict canonical Avalon rules:
     - 5-player role distribution: 3 Good (Merlin, 2 Loyal Servants) vs. 2 Evil (Assassin, 1 Minion).
     - Strict team size matrices per quest: `[2, 3, 2, 3, 3]`.
     - 5 proposal rounds per quest; auto-approval on the 5th round (Hammer rule).
     - Secret quest voting: Good players must pass; Evil players can strategically fail or pass.
     - Assassination phase: If Good secures 3 passed quests, Evil gets one shot to identify Merlin.
2. **Decoupled Event-Driven Runner (`avalon/runner.py`):**
   - Agents never mutate engine state directly. They observe broadcasted events (`utterance`, `team_proposed`, `team_vote_result`, `quest_result`) and submit actions via typed interfaces.
   - Observers (the arena logger, the web server) subscribe to the event bus through `on_event`, so the same runner drives self-play and live games.

---

## 3. The Belief Graph & Evaluation Methodology

### Mathematical Formulation (`avalon/belief_graph.py`)
In raw LLM play (Condition A), models hallucinate past votes or lose track of who approved failed missions when context windows grow. Condition B equips Good agents with an explicit **Belief Graph**:

1. **Probability Distribution:**
   Each Good player maintains a continuous probability $P(\text{Evil}_j) \in [0.01, 0.99]$ for all players $j \neq \text{self}$.
   - **Initial Prior:** $P(\text{Evil}_j) = 0.5$ (since 2 out of 4 other players are evil).
   - **Merlin Prior:** For Merlin, true evils are initialized to $1.0$ at Turn 0.
2. **Evidence Graph:**
   A directed bipartite graph linking players to timestamped game events:
   - `PROPOSED`: Proposed a team that subsequently failed or passed.
   - `VOTED_APPROVE` / `VOTED_REJECT`: Voting alignment on teams.
   - `QUEST_MEMBER`: Cast a secret vote on a mission that failed.
3. **Prompt Injection Serialization:**
   Before generating discussion or casting votes, the graph is serialized into a markdown table injected directly into the LLM prompt:
   ```markdown
   ### Current Belief Table (Your Internal Analysis)
   | Player | P(Evil) | Status | Recent Evidence |
   |---|---|---|---|
   | Player 0 | 0.85 | High Suspect | Approved failed Q1 team [0, 1]; Voted Reject on clean team |
   | Player 2 | 0.20 | Likely Good | Was on passed Q2 team; Proposed clean roster |
   ```

### Metric Suite
- **Good-Team Win Rate:** Primary win condition (3 passed quests + Merlin survival).
- **Spy-ID Accuracy:** Boolean flag: at game conclusion, are the agent's top-2 suspects *exactly* the true evil players?
- **Brier Calibration Score:**
  $$\text{Brier} = \frac{1}{N-1} \sum_{j \neq \text{self}} (P(\text{Evil}_j) - y_j)^2 \quad \text{where } y_j \in \{0, 1\}$$
  Measures probabilistic calibration (0.0 is perfect calibration).
- **Merlin Survival Rate:** Proportion of Good wins where the Assassin chooses an innocent servant instead of Merlin.

---

## 4. Tool Calling Protocol

AvalonBot defines 5 formal JSON tools in `avalon/tools.py`, in the OpenAI Chat Completions format. `claude_cli` and `codex_cli` seats get the same tools, rendered into the prompt and parsed back from a JSON reply.

1. `propose_team(team)`: Leader nominates players.
2. `vote_on_team(vote)`: Approve/Reject team.
3. `vote_on_quest(vote)`: Secret Pass/Fail quest vote.
4. `assassinate(target)`: Assassin selects suspected Merlin.
5. `update_belief(player_id, p_evil, rationale)`: Good players update their belief graph.

---

## 5. Chronological Changelog & Milestones

- **Milestone 1:** Evaluated `Avalon-LLM` and designed the 5-player isolated architecture.
- **Milestone 2:** Initialized GitHub repo (`KhuzemahHQ/AvalonBot`), created `README.md`, `.gitignore`, `engine.py`, `belief_graph.py`, `runner.py`, and 8 passing unit tests.
- **Milestone 3:** Integrated Boson AI Higgs TTS 3 (`speech/boson_tts.py`) and Realtime client (`speech/boson_realtime.py`).
- **Milestone 4:** Resolved HTTP 400 voice registry errors; built offline PCM synthesizer fallback.
- **Milestone 5:** Discovered Boson Higgs control token vocabulary; introduced `<|prosody:expressiveness_high|>`, whispering, shouting, and laughter SFX.
- **Milestone 6:** Implemented dynamic emotional escalation across game rounds and created this comprehensive technical log.
- **After the hackathon (2026-10-25):** Removed the voice layer, LiveKit avatars and face clips; added Claude Code seats (`provider: claude_cli`).

---

## 6. Running and Testing

```bash
# 1. Run all unit tests
python -m pytest tests/

# 2. Play one offline game with heuristic bots (no model calls)
python -m arena run --fake --config configs/arena/haiku_chat_only.yaml --run-dir runs/fake

# 3. Serve the web table (then `npm run dev` in frontend/)
python -m uvicorn server.ws_server:app --port 8000
```
