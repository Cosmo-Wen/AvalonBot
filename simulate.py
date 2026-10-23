"""
Quick simulation runner demonstrating an end-to-end 5-player Avalon game.
"""

import asyncio
from avalon.engine import Role
from avalon.agents import HeuristicAgent
from avalon.runner import AvalonGameRunner


async def main():
    # Setup 5 heuristic agents (3 Good with belief graphs, 2 Evil)
    agents = {}
    for i in range(5):
        # We assign placeholder roles that get re-bound by the runner
        agents[i] = HeuristicAgent(
            player_id=i,
            role=Role.LOYAL_SERVANT,
            condition="belief_graph",
            seed=100 + i,
        )

    runner = AvalonGameRunner(agents=agents, seed=42, verbose=True)
    metrics = await runner.run_game()

    print("\n--- Game Result Summary ---")
    print(f"Good Victory: {metrics.good_victory}")
    print(f"Win Reason: {metrics.win_reason}")
    print(f"Total Quests Played: {metrics.total_turns}")
    print(f"Merlin Id: {metrics.merlin_id}, Assassin Id: {metrics.assassin_id}")
    print(f"Merlin Survived: {metrics.merlin_survived}")
    print(f"Good Players Spy-ID Accuracies: {metrics.good_spy_id_accuracies}")
    print(f"Good Players Brier Scores: {metrics.good_brier_scores}")


if __name__ == "__main__":
    asyncio.run(main())
