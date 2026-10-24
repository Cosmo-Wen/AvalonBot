"""
Simulation runner demonstrating an end-to-end 5-player Avalon game with Boson TTS.

Usage:
  python simulate.py             # Runs simulation with TTS synthesis & audio caching
  python simulate.py --mute      # Runs simulation without audio playback
"""

import sys
import asyncio
from avalon.engine import Role
from avalon.agents import HeuristicAgent
from avalon.runner import AvalonGameRunner
from speech.boson_tts import HiggsTTSClient


async def main():
    enable_playback = "--mute" not in sys.argv
    print(f"[Simulate] Audio playback on speakers: {'ENABLED' if enable_playback else 'DISABLED'}")

    # Initialize Boson Higgs TTS client
    tts_client = HiggsTTSClient(play_audio=enable_playback)

    # Setup 5 agents (3 Good with belief graphs, 2 Evil)
    agents = {}
    for i in range(5):
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


if __name__ == "__main__":
    asyncio.run(main())
