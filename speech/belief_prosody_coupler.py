"""
speech/belief_prosody_coupler.py - Epistemic Belief to Boson Prosody Coupler

Translates real-time continuous belief probabilities P(Evil_j) and Shannon entropy
into acoustic delivery intent vectors for Boson Higgs TTS 3.
"""
import math
from typing import Dict, List, Optional
from speech.intent_compiler import DeliveryIntent


class BeliefProsodyCoupler:
    """Translates epistemic probabilities into Boson Higgs acoustic intent vectors."""

    @staticmethod
    def calculate_entropy(probabilities: List[float]) -> float:
        """
        Calculates normalized Shannon entropy over independent binary hypotheses.
        Returns value in [0.0, 1.0], where 1.0 represents maximal uncertainty.
        """
        if not probabilities:
            return 1.0
        total_entropy = 0.0
        for p in probabilities:
            p_clamped = max(0.001, min(0.999, p))
            q = 1.0 - p_clamped
            h = -(p_clamped * math.log2(p_clamped) + q * math.log2(q))
            total_entropy += h
        max_entropy = len(probabilities) * 1.0  # max 1 bit per player
        return total_entropy / max_entropy

    @classmethod
    def map_epistemic_state(
        cls,
        belief_distribution: Optional[Dict[int, float]] = None,
        agent_role: str = "Loyal Servant",
        proposal_round: int = 0,
        quest_results: Optional[List[bool]] = None
    ) -> DeliveryIntent:
        """
        Maps game state and belief entropy to a DeliveryIntent.
        """
        intent = DeliveryIntent()
        probs = list(belief_distribution.values()) if belief_distribution else []
        entropy = cls.calculate_entropy(probs) if probs else 1.0
        max_suspicion = max(probs) if probs else 0.5

        # 1. Round 4 (Hammer) override: highest tension
        if proposal_round >= 4:
            intent.emotion = "fear" if agent_role in ["Merlin", "Loyal Servant"] else "determination"
            intent.prosody = "expressive_high"
            return intent

        # 2. Merlin cautious guidance: deliberate calm under cover
        if agent_role == "Merlin":
            if max_suspicion > 0.80:
                intent.emotion = "contemplation"
                intent.prosody = "speed_slow"
                intent.style = "whispering"
                return intent

        # 3. High Certainty: direct fast assertion
        if max_suspicion > 0.80 and entropy < 0.40:
            intent.emotion = "anger"
            intent.prosody = "expressive_high"
            return intent

        # 4. High Uncertainty: slow contemplative delivery with sighs
        if entropy > 0.75:
            intent.emotion = "confusion"
            intent.prosody = "speed_slow"
            intent.sfx = "sigh"
            return intent

        # Default poised baseline
        intent.emotion = "contemplation"
        intent.prosody = "expressive_low"
        return intent
