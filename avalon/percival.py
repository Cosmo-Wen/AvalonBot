"""Percival's fixed, pre-registered four-world inference model."""
import itertools
import math
from dataclasses import dataclass

MERLIN_EVIL_FACTOR = 0.2
MERLIN_MORGANA_FACTOR = 0.1
MORGANA_REJECT_FACTOR = 0.5
TEAM_APPROVAL_THRESHOLD = 0.55
FOLLOW_THRESHOLD = 0.8
TIE_TOLERANCE = 1e-9


@dataclass(frozen=True)
class World:
    merlin: int
    morgana: int
    assassin: int
    servant: int

    @property
    def evil(self):
        return {self.morgana, self.assassin}


class PercivalBelief:
    def __init__(self, owner, candidates, num_players=5):
        self.owner = owner
        self.num_players = num_players
        candidates = tuple(sorted(candidates))
        if num_players != 5 or len(set(candidates)) != 2 or owner in candidates or any(c not in range(5) for c in candidates):
            raise ValueError("Percival requires two distinct other-player candidates")
        others = sorted(set(range(num_players)) - set(candidates) - {owner})
        self.worlds = [World(m, g, a, s) for m, g in (candidates, candidates[::-1])
                       for a, s in (others, others[::-1])]
        self.log_weights = [0.0] * 4
        self.seen = set()

    @property
    def weights(self):
        peak = max(self.log_weights)
        raw = [max(math.exp(v - peak), 1e-300) if math.isfinite(v) else 0.0 for v in self.log_weights]
        total = sum(raw)
        return [v / total for v in raw]

    @property
    def p_merlin(self):
        return {p: sum(w for world, w in zip(self.worlds, self.weights) if world.merlin == p)
                for p in sorted({w.merlin for w in self.worlds})}

    @property
    def p_evil(self):
        return {p: sum(w for world, w in zip(self.worlds, self.weights) if p in world.evil)
                for p in range(5) if p != self.owner}

    def all_good(self, team):
        return sum(w for world, w in zip(self.worlds, self.weights) if not world.evil.intersection(team))

    def best_all_good(self, team_size):
        r"""The highest all-good probability any team of this size could have."""
        return max(self.all_good(team) for team in itertools.combinations(range(self.num_players), team_size))

    def best_team(self, team_size):
        r"""Percival's proposal: the team most likely all good. Ties go to teams with Percival on them,
        then to the lower summed P(evil), then to the lowest seats."""
        p_evil = self.p_evil
        return list(min(itertools.combinations(range(self.num_players), team_size),
                        key=lambda team: (-round(self.all_good(team), 12), self.owner not in team,
                                          round(sum(p_evil.get(p, 0.0) for p in team), 12), team)))

    def approves(self, team, leader):
        r"""Team vote, kept consistent with what Percival would propose itself.

        Percival approves its own proposal (`best_team`), and any team at least as likely all good as the
        best team of that size. Otherwise the fixed cutoff applies. Without the first two rules Percival rejected its
        own clean opening team at 50% and the best available trio at 48.9% (P1 seed 0).
        """
        if leader == self.owner:
            return True
        probability = self.all_good(team)
        return probability > TEAM_APPROVAL_THRESHOLD or probability >= self.best_all_good(len(team)) - TIE_TOLERANCE

    def following(self):
        return next((p for p, prob in self.p_merlin.items() if prob > FOLLOW_THRESHOLD), None)

    def update(self, entry):
        if entry.seq in self.seen:
            raise ValueError(f"Duplicate Percival evidence #{entry.seq}")
        updated = list(self.log_weights)
        for i, world in enumerate(self.worlds):
            factor = 1.0
            if entry.kind == "quest_result" and not entry.success:
                if len(world.evil.intersection(entry.members)) < entry.fails:
                    updated[i] = -math.inf
            elif entry.kind == "proposal" or (entry.kind == "team_vote" and entry.attempt < 5):
                votes = dict(entry.votes)
                merlin_supports = (entry.leader == world.merlin if entry.kind == "proposal" else votes.get(world.merlin) is True)
                if merlin_supports:
                    if world.morgana in entry.members:
                        factor *= MERLIN_MORGANA_FACTOR
                    elif world.evil.intersection(entry.members):
                        factor *= MERLIN_EVIL_FACTOR
                if entry.kind == "team_vote" and votes.get(world.morgana) is False and world.assassin in entry.members:
                    factor *= MORGANA_REJECT_FACTOR
            updated[i] += math.log(factor)
        if not any(math.isfinite(v) for v in updated):
            raise ValueError("Quest evidence contradicts all Percival worlds")
        peak = max(updated)
        self.log_weights = [v - peak for v in updated]
        self.seen.add(entry.seq)

    def snapshot(self):
        return {"worlds": [{**vars(world), "weight": weight} for world, weight in zip(self.worlds, self.weights)],
                "p_merlin": self.p_merlin, "p_evil": self.p_evil, "following": self.following()}

    def render(self):
        import json
        best = {size: self.best_team(size) for size in (2, 3)}
        favoured = "; ".join(f"{size} players: {team} (P(all good)={self.all_good(team):.2f})" for size, team in best.items())
        return ("Your private four-world belief table:\n" + json.dumps(self.snapshot())
                + f"\nThe teams you would propose and approve: {favoured}")
