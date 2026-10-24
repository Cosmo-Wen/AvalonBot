"""
speech/intent_compiler.py - Dual-Layer Semantic Intent to Boson Token Compiler

Ensures that LLM reasoning agents or emotion heuristics compile strictly to
valid Boson Higgs TTS 3 control tokens without syntax leaks or unparsed tags.
"""
from typing import Dict, List, Optional, Set
from dataclasses import dataclass
import re

VALID_EMOTIONS: Set[str] = {
    "elation", "amusement", "enthusiasm", "determination", "pride",
    "contentment", "affection", "relief", "contemplation", "confusion",
    "surprise", "awe", "longing", "arousal", "anger", "fear",
    "disgust", "bitterness", "sadness", "shame", "helplessness"
}

VALID_PROSODY: Set[str] = {
    "expressive_high", "expressive_low", "speed_very_slow", "speed_slow",
    "speed_fast", "speed_very_fast", "pitch_low", "pitch_high",
    "pause", "long_pause"
}

VALID_STYLES: Set[str] = {"whispering", "shouting", "singing"}

SYNONYM_FALLBACK_MAP: Dict[str, str] = {
    "indignation": "anger",
    "suspicious": "contemplation",
    "confident": "pride",
    "defensive": "fear",
    "skeptical": "contemplation",
    "alarmed": "fear",
    "furious": "anger",
    "hesitant": "confusion",
    "triumphant": "elation"
}

SFX_ONOMATOPOEIA: Dict[str, str] = {
    "laughter": "Haha! ",
    "sigh": "Uh, ",
    "cough": "*cough* ",
    "crying": "Sob, ",
    "screaming": "Ahhh! ",
    "humming": "Hmm, ",
    "sniff": "Sniff, ",
    "sneeze": "Achoo! "
}


@dataclass
class DeliveryIntent:
    emotion: Optional[str] = None
    prosody: Optional[str] = None
    style: Optional[str] = None
    sfx: Optional[str] = None


class SpeechIntentCompiler:
    """Clamps semantic intents and compiles strictly compliant Boson Higgs tag strings."""

    @staticmethod
    def compile_utterance(text: str, intent: Optional[DeliveryIntent] = None) -> str:
        if intent is None:
            intent = DeliveryIntent()

        tags: List[str] = []

        # 1. Resolve and clamp Emotion
        if intent.emotion:
            norm_emotion = intent.emotion.strip().lower()
            if norm_emotion in VALID_EMOTIONS:
                tags.append(f"<|emotion:{norm_emotion}|>")
            elif norm_emotion in SYNONYM_FALLBACK_MAP:
                tags.append(f"<|emotion:{SYNONYM_FALLBACK_MAP[norm_emotion]}|>")
            else:
                tags.append("<|emotion:contemplation|>")

        # 2. Resolve and clamp Prosody
        if intent.prosody:
            norm_prosody = intent.prosody.strip().lower()
            # Normalize legacy token
            if norm_prosody == "expressiveness_high":
                norm_prosody = "expressive_high"
            if norm_prosody in VALID_PROSODY:
                tags.append(f"<|prosody:{norm_prosody}|>")

        # 3. Resolve Style
        if intent.style and intent.style.strip().lower() in VALID_STYLES:
            tags.append(f"<|style:{intent.style.strip().lower()}|>")

        # 4. Resolve Sound Effects with required lexical cues
        prefix_sfx = ""
        if intent.sfx and intent.sfx.strip().lower() in SFX_ONOMATOPOEIA:
            sfx_tag = intent.sfx.strip().lower()
            cue = SFX_ONOMATOPOEIA[sfx_tag]
            prefix_sfx = f"<|sfx:{sfx_tag}|>{cue}"

        # Clean any raw unescaped tokens that the LLM may have hallucinated in body text
        cleaned_text = re.sub(r"<\|(?:emotion|prosody|style|sfx):[^|>]+?\|>", "", text).strip()

        return "".join(tags) + prefix_sfx + cleaned_text
