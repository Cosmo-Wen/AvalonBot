"""
tests/test_intent_compiler.py - Test suite for SpeechIntentCompiler and BeliefProsodyCoupler
"""
import pytest
from speech.intent_compiler import SpeechIntentCompiler, DeliveryIntent
from speech.belief_prosody_coupler import BeliefProsodyCoupler


def test_compile_valid_emotion_and_prosody():
    intent = DeliveryIntent(emotion="anger", prosody="expressive_high")
    compiled = SpeechIntentCompiler.compile_utterance("I am loyal!", intent)
    assert compiled == "<|emotion:anger|><|prosody:expressive_high|>I am loyal!"


def test_compile_legacy_tag_sanitization():
    intent = DeliveryIntent(prosody="expressiveness_high")
    compiled = SpeechIntentCompiler.compile_utterance("Check the records.", intent)
    assert compiled == "<|prosody:expressive_high|>Check the records."


def test_compile_synonym_fallback():
    # 'suspicious' is invalid in Boson taxonomy, should fallback to 'contemplation'
    intent = DeliveryIntent(emotion="suspicious")
    compiled = SpeechIntentCompiler.compile_utterance("Something is off.", intent)
    assert compiled == "<|emotion:contemplation|>Something is off."

    # 'indignation' should fallback to 'anger'
    intent2 = DeliveryIntent(emotion="indignation")
    compiled2 = SpeechIntentCompiler.compile_utterance("How dare you!", intent2)
    assert compiled2 == "<|emotion:anger|>How dare you!"


def test_compile_sfx_onomatopoeia_pairing():
    intent = DeliveryIntent(sfx="sigh", emotion="contemplation")
    compiled = SpeechIntentCompiler.compile_utterance("I do not know who to trust.", intent)
    assert compiled == "<|emotion:contemplation|><|sfx:sigh|>Uh, I do not know who to trust."

    intent_laughter = DeliveryIntent(sfx="laughter", emotion="elation")
    compiled_l = SpeechIntentCompiler.compile_utterance("We won the quest!", intent_laughter)
    assert compiled_l == "<|emotion:elation|><|sfx:laughter|>Haha! We won the quest!"


def test_compile_strips_hallucinated_inline_tokens_from_body():
    intent = DeliveryIntent(emotion="anger")
    raw_text = "I am <|emotion:suspicious|> telling the truth <|prosody:fast|> here."
    compiled = SpeechIntentCompiler.compile_utterance(raw_text, intent)
    assert compiled == "<|emotion:anger|>I am  telling the truth  here."


def test_belief_entropy_calculation():
    # Maximum uncertainty (all probabilities 0.5)
    max_uncertainty = [0.5, 0.5, 0.5, 0.5]
    entropy_max = BeliefProsodyCoupler.calculate_entropy(max_uncertainty)
    assert pytest.approx(entropy_max, 0.01) == 1.0

    # High certainty (probabilities near 0 or 1)
    high_certainty = [0.95, 0.05, 0.05, 0.95]
    entropy_low = BeliefProsodyCoupler.calculate_entropy(high_certainty)
    assert entropy_low < 0.35


def test_epistemic_prosody_mapping():
    # Hammer round (Round 4 / Proposal 5)
    intent_hammer = BeliefProsodyCoupler.map_epistemic_state(
        belief_distribution={1: 0.5, 2: 0.5, 3: 0.5, 4: 0.5},
        agent_role="Loyal Servant",
        proposal_round=4
    )
    assert intent_hammer.emotion == "fear"
    assert intent_hammer.prosody == "expressive_high"

    # Merlin cautious delivery
    intent_merlin = BeliefProsodyCoupler.map_epistemic_state(
        belief_distribution={1: 0.92, 2: 0.1, 3: 0.1, 4: 0.1},
        agent_role="Merlin",
        proposal_round=1
    )
    assert intent_merlin.emotion == "contemplation"
    assert intent_merlin.style == "whispering"

    # High certainty accusation
    intent_certain = BeliefProsodyCoupler.map_epistemic_state(
        belief_distribution={1: 0.95, 2: 0.05, 3: 0.05, 4: 0.05},
        agent_role="Loyal Servant",
        proposal_round=2
    )
    assert intent_certain.emotion == "anger"
    assert intent_certain.prosody == "expressive_high"
