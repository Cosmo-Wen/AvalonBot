"""
Dynamic Game-State Emotion & Delivery Mapper for Boson Higgs TTS.

Translates real-time Avalon game events, round pressure, quest history,
and player roles into expressive Boson Higgs control tokens:
- Emotions: anger, determination, enthusiasm, fear, amusement, contemplation,
            elation, pride, relief, confusion, surprise, disgust, bitterness
- Styles: whispering, shouting
- Prosody: expressive_high, speed_fast, speed_slow, speed_very_fast, pause
- SFX: laughter, sigh
"""

from typing import Dict, List, Optional, Tuple, Any
from avalon.engine import Role


class GameStateDelivery:
    """Encapsulates the vocal delivery tokens for a single utterance."""

    def __init__(
        self,
        emotion: str = "determination",
        style: Optional[str] = None,
        prosody: Optional[List[str]] = None,
        sfx: Optional[str] = None,
    ):
        self.emotion = emotion
        self.style = style
        self.prosody = prosody or ["expressive_high"]
        self.sfx = sfx

    def to_prefix_tags(self) -> str:
        """Generates the verified Higgs inline token string prefix."""
        tags = []
        if self.style:
            tags.append(f"<|style:{self.style}|>")
        if self.emotion:
            tags.append(f"<|emotion:{self.emotion}|>")
        if self.prosody:
            for p in self.prosody:
                token = "expressive_high" if p == "expressiveness_high" else p
                tags.append(f"<|prosody:{token}|>")
        if self.sfx:
            # Pair with onomatopoeia cue for Higgs acoustic model
            if self.sfx == "sigh":
                tags.append(f"<|sfx:{self.sfx}|>Uh, ")
            elif self.sfx == "laughter":
                tags.append(f"<|sfx:{self.sfx}|>Haha! ")
            else:
                tags.append(f"<|sfx:{self.sfx}|>")
        return "".join(tags)

    def format_utterance(self, text: str) -> str:
        """Prepends tags to utterance if not already present."""
        if text.startswith("<|"):
            return text
        prefix = self.to_prefix_tags()
        return f"{prefix}{text}"


class GameStateEmotionMapper:
    """
    Computes vocal emotion, style, and prosody from dynamic Avalon game states.
    """

    @staticmethod
    def get_delivery_for_utterance(
        seat: int,
        role: Optional[Role],
        turn: int,
        round_num: int,
        last_quest_result: Optional[Dict[str, Any]] = None,
        quest_results: Optional[List[bool]] = None,
        is_hammer_round: bool = False,
        recent_rejections: int = 0,
        is_accusing: bool = False,
    ) -> GameStateDelivery:
        """
        Determines vocal delivery tags based on game events and situational urgency.
        """
        quest_results = quest_results or []
        fails_count = quest_results.count(False)
        passes_count = quest_results.count(True)

        # 1. HAMMER ROUND (Round 4 / 5th proposal)
        # Extreme tension: if this team vote fails, Evil wins automatically!
        if is_hammer_round or round_num >= 4:
            if role == Role.MERLIN:
                return GameStateDelivery(
                    emotion="fear",
                    style="whispering",
                    prosody=["speed_fast", "expressive_high"],
                    sfx="sigh",
                )
            elif role in (Role.MINION, Role.ASSASSIN):
                # Evil is excited or confident
                return GameStateDelivery(
                    emotion="amusement",
                    style=None,
                    prosody=["speed_slow", "expressive_high"],
                )
            else:
                # Loyal Servants are desperate and shouting
                return GameStateDelivery(
                    emotion="fear",
                    style="shouting",
                    prosody=["speed_very_fast", "expressive_high"],
                )

        # 2. IMMEDIATE REACTION TO FAILED QUEST
        if last_quest_result and not last_quest_result.get("success", True):
            num_fails = last_quest_result.get("num_fails", 1)
            if role == Role.MERLIN:
                # Merlin knows who failed it, but must be cryptic
                return GameStateDelivery(
                    emotion="contemplation",
                    style="whispering",
                    prosody=["speed_slow", "expressive_high"],
                    sfx="sigh",
                )
            elif role in (Role.MINION, Role.ASSASSIN):
                # Evil feigns innocence or deflects with indignation/anger
                return GameStateDelivery(
                    emotion="anger",
                    style=None,
                    prosody=["speed_fast", "expressive_high"],
                )
            else:
                # Loyal servants are furious (more anger as requested!)
                if num_fails >= 2 or fails_count >= 2:
                    return GameStateDelivery(
                        emotion="anger",
                        style="shouting",
                        prosody=["speed_fast", "expressive_high"],
                    )
                else:
                    return GameStateDelivery(
                        emotion="anger",
                        style=None,
                        prosody=["speed_fast", "expressive_high"],
                    )

        # 3. IMMEDIATE REACTION TO SUCCESSFUL QUEST
        if last_quest_result and last_quest_result.get("success", False):
            if role == Role.MERLIN:
                return GameStateDelivery(
                    emotion="relief",
                    style="whispering",
                    prosody=["expressive_high"],
                )
            elif role in (Role.MINION, Role.ASSASSIN):
                # Evil is cautious or bitter inside
                return GameStateDelivery(
                    emotion="determination",
                    style=None,
                    prosody=["expressive_high"],
                )
            else:
                # Good is elated
                return GameStateDelivery(
                    emotion="elation" if passes_count >= 2 else "enthusiasm",
                    style=None,
                    prosody=["expressive_high"],
                )

        # 4. HIGH REJECTION STREAK (Round 2 or 3)
        if round_num >= 2:
            if role == Role.LOYAL_SERVANT:
                return GameStateDelivery(
                    emotion="anger" if round_num == 3 else "bitterness",
                    style=None,
                    prosody=["speed_fast", "expressive_high"],
                )
            elif role == Role.MERLIN:
                return GameStateDelivery(
                    emotion="contemplation",
                    style="whispering",
                    prosody=["expressive_high"],
                )

        # 5. ACCUSATION / DIRECT CHALLENGE
        if is_accusing:
            return GameStateDelivery(
                emotion="anger",
                style=None,
                prosody=["speed_fast", "expressive_high"],
            )

        # 6. BASE ROLE ARCHETYPES (When game is in normal steady state)
        if role == Role.MERLIN:
            return GameStateDelivery(
                emotion="contemplation",
                style="whispering",
                prosody=["expressive_high"],
            )
        elif role == Role.ASSASSIN:
            return GameStateDelivery(
                emotion="amusement",
                style=None,
                prosody=["speed_slow", "expressive_high"],
            )
        elif role == Role.MINION:
            return GameStateDelivery(
                emotion="determination",
                style=None,
                prosody=["expressive_high"],
            )
        elif seat == 2:  # Loyal Servant 2 - hot-tempered
            return GameStateDelivery(
                emotion="anger",
                style=None,
                prosody=["speed_fast", "expressive_high"],
            )
        else:  # Loyal Servant 1 - earnest defender
            return GameStateDelivery(
                emotion="enthusiasm",
                style=None,
                prosody=["expressive_high"],
            )

    @staticmethod
    def get_assassination_delivery() -> GameStateDelivery:
        """Triumphant / chilling delivery for the Assassin's final kill."""
        return GameStateDelivery(
            emotion="pride",
            style=None,
            prosody=["speed_slow", "expressive_high"],
        )
