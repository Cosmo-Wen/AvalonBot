"""
Human Participant Voice & Keyboard Agent for Avalon.

Allows a human player to sit in any Avalon seat (e.g. Player 0 or Player 1)
and participate via:
1. Live Microphone capture via sounddevice + Boson AI Higgs STT 3.1 (/v1/audio/transcriptions).
2. Natural language entity & intent extraction for proposals, votes, quest cards, and assassination.
3. Interactive keyboard console fallback when mic is unavailable, silent, or offline.
"""

import os
import io
import re
import wave
import struct
import asyncio
from typing import Dict, List, Optional, Set, Any
from pathlib import Path
import aiohttp
from dotenv import load_dotenv

from avalon.engine import Role, ROLE_NAMES
from avalon.agents import Agent
from speech.budget import global_budget_tracker

load_dotenv()

try:
    import sounddevice as sd
    HAS_SOUNDDEVICE = True
except Exception:
    HAS_SOUNDDEVICE = False


# Word to number mapping for spoken player numbers
WORD_TO_DIGIT: Dict[str, int] = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4,
    "0": 0, "1": 1, "2": 2, "3": 3, "4": 4,
}

# Default character names assigned to Avalon seats
DEFAULT_SEAT_NAMES: Dict[str, int] = {
    "marcus": 0,
    "eleanor": 1,
    "jake": 2,
    "oliver": 3,
    "chloe": 4,
    "merlin": 4,
}


def parse_spoken_team_proposal(
    transcript: str,
    team_size: int,
    num_players: int = 5,
    human_id: int = -1,
    name_to_id: Optional[Dict[str, int]] = None,
) -> Optional[List[int]]:
    """
    Extracts an ordered list of unique player IDs from natural language speech or typed text.

    Supports:
    - Direct digits: "0", "1", "2", "3", "4"
    - Word numbers: "zero", "one", "two", "three", "four"
    - "Player X", "Seat X", "P0", "P1"
    - Character names: "Eleanor", "Marcus", "Jake", "Oliver", "Chloe"
    - Self-reference: "myself", "me" (resolves to human_id)
    - Exclusions: "not player 0", "without 2", "exclude 3"
    - Conjunctions: "and", "plus", "with", commas

    Returns:
        List of exactly `team_size` player IDs, or None if ambiguous/invalid.
    """
    if not transcript or not transcript.strip():
        return None

    names = dict(DEFAULT_SEAT_NAMES)
    if name_to_id:
        names.update({k.lower(): v for k, v in name_to_id.items()})

    text = transcript.lower().strip().replace("'", "").replace("’", "")

    # 1. Identify excluded player IDs (e.g. "not player 0", "without player 2", "exclude 3")
    excluded: Set[int] = set()
    exclusion_patterns = [
        r"\b(?:not|without|exclude|excluding|don't pick|dont pick|never)\s+(?:player\s+|seat\s+|p)?(\d|zero|one|two|three|four|[a-z]+)\b",
    ]
    for pat in exclusion_patterns:
        for match in re.finditer(pat, text):
            target_str = match.group(1).lower()
            if target_str in WORD_TO_DIGIT:
                excluded.add(WORD_TO_DIGIT[target_str])
            elif target_str in names:
                excluded.add(names[target_str])
            elif target_str in ("myself", "me") and human_id >= 0:
                excluded.add(human_id)

    # 2. Tokenize and scan text from left to right to find mentions in order
    clean_text = re.sub(r"[^\w\s]", " ", text)
    tokens = clean_text.split()

    candidates: List[int] = []

    def add_candidate(pid: int):
        if 0 <= pid < num_players and pid not in excluded and pid not in candidates:
            candidates.append(pid)

    i = 0
    while i < len(tokens):
        tok = tokens[i]
        # Check "player X" or "seat X"
        if tok in ("player", "seat") and i + 1 < len(tokens):
            nxt = tokens[i + 1]
            if nxt in WORD_TO_DIGIT:
                add_candidate(WORD_TO_DIGIT[nxt])
                i += 2
                continue
            elif nxt in names:
                add_candidate(names[nxt])
                i += 2
                continue
        # Check "p0", "p1", "p2", etc.
        m_p = re.match(r"^p([0-4])$", tok)
        if m_p:
            add_candidate(int(m_p.group(1)))
            i += 1
            continue
        # Check self-reference: "myself", "me"
        if tok in ("myself", "me") and human_id >= 0:
            add_candidate(human_id)
            i += 1
            continue
        # Check character name
        if tok in names:
            add_candidate(names[tok])
            i += 1
            continue
        # Check digits or word numbers
        if tok in WORD_TO_DIGIT:
            # Avoid false positives like "one of" or "one moment"
            if tok == "one" and i + 1 < len(tokens) and tokens[i + 1] in ("of", "second", "moment"):
                i += 1
                continue
            add_candidate(WORD_TO_DIGIT[tok])
            i += 1
            continue

        i += 1

    if len(candidates) == team_size:
        return candidates

    return None


def parse_spoken_vote(transcript: str) -> Optional[bool]:
    """
    Parses an affirmative (Approve / True) or negative (Reject / False) vote
    from a spoken transcript or typed text.

    Supports:
    - Direct affirmative: "approve", "yes", "yeah", "yep", "aye", "agree", "support", "y", "1"
    - Direct negative: "reject", "no", "nope", "nah", "nay", "disagree", "oppose", "n", "0"
    - Negated approval: "don't approve", "cannot support", "do not agree" -> False
    - Negated rejection: "don't reject", "do not oppose" -> True

    Returns:
        True for Approve / Yes
        False for Reject / No
        None if ambiguous or unrecognized
    """
    if not transcript or not transcript.strip():
        return None

    text = transcript.lower().strip().replace("'", "").replace("’", "")
    clean = re.sub(r"[^\w\s]", " ", text)
    words = clean.split()

    direct_pos = {"y", "yes", "yeah", "yep", "aye", "approve", "approved", "approval", "true", "1", "sure", "agreed"}
    direct_neg = {"n", "no", "nope", "nah", "nay", "reject", "rejected", "rejection", "false", "0", "disagree", "oppose"}

    if len(words) == 1:
        if words[0] in direct_pos:
            return True
        if words[0] in direct_neg:
            return False

    # Check negated approval (e.g. "don't approve", "do not approve", "cannot support")
    negated_pos = re.search(
        r"\b(?:not|dont|do not|cannot|cant|wont|refuse to|never)\s+(?:to\s+)?(?:approve|support|agree|accept|trust|vote yes)\b",
        clean,
    )
    if negated_pos:
        return False

    # Check negated rejection (e.g. "don't reject", "do not reject")
    negated_neg = re.search(
        r"\b(?:not|dont|do not|cannot|cant)\s+(?:to\s+)?(?:reject|oppose|vote no)\b",
        clean,
    )
    if negated_neg:
        return True

    pos_patterns = [
        r"\b(?:approve|approved|approving|approval)\b",
        r"\b(?:support|supporting)\b",
        r"\b(?:agree|agreed|agreeing)\b",
        r"\b(?:aye|yep|yeah)\b",
        r"\b(?:vote\s+yes|say\s+yes|is\s+a\s+yes|thumbs\s+up|lets\s+do\s+it|looks\s+good|trust\s+this\s+team)\b",
    ]
    neg_patterns = [
        r"\b(?:reject|rejected|rejecting|rejection)\b",
        r"\b(?:oppose|opposing)\b",
        r"\b(?:disagree|disagreeing)\b",
        r"\b(?:nay|nope|nah)\b",
        r"\b(?:vote\s+no|say\s+no|is\s+a\s+no|thumbs\s+down|distrust|untrustworthy|bad\s+team)\b",
    ]

    has_pos = any(re.search(p, clean) for p in pos_patterns) or ("yes" in words)
    has_neg = any(re.search(p, clean) for p in neg_patterns) or ("no" in words)

    if has_pos and not has_neg:
        return True
    if has_neg and not has_pos:
        return False

    return None


def parse_spoken_quest_vote(transcript: str) -> Optional[bool]:
    """
    Parses a secret quest vote: Pass (True) or Fail (False).

    Supports:
    - Pass: "pass", "success", "succeed", "support", "clean", "yes", "p"
    - Fail: "fail", "failure", "sabotage", "betray", "betrayal", "poison", "strike", "no", "f"
    - Negations: "don't fail" -> True, "don't pass" -> False
    """
    if not transcript or not transcript.strip():
        return None

    text = transcript.lower().strip().replace("'", "").replace("’", "")
    clean = re.sub(r"[^\w\s]", " ", text)
    words = clean.split()

    direct_pass = {"p", "pass", "passed", "success", "succeed", "true", "1", "yes"}
    direct_fail = {"f", "fail", "failed", "failure", "sabotage", "betray", "false", "0", "no"}

    if len(words) == 1:
        if words[0] in direct_pass:
            return True
        if words[0] in direct_fail:
            return False

    if re.search(r"\b(?:dont|not|do not|wont)\s+(?:fail|sabotage|betray)\b", clean):
        return True

    if re.search(r"\b(?:dont|not|do not|wont)\s+(?:pass|succeed)\b", clean):
        return False

    has_fail = bool(re.search(r"\b(?:fail|failure|sabotage|betray|betrayal|poison|strike)\b", clean)) or ("no" in words)
    has_pass = bool(re.search(r"\b(?:pass|passing|succeed|success|clean|support)\b", clean)) or ("yes" in words)

    if has_pass and not has_fail:
        return True
    if has_fail and not has_pass:
        return False

    return None


def parse_spoken_assassination_target(
    transcript: str,
    num_players: int = 5,
    assassin_id: int = -1,
    name_to_id: Optional[Dict[str, int]] = None,
) -> Optional[int]:
    """
    Parses the targeted player ID for assassination.
    Excludes the assassin themselves.
    """
    if not transcript or not transcript.strip():
        return None

    names = dict(DEFAULT_SEAT_NAMES)
    if name_to_id:
        names.update({k.lower(): v for k, v in name_to_id.items()})

    text = transcript.lower().strip()
    clean = re.sub(r"[^\w\s]", " ", text)
    tokens = clean.split()

    targets: List[int] = []

    def add_target(pid: int):
        if 0 <= pid < num_players and pid != assassin_id and pid not in targets:
            targets.append(pid)

    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok in ("player", "seat") and i + 1 < len(tokens):
            nxt = tokens[i + 1]
            if nxt in WORD_TO_DIGIT:
                add_target(WORD_TO_DIGIT[nxt])
                i += 2
                continue
            elif nxt in names:
                add_target(names[nxt])
                i += 2
                continue
        m_p = re.match(r"^p([0-4])$", tok)
        if m_p:
            add_target(int(m_p.group(1)))
            i += 1
            continue
        # "merlin" is the role being targeted, not the seat ID itself
        if tok in names and tok != "merlin":
            add_target(names[tok])
            i += 1
            continue
        if tok in WORD_TO_DIGIT:
            if tok == "one" and i + 1 < len(tokens) and tokens[i + 1] in ("of", "second", "moment"):
                i += 1
                continue
            add_target(WORD_TO_DIGIT[tok])
            i += 1
            continue
        i += 1

    if len(targets) == 1:
        return targets[0]

    return None


async def transcribe_audio_file(
    wav_bytes: bytes,
    api_key: Optional[str] = None,
    model: str = "higgs-stt-3.1",
) -> str:
    """
    Transcribes PCM WAV audio bytes using Boson AI Higgs STT 3.1.
    """
    api_key = (api_key or os.getenv("BOSON_API_KEY", "")).strip()
    if not api_key:
        return ""

    if not global_budget_tracker.can_call():
        print("[STT Notice] Boson API budget cap reached.")
        return ""

    url = "https://api.boson.ai/v1/audio/transcriptions"
    headers = {"Authorization": f"Bearer {api_key}"}

    form_data = aiohttp.FormData()
    form_data.add_field("model", model)
    form_data.add_field(
        "file",
        wav_bytes,
        filename="speech.wav",
        content_type="audio/wav",
    )

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, data=form_data, headers=headers) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    transcript = data.get("text", "").strip()
                    global_budget_tracker.record_call(
                        endpoint=url,
                        voice="human_mic",
                        text_length=len(transcript),
                        status_code=resp.status,
                        byte_size=len(wav_bytes),
                        extra={"stt_model": model},
                    )
                    return transcript
                else:
                    err = await resp.text()
                    print(f"[STT Error] Boson STT HTTP {resp.status}: {err}")
    except Exception as e:
        print(f"[STT Error] STT request failed: {e}")

    return ""


def record_mic_clip(duration_sec: float = 4.0, sample_rate: int = 16000) -> Optional[bytes]:
    """
    Synchronously captures audio from default microphone using sounddevice.
    """
    if not HAS_SOUNDDEVICE:
        return None

    try:
        print(f"\n  🎤 [MIC ACTIVE] Listening for {duration_sec}s... Speak now!")
        recording = sd.rec(
            int(duration_sec * sample_rate),
            samplerate=sample_rate,
            channels=1,
            dtype="int16",
        )
        sd.wait()
        print("  ⏳ [MIC FINISHED] Processing speech...")

        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(sample_rate)
            w.writeframes(recording.tobytes())

        return buf.getvalue()
    except Exception as e:
        print(f"[Mic Recording Error] {e}")
        return None


class HumanVoiceAgent(Agent):
    """
    Human player agent allowing participation via microphone voice (Higgs STT 3.1)
    or interactive keyboard console input.
    """

    def __init__(
        self,
        player_id: int,
        role: Role = Role.LOYAL_SERVANT,
        use_mic: bool = True,
        mic_duration: float = 4.0,
        api_key: Optional[str] = None,
        name_to_id: Optional[Dict[str, int]] = None,
    ):
        super().__init__(player_id=player_id, role=role, condition="human")
        self.is_human = True
        self.use_mic = use_mic and HAS_SOUNDDEVICE
        self.mic_duration = mic_duration
        self.api_key = (api_key or os.getenv("BOSON_API_KEY", "")).strip()
        self.name_to_id = name_to_id or dict(DEFAULT_SEAT_NAMES)

    def set_private_info(self, info: Dict[str, Any]):
        super().set_private_info(info)
        role_name = ROLE_NAMES.get(self.role, str(self.role))
        side_desc = "Good (Loyal Servant of Arthur)" if self.side else "Evil (Minion of Mordred)"
        print("\n" + "=" * 60)
        print(f"  👑 [SECRET ROLE REVEAL] You are Player {self.player_id}: {role_name}")
        print(f"  Allegiance: {side_desc}")
        if "seen_players" in info and info["seen_players"]:
            print(f"  🔮 Merlin Sight: You know the evil players are: {info['seen_players']}")
        if "evil_players" in info and info["evil_players"]:
            fellow = [p for p in info["evil_players"] if p != self.player_id]
            print(f"  🗡️ Evil Coven: Your evil teammate(s): {fellow}")
        print("=" * 60 + "\n")

    async def _capture_and_transcribe(self, duration: Optional[float] = None) -> str:
        """Helper to record a mic clip in thread pool and transcribe via Boson STT."""
        if not (self.use_mic and self.api_key):
            return ""
        dur = duration or self.mic_duration
        loop = asyncio.get_running_loop()
        wav_bytes = await loop.run_in_executor(None, record_mic_clip, dur, 16000)
        if not wav_bytes:
            return ""
        transcript = await transcribe_audio_file(wav_bytes, api_key=self.api_key)
        return transcript.strip()

    async def team_discussion(self, turn: int, round_num: int, leader: int, team_size: int) -> str:
        role_name = ROLE_NAMES.get(self.role, "Human")
        print(f"\n[YOUR TURN TO SPEAK - Player {self.player_id} ({role_name})]")

        # 1. Voice attempt if mic enabled
        if self.use_mic and self.api_key:
            print(f"  🎤 Speak your discussion statement into your microphone ({self.mic_duration}s)...")
            transcript = await self._capture_and_transcribe(self.mic_duration)
            if transcript:
                print(f"  🗣️ [Transcribed via Boson STT]: \"{transcript}\"")
                return transcript
            print("  ⚠️ Voice unrecognized or empty. Falling back to keyboard input.")

        # 2. Interactive console fallback
        loop = asyncio.get_running_loop()
        utterance = await loop.run_in_executor(
            None,
            input,
            f"Enter your discussion statement as Player {self.player_id}: ",
        )
        return utterance.strip() or f"I am Loyal Player {self.player_id} and want a trusted team."

    async def propose_team(self, turn: int, team_size: int) -> List[int]:
        print("\n" + "=" * 55)
        print(f"  👑 [LEADER PROPOSAL - Player {self.player_id}]")
        print(f"  You are the Leader! Propose a team of {team_size} players for Quest {turn + 1}.")
        print("  Options: Player numbers (0-4), character names (Eleanor, Jake, etc.), or 'myself'.")
        print("=" * 55)

        # 1. Voice attempt if mic enabled
        if self.use_mic and self.api_key:
            print(f"  🎤 Speak your proposed team now ({self.mic_duration}s recording)...")
            transcript = await self._capture_and_transcribe(self.mic_duration)
            if transcript:
                print(f"  🗣️ [Transcribed via Boson STT]: \"{transcript}\"")
                parsed = parse_spoken_team_proposal(
                    transcript,
                    team_size=team_size,
                    num_players=self.num_players,
                    human_id=self.player_id,
                    name_to_id=self.name_to_id,
                )
                if parsed is not None:
                    print(f"  ✅ [Spoken Proposal Accepted]: Team {parsed}")
                    return parsed
                print(f"  ⚠️ Could not identify exactly {team_size} valid player IDs from speech.")
            else:
                print("  ⚠️ Voice unrecognized or empty.")

        # 2. Interactive keyboard console fallback
        loop = asyncio.get_running_loop()
        while True:
            text = await loop.run_in_executor(
                None,
                input,
                f"Enter {team_size} players (e.g. '0, 1' or 'Eleanor, Jake'): ",
            )
            parsed = parse_spoken_team_proposal(
                text,
                team_size=team_size,
                num_players=self.num_players,
                human_id=self.player_id,
                name_to_id=self.name_to_id,
            )
            if parsed is not None:
                print(f"  ✅ [Proposal Accepted]: Team {parsed}")
                return parsed
            print(f"  ❌ Invalid input. Please enter exactly {team_size} unique players between 0 and {self.num_players - 1}.")

    async def vote_on_team(self, turn: int, round_num: int, leader: int, team: List[int]) -> bool:
        team_str = ", ".join(f"Player {p}" for p in team)
        print("\n" + "-" * 55)
        print(f"  🗳️ [TEAM VOTE - Player {self.player_id}]")
        print(f"  Leader Player {leader} proposed: [{team_str}]")
        print(f"  Cast your vote: Approve (Yes) or Reject (No).")
        print("-" * 55)

        # 1. Voice attempt if mic enabled
        if self.use_mic and self.api_key:
            print("  🎤 Speak your vote now ('Approve' / 'Reject' / 'Yes' / 'No')...")
            transcript = await self._capture_and_transcribe(min(3.0, self.mic_duration))
            if transcript:
                print(f"  🗣️ [Transcribed via Boson STT]: \"{transcript}\"")
                parsed = parse_spoken_vote(transcript)
                if parsed is not None:
                    decision = "APPROVE (Yes)" if parsed else "REJECT (No)"
                    print(f"  ✅ [Spoken Vote Accepted]: {decision}")
                    return parsed
                print("  ⚠️ Vote not clearly recognized as Approve or Reject.")
            else:
                print("  ⚠️ Voice unrecognized or empty.")

        # 2. Interactive keyboard console fallback
        loop = asyncio.get_running_loop()
        while True:
            text = await loop.run_in_executor(
                None,
                input,
                "Enter vote: Approve (y) or Reject (n): ",
            )
            parsed = parse_spoken_vote(text)
            if parsed is not None:
                decision = "APPROVE (Yes)" if parsed else "REJECT (No)"
                print(f"  ✅ [Vote Accepted]: {decision}")
                return parsed
            print("  ❌ Please enter 'y' / 'approve' to Approve, or 'n' / 'reject' to Reject.")

    async def vote_on_quest(self, turn: int, team: List[int]) -> bool:
        print("\n" + "=" * 55)
        print(f"  ⚔️ [SECRET QUEST VOTE - Player {self.player_id}]")
        print(f"  You are on the quest team: {team}")
        print("=" * 55)

        # Good players cannot fail quests per official Avalon rules
        if self.side:
            role_name = ROLE_NAMES.get(self.role, "Loyal Servant")
            print(f"  🛡️ As a Good player ({role_name}), you MUST pass the quest.")
            print("  ✅ Automatically submitting: PASS (Success)")
            return True

        # Evil players can choose Pass or Fail
        # In Avalon, quest votes are strictly secret cards, so this is entered silently via keyboard
        print("  🗡️ As an Evil player, choose secretly: PASS (support quest) or FAIL (sabotage quest).")
        print("  🤫 [SECRET INPUT] Do not speak aloud. Enter your secret card choice below:")

        loop = asyncio.get_running_loop()
        while True:
            text = await loop.run_in_executor(
                None,
                input,
                "  Secret Quest Card - Pass (p) or Fail (f): ",
            )
            parsed = parse_spoken_quest_vote(text)
            if parsed is not None:
                choice = "PASS" if parsed else "FAIL (Sabotage)"
                print(f"  ✅ [Secret Card Recorded]: {choice}")
                return parsed
            print("  ❌ Please enter 'p' to Pass, or 'f' to Fail.")

    async def evil_discussion(self, turn: int) -> str:
        print(f"\n[EVIL SECRET DISCUSSION - Player {self.player_id}] Coordinate privately with your evil partner:")
        if self.use_mic and self.api_key:
            print(f"  🎤 Speak your private thoughts into mic ({self.mic_duration}s)...")
            transcript = await self._capture_and_transcribe(self.mic_duration)
            if transcript:
                print(f"  🗣️ [Transcribed via Boson STT]: \"{transcript}\"")
                return transcript

        loop = asyncio.get_running_loop()
        utterance = await loop.run_in_executor(
            None,
            input,
            "Enter private message to evil teammate: ",
        )
        return utterance.strip() or "I suspect Player 4 is Merlin based on the voting patterns."

    async def assassinate(self) -> int:
        print("\n" + "=" * 55)
        print(f"  🎯 [ASSASSINATION PHASE - Player {self.player_id}]")
        print("  Good won 3 quests! Identify Merlin to snatch victory for Evil!")
        print("=" * 55)

        # 1. Voice attempt if mic enabled
        if self.use_mic and self.api_key:
            print(f"  🎤 Speak your target now (e.g. 'I choose Player 2' or 'Eleanor')...")
            transcript = await self._capture_and_transcribe(self.mic_duration)
            if transcript:
                print(f"  🗣️ [Transcribed via Boson STT]: \"{transcript}\"")
                parsed = parse_spoken_assassination_target(
                    transcript,
                    num_players=self.num_players,
                    assassin_id=self.player_id,
                    name_to_id=self.name_to_id,
                )
                if parsed is not None:
                    print(f"  ✅ [Target Selected]: Player {parsed}")
                    return parsed
                print("  ⚠️ Target player not clearly recognized.")
            else:
                print("  ⚠️ Voice unrecognized or empty.")

        # 2. Interactive keyboard console fallback
        loop = asyncio.get_running_loop()
        while True:
            text = await loop.run_in_executor(
                None,
                input,
                f"Enter player ID to assassinate (0-{self.num_players - 1} or name): ",
            )
            parsed = parse_spoken_assassination_target(
                text,
                num_players=self.num_players,
                assassin_id=self.player_id,
                name_to_id=self.name_to_id,
            )
            if parsed is not None:
                print(f"  ✅ [Target Selected]: Player {parsed}")
                return parsed
            print(f"  ❌ Invalid player. Enter a player other than yourself (0 to {self.num_players - 1}).")
