"""
Boson AI Higgs TTS 3 Client & Audio Player.

Synthesizes spoken lines for all Avalon players using the Boson Higgs TTS 3 API.
Features:
- Distinct voice personality mapped to each bot seat (0 to 4).
- Emotion & prosody tag formatting (e.g. <|emotion:suspicious|>, <|emotion:confident|>).
- Local audio caching (audio_cache/turn_X_round_Y_player_Z.wav).
- Audio playback on Windows (via winsound).
- Offline fallback waveform synthesizer so audio testing works even before API keys are added.
"""

import os
import wave
import struct
import math
import asyncio
from typing import Dict, Optional, Tuple, List, Any
from pathlib import Path
import aiohttp

from dotenv import load_dotenv

from speech.budget import global_budget_tracker

load_dotenv()

try:
    import winsound
    HAS_WINSOUND = True
except ImportError:
    HAS_WINSOUND = False


# Same pairing as server/audio_proxy.py: one male voice for James, female voices for Claire and Emma.
DEFAULT_SEAT_VOICES: Dict[int, str] = {
    -1: os.getenv("BOSON_VOICE_NARRATOR", "nora"),
    0: os.getenv("BOSON_VOICE_0", "marcus"),
    1: os.getenv("BOSON_VOICE_1", "eleanor"),
    2: os.getenv("BOSON_VOICE_2", "nora"),
    3: os.getenv("BOSON_VOICE_3", "jake"),
    4: os.getenv("BOSON_VOICE_4", "chloe"),
}

# Verified Boson Higgs Control Tag Profiles per seat:
# - Emotion tokens: 'determination', 'enthusiasm', 'anger', 'fear', 'amusement', 'contemplation', 'pride', 'relief', 'elation'
# - Style tokens: 'whispering', 'shouting', 'singing'
# - Prosody tokens: 'expressive_high', 'expressive_low', 'speed_fast', 'speed_slow', 'speed_very_fast', 'pause', 'long_pause', 'pitch_low', 'pitch_high'
# - SFX tokens: 'laughter', 'sigh', 'cough', 'crying', 'screaming', 'burping', 'humming', 'sniff', 'sneeze'
SEAT_PROSODY = {
    -1: {  # Narrator: Clear, cinematic, poised storyteller
        "emotion": "contemplation",
        "style": None,
        "prosody": ["expressive_high"],
    },
    0: {  # Player 0 (Minion): Forceful, assertive, determined soldier
        "emotion": "determination",
        "style": None,
        "prosody": ["expressive_high"],
    },
    1: {  # Player 1 (Loyal Servant 1): Earnest, passionate, enthusiastic defender of Arthur
        "emotion": "enthusiasm",
        "style": None,
        "prosody": ["expressive_high"],
    },
    2: {  # Player 2 (Loyal Servant 2): High-energy, rapid, sharp questioning / indignation
        "emotion": "anger",
        "style": None,
        "prosody": ["speed_fast", "expressive_high"],
    },
    3: {  # Player 3 (Assassin): Slow, mocking, self-assured, chilling
        "emotion": "amusement",
        "style": None,
        "prosody": ["speed_slow", "expressive_high"],
    },
    4: {  # Player 4 (Merlin): Whispered, secretive, cryptic guidance to evade assassination
        "emotion": "contemplation",
        "style": "whispering",
        "prosody": ["expressive_high"],
    },
}

# Tones for offline fallback synthesizer (Hz)
SEAT_TONE_FREQS = {
    -1: 523, # C5 (Narrator chime)
    0: 220,  # A3 (low)
    1: 440,  # A4 (mid)
    2: 554,  # C#5 (high-mid)
    3: 330,  # E4 (firm)
    4: 659,  # E5 (high)
}


class HiggsTTSClient:
    """
    Client for Boson AI Higgs TTS 3 synthesis and audio playback.
    """

    BASE_URL: str = "https://api.boson.ai/v1/audio/speech"

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "higgs-tts-3",
        seat_voices: Optional[Dict[int, str]] = None,
        cache_dir: str = "audio_cache",
        play_audio: bool = True,
    ):
        self.api_key = (api_key or os.getenv("BOSON_API_KEY_4") or os.getenv("BOSON_API_KEY") or os.getenv("BOSON_API_KEY_1") or "").strip()
        self.model = model
        self.seat_voices = seat_voices or DEFAULT_SEAT_VOICES
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.play_audio = play_audio

        if not self.api_key:
            print("[Higgs TTS Notice] No Boson speech key found in .env — playing synthesized offline tones (beeps). Set BOSON_API_KEY_4 in .env to hear real voices.")

    def get_voice_for_seat(self, seat: int) -> str:
        if seat == -1:
            return self.seat_voices.get(-1, os.getenv("BOSON_VOICE_NARRATOR", "nora"))
        return self.seat_voices.get(seat, "default")

    def _generate_offline_wav(self, file_path: Path, freq: int = 440, duration_sec: float = 0.6):
        """
        Generates a small clean sine-wave PCM WAV for offline demonstration.
        """
        sample_rate = 24000
        num_samples = int(sample_rate * duration_sec)
        with wave.open(str(file_path), "w") as wav_file:
            wav_file.setnchannels(1)       # Mono
            wav_file.setsampwidth(2)      # 16-bit PCM
            wav_file.setframerate(sample_rate)
            raw_data = bytearray()
            for i in range(num_samples):
                t = float(i) / sample_rate
                # Sine with smooth attack and decay envelope
                envelope = math.sin(math.pi * i / num_samples)
                val = int(envelope * 10000.0 * math.sin(2.0 * math.pi * freq * t))
                raw_data.extend(struct.pack("<h", val))
            wav_file.writeframes(raw_data)

    async def synthesize(
        self,
        text: str,
        voice: str = "default",
        save_path: Optional[Path] = None,
        style: Optional[str] = None,
        emotion: Optional[str] = None,
        prosody: Optional[List[str]] = None,
        sfx: Optional[str] = None,
        normalize: bool = True,
        language: Optional[str] = "eng",
        seat: int = 0,
    ) -> Optional[bytes]:
        """
        Synthesizes text into audio bytes via Boson Higgs TTS 3.
        Supports Higgs inline control tokens:
        - <|style:...|> (e.g. whispering, shouting)
        - <|emotion:...|> (e.g. determination, anger, enthusiasm, contemplation, amusement)
        - <|prosody:...|> (e.g. expressive_high, expressive_low, speed_fast, speed_slow, pause)
        - <|sfx:...|> (e.g. laughter, sigh)
        """
        formatted_text = text

        # If text doesn't already contain control tokens, build from parameters
        if not text.startswith("<|"):
            prefix_tags = ""
            if style:
                prefix_tags += f"<|style:{style}|>"
            if emotion:
                prefix_tags += f"<|emotion:{emotion}|>"
            if prosody:
                for p in prosody:
                    # Sanitize legacy/misnamed token
                    token = "expressive_high" if p == "expressiveness_high" else p
                    prefix_tags += f"<|prosody:{token}|>"
            if sfx:
                # In Boson Higgs, SFX tokens work best with an accompanying onomatopoeia cue
                lower_text = text.lower()
                if sfx == "sigh" and "sigh" not in lower_text and "uh" not in lower_text:
                    prefix_tags += f"<|sfx:{sfx}|>Uh, "
                elif sfx == "laughter" and "haha" not in lower_text:
                    prefix_tags += f"<|sfx:{sfx}|>Haha! "
                else:
                    prefix_tags += f"<|sfx:{sfx}|>"

            formatted_text = f"{prefix_tags}{text}"

        # Clean any legacy expressiveness_high tokens inside text
        if "expressiveness_high" in formatted_text:
            formatted_text = formatted_text.replace("expressiveness_high", "expressive_high")

        # Check if API key is present and budget allows
        if self.api_key:
            if not global_budget_tracker.can_call():
                print(f"[Higgs TTS Notice] Budget cap of {global_budget_tracker.max_calls} calls reached. Falling back to offline tone synthesis.")
            else:
                headers = {
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                }
                payload: Dict[str, Any] = {
                    "model": self.model,
                    "input": formatted_text,
                    "voice": voice,
                    "response_format": "wav",
                    "normalize": normalize,
                }
                if language:
                    payload["language"] = language

                try:
                    async with aiohttp.ClientSession() as session:
                        async with session.post(self.BASE_URL, json=payload, headers=headers) as resp:
                            if resp.status == 200:
                                audio_bytes = await resp.read()
                                if save_path:
                                    save_path.write_bytes(audio_bytes)
                                global_budget_tracker.record_call(
                                    endpoint=self.BASE_URL,
                                    voice=voice,
                                    text_length=len(formatted_text),
                                    status_code=resp.status,
                                    byte_size=len(audio_bytes),
                                    extra={"seat": seat, "model": self.model},
                                )
                                return audio_bytes
                            else:
                                err_text = await resp.text()
                                print(f"[Higgs TTS Error] API returned HTTP {resp.status} for voice '{voice}': {err_text}")
                except Exception as e:
                    print(f"[Higgs TTS Error] Connection failed: {e}")

        # Fallback to local audio tone generation if key missing, budget exhausted, or failed
        if save_path:
            freq = SEAT_TONE_FREQS.get(seat, 440)
            self._generate_offline_wav(save_path, freq=freq)
            return save_path.read_bytes()

        return None

    def play_wav_file(self, wav_path: Path):
        """
        Plays the WAV audio file out loud on speakers.
        """
        if not self.play_audio:
            return

        if HAS_WINSOUND and wav_path.exists():
            try:
                # SND_FILENAME plays WAV synchronously so lines don't talk over each other
                winsound.PlaySound(str(wav_path), winsound.SND_FILENAME)
            except Exception as e:
                print(f"[AudioPlayer] Playback error: {e}")

    async def speak_seat_utterance(
        self,
        seat: int,
        text: str,
        turn: int,
        round_num: int,
        style: Optional[str] = None,
        emotion: Optional[str] = None,
        prosody: Optional[List[str]] = None,
        sfx: Optional[str] = None,
        tag: str = "",
    ) -> Optional[Path]:
        """
        Synthesizes and plays a player's line out loud in their designated seat voice.
        Applies seat-specific vocal delivery profile and verified Boson control tags.
        """
        voice = self.get_voice_for_seat(seat)
        suffix = f"_{tag}" if tag else ""
        save_file = self.cache_dir / f"turn_{turn + 1}_round_{round_num + 1}_seat_{seat}{suffix}.wav"

        profile = SEAT_PROSODY.get(seat, {
            "emotion": "determination",
            "style": None,
            "prosody": ["expressive_high"],
        })

        chosen_style = style or profile.get("style")
        chosen_emotion = emotion or profile.get("emotion")
        chosen_prosody = prosody or profile.get("prosody", ["expressive_high"])
        chosen_sfx = sfx

        if text.startswith("<|"):
            tag_end = text.rfind("|>")
            active_tags = text[:tag_end + 2] if tag_end != -1 else ""
            print(f"  [Higgs TTS] Synthesizing Player {seat} (Active Tags: {active_tags})...")
        else:
            tag_summary = f"Style: {chosen_style or 'normal'}, Emotion: {chosen_emotion}, Prosody: {chosen_prosody}"
            if chosen_sfx:
                tag_summary += f", SFX: {chosen_sfx}"
            print(f"  [Higgs TTS] Synthesizing Player {seat} ({tag_summary})...")

        # Synthesize audio
        await self.synthesize(
            text=text,
            voice=voice,
            save_path=save_file,
            style=chosen_style,
            emotion=chosen_emotion,
            prosody=chosen_prosody,
            sfx=chosen_sfx,
            seat=seat,
        )

        # Play audio out loud if file exists
        if save_file.exists():
            print(f"  [Higgs TTS Audio Out] Playing audio for Player {seat} ({save_file.name})")
            # Run playback in background thread so it doesn't freeze the asyncio loop
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self.play_wav_file, save_file)
            return save_file

        return None

    async def speak_narrator(
        self,
        text: str,
        tag: str = "announcement",
        turn: Optional[int] = None,
        round_num: Optional[int] = None,
        emotion: Optional[str] = "contemplation",
        style: Optional[str] = None,
        prosody: Optional[List[str]] = None,
        sfx: Optional[str] = None,
    ) -> Optional[Path]:
        """
        Synthesizes and plays a narration line out loud in the Narrator voice ('nora').
        Used for game master announcements (team proposals, vote outcomes, quest results).
        """
        voice = self.get_voice_for_seat(-1)
        if turn is not None and round_num is not None:
            save_file = self.cache_dir / f"narrator_turn_{turn + 1}_round_{round_num + 1}_{tag}.wav"
        elif turn is not None:
            save_file = self.cache_dir / f"narrator_turn_{turn + 1}_{tag}.wav"
        else:
            save_file = self.cache_dir / f"narrator_{tag}.wav"

        profile = SEAT_PROSODY.get(-1, {
            "emotion": "contemplation",
            "style": None,
            "prosody": ["expressive_high"],
        })

        chosen_style = style or profile.get("style")
        chosen_emotion = emotion or profile.get("emotion")
        chosen_prosody = prosody or profile.get("prosody", ["expressive_high"])
        chosen_sfx = sfx

        if text.startswith("<|"):
            tag_end = text.rfind("|>")
            active_tags = text[:tag_end + 2] if tag_end != -1 else ""
            print(f"  [Higgs TTS Narrator] Synthesizing (Active Tags: {active_tags})...")
        else:
            tag_summary = f"Emotion: {chosen_emotion}, Prosody: {chosen_prosody}"
            print(f"  [Higgs TTS Narrator] Synthesizing ({tag_summary})...")

        # Synthesize audio (seat=-1 for distinct Narrator frequency tone)
        await self.synthesize(
            text=text,
            voice=voice,
            save_path=save_file,
            style=chosen_style,
            emotion=chosen_emotion,
            prosody=chosen_prosody,
            sfx=chosen_sfx,
            seat=-1,
        )

        # Play audio out loud if file exists
        if save_file.exists():
            print(f"  [Higgs TTS Audio Out] Playing Narrator ({save_file.name})")
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self.play_wav_file, save_file)
            return save_file

        return None

