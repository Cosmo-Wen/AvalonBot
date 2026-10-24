"""
Simulation runner demonstrating an end-to-end 5-player Avalon game with Boson TTS.

Usage:
  python simulate.py                    # Standard live game with Boson TTS
  python simulate.py --pipeline         # Low-latency pipelined synthesis (pre-synthesizes upcoming speakers)
  python simulate.py --mute             # Fast simulation without playing audio to speakers
  python simulate.py --human-seat 0     # Human takes seat 0 via microphone & Boson STT 3.1
"""

import sys
import asyncio
from avalon.engine import Role
from avalon.agents import HeuristicAgent
from avalon.runner import AvalonGameRunner
from speech.boson_tts import HiggsTTSClient
from speech.audio_pipeline import AudioPipeline
from speech.human_agent import HumanVoiceAgent
from speech.budget import global_budget_tracker


async def main():
    enable_playback = "--mute" not in sys.argv
    use_pipeline = "--pipeline" in sys.argv

    # Check for human participant seat
    human_seat = None
    if "--human-seat" in sys.argv:
        try:
            idx = sys.argv.index("--human-seat")
            human_seat = int(sys.argv[idx + 1])
        except (IndexError, ValueError):
            human_seat = 0

    print("=" * 60)
    print("AvalonBot Game Simulation with Boson AI Voice Pipeline")
    print("=" * 60)
    print(f"  Audio Playback:    {'ENABLED' if enable_playback else 'DISABLED (--mute)'}")
    print(f"  Pipelining Mode:   {'ACTIVE (--pipeline)' if use_pipeline else 'SEQUENTIAL'}")
    print(f"  Human Player Seat: {'None (all AI)' if human_seat is None else f'Player {human_seat} (Microphone + STT)'}")
    print(f"  Boson API Budget:  {global_budget_tracker.remaining_budget()} calls remaining (cap: {global_budget_tracker.max_calls})")
    print("=" * 60)

    # Initialize Boson Higgs TTS client
    tts_client = HiggsTTSClient(play_audio=enable_playback)
    pipeline = AudioPipeline(tts_client=tts_client) if use_pipeline else None

    # Setup 5 agents (3 Good with belief graphs, 2 Evil)
    agents = {}
    for i in range(5):
        if human_seat is not None and i == human_seat:
            agents[i] = HumanVoiceAgent(
                player_id=i,
                role=Role.LOYAL_SERVANT,
                use_mic=True,
            )
        else:
            agents[i] = HeuristicAgent(
                player_id=i,
                role=Role.LOYAL_SERVANT,
                condition="belief_graph",
                seed=100 + i,
                merlin_graph=True,  # Live demo: evil keeps P(Merlin)
            )

    runner = AvalonGameRunner(
        agents=agents,
        seed=42,
        tts_client=tts_client,
        audio_pipeline=pipeline,
        verbose=True,
    )
    metrics = await runner.run_game()

    print("\n" + "=" * 50)
    print("Game Result Summary")
    print("=" * 50)
    print(f"Good Victory: {metrics.good_victory}")
    print(f"Win Reason: {metrics.win_reason}")
    print(f"Total Quests Played: {metrics.total_turns}")
    print(f"Merlin Id: {metrics.merlin_id}, Assassin Id: {metrics.assassin_id}")
    print(f"Merlin Survived: {metrics.merlin_survived}")
    if metrics.assassin_p_merlin:
        print(f"Assassin's P(Merlin) before the guess: {metrics.assassin_p_merlin}")
    print(f"Good Players Spy-ID Accuracies: {metrics.good_spy_id_accuracies}")
    print(f"Good Players Brier Scores: {metrics.good_brier_scores}")
    print(f"\nAll synthesized voice lines saved to: {tts_client.cache_dir}/")

    budget_stats = global_budget_tracker.get_summary()
    print(f"Boson API Calls Used: {budget_stats['total_calls']} / {budget_stats['max_calls']} (Remaining: {budget_stats['remaining']})")


if __name__ == "__main__":
    asyncio.run(main())
