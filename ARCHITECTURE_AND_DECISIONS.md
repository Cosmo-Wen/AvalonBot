# AvalonBot: Architecture, Design Decisions & Technical Log

This document provides a comprehensive log of the architectural choices, engineering trade-offs, and technical discoveries made during the design and development of **AvalonBot**. It is maintained so collaborators and future contributors can understand the system design, the empirical findings regarding Boson AI's speech models, and the research methodology.

---

## 1. Executive Summary & Project Mission

**AvalonBot** bridges rigorous LLM social deduction benchmarking with interactive, real-time voice synthesis.

### The Two Core Pillars
1. **Scientific Benchmark (Ablation Study):** Evaluating whether structured external state tracking (**Belief Graphs**) outperforms unstructured, raw token context (**Chat History**) in high-entropy social deduction environments (*The Resistance: Avalon*).
2. **Real-Time Spoken Interaction:** Giving autonomous agents unique vocal personalities with emotional prosody and non-verbal reactions using **Boson AI's Higgs TTS 3** and **Higgs Realtime**, allowing human players to converse naturally at the table.

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

    subgraph Speech ["Boson AI Voice Layer"]
        TTS[HiggsTTSClient (POST /v1/audio/speech)]
        RT[HiggsRealtimeClient (WebSocket)]
        AC[audio_cache/ PCM WAVs]
    end

    GE -->|Broadcast Events| Agents
    Agents -->|Tool Calls: propose, vote, assassinate| GE
    GE -->|Spoken Utterances| TTS
    TTS -->|PCM 24kHz Audio| AC
    HUM <-->|Audio In / Out| RT
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
   - Voice synthesis is completely decoupled as a subscriber to the event bus. If voice synthesis fails or is muted, the simulation and evaluation runner executes at full speed without interruption.

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

## 4. Boson AI Speech & Voice Discoveries

Integrating Boson AI's **Higgs TTS 3** and **Higgs Realtime** yielded several critical technical discoveries regarding acoustic conditioning, token parsing, and voice registry constraints:

### Discovery 1: Built-in Voices vs. Custom Voices
- **Constraint:** Calling `POST /v1/audio/speech` with fictitious names like `"male_1"`, `"female_1"`, or OpenAI voice names (`"alloy"`, `"echo"`) triggers:
  ```json
  HTTP 400: Unknown voice 'male_1'. Upload a voice first via POST /v1/audio/voices, or use ref_audio + ref_text
  ```
- **Architectural Decision:** Without pre-registered cloned voices, all seats must point to `"default"` (`os.getenv("BOSON_VOICE_X", "default")`). Differentiating identical base voices into distinct characters must therefore be accomplished through **inline delivery tags**, **tempo shifts**, and **stylistic modifiers**.

### Discovery 2: The Fallback Waveform Synthesizer
- **Problem:** If a network blip, missing API key, or invalid voice name crashes synthesis, the entire game engine would crash.
- **Solution:** We implemented `_generate_offline_wav()` in `speech/boson_tts.py`. If Boson returns an error or no key is present, it writes a clean, distinct-frequency PCM sine wave (220Hz to 659Hz) to `audio_cache/`. This allowed local end-to-end development before API keys were added.

### Discovery 3: Why Simple Emotion Tags Felt Flat
During initial testing, lines tagged with `<|emotion:suspicious|>` sounded acoustic-flat and robotic.
1. **Acoustic Reality:** In acoustic modeling, "suspicion" is modeled as restrained, low-pitch, low-variance speech. Over laptop speakers, this registers as flat or monotone.
2. **Invalid Tag Syntax:** Tags like `<|speed:0.92|>` and `<|emotion:confident|>` do **not** exist in Boson's vocabulary. The model silently discarded them and reverted to neutral prosody.
3. **The Expressiveness Multiplier:** Boson's model requires the dedicated token:
   ```text
   <|prosody:expressiveness_high|>
   ```
   Without this token, the acoustic decoder remains constrained to a conservative, conversational pitch range.

### Discovery 4: Verified Boson Control Token Grammar
Through testing against Boson documentation and live API endpoints, we confirmed the supported token categories:

| Category | Valid Syntax & Values | Auditory Effect in Avalon |
|---|---|---|
| **Emotion** | `<|emotion:anger|>`, `<|emotion:determination|>`, `<|emotion:enthusiasm|>`, `<|emotion:fear|>`, `<|emotion:amusement|>`, `<|emotion:contemplation|>` | Dramatic shifts in pitch inflection, attack, and vocal tension. |
| **Style** | `<|style:whispering|>`, `<|style:shouting|>` | Converts Merlin's advice into a genuine hushed whisper; pushes high vocal effort for accused players. |
| **Prosody** | `<|prosody:expressiveness_high|>`, `<|prosody:speed_fast|>`, `<|prosody:speed_slow|>`, `<|prosody:pause|>` | Unlocks wide pitch excursions, adjusts speech rate, and adds dramatic breath pauses. |
| **SFX** | `<|sfx:laughter|>Haha!`, `<|sfx:sigh|>Uh,` | Non-verbal vocalizations (laughter, sighs) when paired with immediate text onomatopoeia. |

### Discovery 5: Lexical Prosody Conditioning
Because Higgs TTS is an auto-regressive multimodal model, its prosody is conditioned directly on the text syntax.
- **Dry text:** *"I am putting together 2 players with solid records."* $\rightarrow$ Model outputs flat, monotonic speech.
- **Conversational text:** *"Wait, hold on! <|prosody:pause|>Player 0's actions make me furious! Why did you vote approve on a sabotaged team?!"* $\rightarrow$ Model generates high pitch peaks, natural staccato cadence, and emotional urgency.

---

## 5. Vocal Profiles per Seat

Using Boson's verified inline tags, each seat was assigned an acoustic identity matching their role:

| Seat | Role | Vocal Archetype | Active Control Tokens |
|---|---|---|---|
| **Player 0** | Minion | Forceful, determined soldier; loud bluffer | `<|emotion:determination|><|prosody:expressiveness_high|>` |
| **Player 1** | Loyal Servant | Earnest, passionate defender of Arthur | `<|emotion:enthusiasm|><|prosody:expressiveness_high|>` |
| **Player 2** | Loyal Servant | Fast, skeptical investigator; sharp outrage | `<|emotion:anger|><|prosody:speed_fast|><|prosody:expressiveness_high|>` |
| **Player 3** | Assassin | Slow, chilling, mocking with laughter | `<|emotion:amusement|><|prosody:speed_slow|><|prosody:expressiveness_high|><|sfx:laughter|>Haha!` |
| **Player 4** | Merlin | Cryptic, intimate, whispered warnings | `<|style:whispering|><|emotion:contemplation|><|prosody:expressiveness_high|>` |

---

## 6. Dynamic Emotional Escalation System

To ensure dialogue never repeats and builds natural tension, `HeuristicAgent.team_discussion()` implements a state-aware emotional escalation machine:

1. **Quest 1 (Scouting Phase):**
   - Controlled, confident proposals; cautious questions; Merlin whispers quietly.
2. **Post-Sabotage (When any quest has failed):**
   - Loyal Servants react with **`<|style:shouting|><|emotion:anger|>`** directly confronting players who approved the failed lineup.
   - Evil agents fire back with indignant defensiveness: *"Stop yelling at me! I put my life on the line for Arthur while you sat back and manipulated everyone!"*
3. **Hammer Rounds (Round 4 or 5 of any quest):**
   - High-stakes urgency using **`<|emotion:fear|><|prosody:speed_fast|>`**: *"Wait! We are at round 4 and right at the hammer! If this team fails, evil wins the entire game!"*

---

## 7. Tool Calling Protocol for Boson Models

AvalonBot defines 5 formal JSON tools in `avalon/tools.py` compatible with both REST and Realtime WebSocket schemas:

1. `propose_team(team)`: Leader nominates players.
2. `vote_on_team(vote)`: Approve/Reject team.
3. `vote_on_quest(vote)`: Secret Pass/Fail quest vote.
4. `assassinate(target)`: Assassin selects suspected Merlin.
5. `update_belief(player_id, p_evil, rationale)`: Good players update their belief graph.

### WebSocket Realtime Protocol Handshake
When operating via `wss://api.boson.ai/v1/realtime/`:
1. Client mints an ephemeral secret via `POST /v1/realtime/client_secrets`.
2. Connects via WebSocket with subprotocol `["realtime", "bai-client-secret.<token>"]`.
3. Sends `session.update` with `higgs-stt-3.1` transcription and server VAD turn detection.
4. On model tool call: Receives `response.function_call_arguments.done`.
5. Client executes tool locally and emits `conversation.item.create` (`type: "function_call_output"`).
6. Client triggers exactly one `response.create` to resume speech.

---

## 8. Chronological Changelog & Milestones

- **Milestone 1:** Evaluated `Avalon-LLM` and designed the 5-player isolated architecture.
- **Milestone 2:** Initialized GitHub repo (`KhuzemahHQ/AvalonBot`), created `README.md`, `.gitignore`, `engine.py`, `belief_graph.py`, `runner.py`, and 8 passing unit tests.
- **Milestone 3:** Integrated Boson AI Higgs TTS 3 (`speech/boson_tts.py`) and Realtime client (`speech/boson_realtime.py`).
- **Milestone 4:** Resolved HTTP 400 voice registry errors; built offline PCM synthesizer fallback.
- **Milestone 5:** Discovered Boson Higgs control token vocabulary; introduced `<|prosody:expressiveness_high|>`, whispering, shouting, and laughter SFX.
- **Milestone 6:** Implemented dynamic emotional escalation across game rounds and created this comprehensive technical log.

---

## 9. Running and Testing

```bash
# 1. Run all unit tests
python -m pytest tests/

# 2. Run self-play simulation with live audio playback on speakers
python simulate.py

# 3. Run self-play simulation in headless mute mode
python simulate.py --mute
```
