"""Metrics kept separate from the historical A/B/C experiment."""
from .engine import ROLE_SIDES


def vote_accuracy_metrics(engine):
    records = [r for r in engine.vote_history if r.round_num < 4]
    good = engine.get_good_players()
    if not records:
        return {"vote_accuracy": {}, "merlin_vote_accuracy_rank": None, "vote_count": 0}
    accuracy = {p: sum(bool(r.votes[p]) == all(ROLE_SIDES[engine.player_roles[q]] for q in r.team)
                       for r in records) / len(records) for p in good}
    value = accuracy[engine.get_merlin()]
    rank = 1 + sum(v > value for v in accuracy.values()) + (sum(v == value for v in accuracy.values()) - 1) / 2
    return {"vote_accuracy": accuracy, "merlin_vote_accuracy_rank": rank, "vote_count": len(records)}


def summarize_percival(ends):
    groups = {}
    for condition in sorted({e["percival_condition"] for e in ends}):
        rows = [e for e in ends if e["percival_condition"] == condition]
        assassinations = [e for e in rows if e["percival_metrics"]["assassination_reached"]]
        ranks = [e["percival_metrics"]["merlin_vote_accuracy_rank"] for e in rows
                 if e["percival_metrics"]["merlin_vote_accuracy_rank"] is not None]
        probabilities = [e["percival_metrics"]["p_true_merlin"] for e in rows
                         if e["percival_metrics"]["p_true_merlin"] is not None]
        quests = [v for e in rows for v in e["quest_results"]]
        groups[condition] = {
            "games": len(rows), "good_wins": sum(e["winner"] == "good" for e in rows),
            "good_win_rate": sum(e["winner"] == "good" for e in rows) / len(rows),
            "assassinations": len(assassinations),
            "assassin_hits": sum(e["percival_metrics"]["assassin_hit"] for e in assassinations),
            "assassin_accuracy": (sum(e["percival_metrics"]["assassin_hit"] for e in assassinations) / len(assassinations)
                                   if assassinations else None),
            "merlin_mean_vote_accuracy_rank": sum(ranks) / len(ranks) if ranks else None,
            "merlin_rank_games": len(ranks),
            "merlin_vote_rank_counts": {str(rank): ranks.count(rank) for rank in sorted(set(ranks))},
            "mean_p_true_merlin": sum(probabilities) / len(probabilities) if probabilities else None,
            "belief_games": len(probabilities), "quests": len(quests), "quests_passed": sum(quests),
            "quest_success_rate": sum(quests) / len(quests) if quests else None}
    return groups
