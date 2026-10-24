"""
Human Participant Voice & Keyboard Agent for Avalon.

Allows a human player to sit in any Avalon seat (e.g. Player 0 or Player 1)
and participate via:
1. Live Microphone capture via sounddevice + Boson AI Higgs STT 3.1 (/v1/audio/transcriptions).
2. Interactive keyboard console fallback when mic is unavailable or offline.
"""

import os
import io
import wave
import struct
import asyncio
from typing import Dict, List, Optional, Any
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
        print(f"\n  [MIC ACTIVE] Speak now ({duration_sec}s recording)...")
        recording = sd.rec(
            int(duration_sec * sample_rate),
            samplerate=sample_rate,
            channels=1,
            dtype="int16",
        )
        sd.wait()
        print("  [MIC FINISHED] Processing speech...")

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
    or standard console input.
    """

    def __init__(
        self,
        player_id: int,
        role: Role = Role.LOYAL_SERVANT,
        use_mic: bool = True,
        mic_duration: float = 4.0,
        api_key: Optional[str] = None,
    ):
        super().__init__(player_id=player_id, role=role, condition="human")
        self.use_mic = use_mic and HAS_SOUNDDEVICE
        self.mic_duration = mic_duration
        self.api_key = api_key or os.getenv("BOSON_API_KEY", "")

    async def team_discussion(self, turn: int, round_num: int, leader: int, team_size: int) -> str:
        prompt_banner = f"\n[YOUR TURN - Player {self.player_id} ({ROLE_NAMES[self.role]})]"
        print(prompt_banner)

        # Try microphone voice input first if enabled
        if self.use_mic and self.api_key:
            loop = asyncio.get_running_loop()
            wav_bytes = await loop.run_in_executor(None, record_mic_clip, self.mic_duration, 16000)
            if wav_bytes:
                transcript = await transcribe_audio_file(wav_bytes, api_key=self.api_key)
                if transcript:
                    print(f"  [Transcribed via Boson STT]: \"{transcript}\"")
                    return transcript
                else:
                    print("  [Voice empty or unrecognized] Falling back to text prompt.")

        # Interactive console fallback
        loop = asyncio.get_running_loop()
        utterance = await loop.run_in_executor(
            None,
            input,
            f"Enter your discussion statement as Player {self.player_id}: ",
        )
        return utterance.strip() or f"I am Loyal Player {self.player_id} and want a trusted team."

    async def propose_team(self, turn: int, team_size: int) -> List[int]:
        print(f"\n[LEADER PROPOSAL] You are the leader! You must propose a team of {team_size} players (e.g. '0, 1').")
        loop = asyncio.get_running_loop()
        while True:
            text = await loop.run_in_executor(None, input, f"Select {team_size} players (0-4 comma-separated): ")
            try:
                parts = [int(p.strip()) for p in text.replace(",", " ").split() if p.strip()]
                unique_parts = list(dict.fromkeys(parts))
                if len(unique_parts) == team_size and all(0 <= p < self.num_players for p in unique_parts):
                    return unique_parts
                print(f"Invalid team size or player IDs. Exactly {team_size} unique players between 0 and 4 required.")
            except Exception:
                print("Could not parse input. Please enter numbers like: 0, 1")

    async def vote_on_team(self, turn: int, round_num: int, leader: int, team: List[int]) -> bool:
        print(f"\n[TEAM VOTE] Player {leader} proposed team {team}. Do you Approve or Reject?")
        loop = asyncio.get_running_loop()
        while True:
            vote = await loop.run_in_executor(None, input, "Vote Approve (y) or Reject (n): ")
            clean = vote.strip().lower()
            if clean in ("y", "yes", "approve", "1", "true"):
                return True
            elif clean in ("n", "no", "reject", "0", "false"):
                return False
            print("Please enter 'y' for Approve or 'n' for Reject.")

    async def vote_on_quest(self, turn: int, team: List[int]) -> bool:
        print(f"\n[SECRET QUEST VOTE] You are on the mission team {team}!")
        if self.side:
            print("As a Good player (Loyal Servant / Merlin), you MUST pass the quest.")
            return True

        loop = asyncio.get_running_loop()
        while True:
            vote = await loop.run_in_executor(None, input, "Secret Quest Vote - Pass (p) or Fail (f): ")
            clean = vote.strip().lower()
            if clean in ("p", "pass", "y", "true"):
                return True
            elif clean in ("f", "fail", "n", "false"):
                return False
            print("Please enter 'p' to Pass or 'f' to Fail.")

    async def assassinate(self) -> int:
        print("\n[ASSASSINATION PHASE] Good won 3 quests! Identify Merlin to snatch victory for Evil!")
        loop = asyncio.get_running_loop()
        while True:
            choice = await loop.run_in_executor(None, input, "Enter player ID to assassinate (0-4): ")
            try:
                target = int(choice.strip())
                if 0 <= target < self.num_players:
                    return target
            except Exception:
                pass
            print("Invalid player ID. Enter a number 0 to 4.")
