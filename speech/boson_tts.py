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
from typing import Dict, Optional, Tuple
from pathlib import Path
import aiohttp

from dotenv import load_dotenv

load_dotenv()

try:
    import winsound
    HAS_WINSOUND = True
except ImportError:
    HAS_WINSOUND = False


DEFAULT_SEAT_VOICES: Dict[int, str] = {
    0: os.getenv("BOSON_VOICE_0", "default"),
    1: os.getenv("BOSON_VOICE_1", "default"),
    2: os.getenv("BOSON_VOICE_2", "default"),
    3: os.getenv("BOSON_VOICE_3", "default"),
    4: os.getenv("BOSON_VOICE_4", "default"),
}

# Distinct acoustic profiles (speed multiplier + baseline emotion) per seat
# Note: '<|emotion:suspicious|>' sounds flat/subtle in speech synthesis, so we use
# higher-contrast tags like 'confident', 'angry', 'surprised', and varied tempo speeds.
SEAT_PROSODY = {
    0: {"speed": "0.92", "emotion": "confident"},  # Deliberate, steady, self-assured
    1: {"speed": "1.00", "emotion": "neutral"},    # Standard conversational pace
    2: {"speed": "1.15", "emotion": "surprised"},  # Fast, animated, energetic
    3: {"speed": "0.88", "emotion": "angry"},      # Low tempo, intense, firm
    4: {"speed": "1.06", "emotion": "confident"},  # Measured, guiding, authoritative
}

# Tones for offline fallback synthesizer (Hz)
SEAT_TONE_FREQS = {
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
        self.api_key = (api_key or os.getenv("BOSON_API_KEY", "")).strip()
        self.model = model
        self.seat_voices = seat_voices or DEFAULT_SEAT_VOICES
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.play_audio = play_audio

        if not self.api_key:
            print("[Higgs TTS Notice] No BOSON_API_KEY found in .env — playing synthesized offline tones (beeps). Set BOSON_API_KEY in .env to hear real voices.")

    def get_voice_for_seat(self, seat: int) -> str:
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
        emotion: Optional[str] = None,
        speed: Optional[str] = None,
        seat: int = 0,
    ) -> Optional[bytes]:
        """
        Synthesizes text into audio bytes via Boson Higgs TTS 3.
        Supports Higgs inline speed and emotion tags (e.g. <|speed:0.92|><|emotion:confident|>).
        """
        formatted_text = text
        prefix_tags = ""
        if speed and f"<|speed:" not in text:
            prefix_tags += f"<|speed:{speed}|>"
        if emotion and f"<|emotion:" not in text:
            prefix_tags += f"<|emotion:{emotion}|>"

        if prefix_tags and not text.startswith("<|"):
            formatted_text = f"{prefix_tags}{text}"

        # If API key is present, call live Boson API
        if self.api_key:
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }
            payload = {
                "model": self.model,
                "input": formatted_text,
                "voice": voice,
                "response_format": "wav",
            }

            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(self.BASE_URL, json=payload, headers=headers) as resp:
                        if resp.status == 200:
                            audio_bytes = await resp.read()
                            if save_path:
                                save_path.write_bytes(audio_bytes)
                            return audio_bytes
                        else:
                            err_text = await resp.text()
                            print(f"[Higgs TTS Error] API returned HTTP {resp.status} for voice '{voice}': {err_text}")
            except Exception as e:
                print(f"[Higgs TTS Error] Connection failed: {e}")

        # Fallback to local audio tone generation if key missing or failed
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
        emotion: Optional[str] = None,
        speed: Optional[str] = None,
    ) -> Optional[Path]:
        """
        Synthesizes and plays a player's line out loud in their designated seat voice.
        Applies seat-specific prosody and context-aware emotion.
        """
        voice = self.get_voice_for_seat(seat)
        save_file = self.cache_dir / f"turn_{turn + 1}_round_{round_num + 1}_seat_{seat}.wav"

        prosody = SEAT_PROSODY.get(seat, {"speed": "1.00", "emotion": "neutral"})
        chosen_speed = speed or prosody.get("speed", "1.00")

        # Contextual emotion selection (avoiding 'suspicious' which produces subtle/flat audio)
        if not emotion:
            lower = text.lower()
            if "sabotage" in lower or "failed" in lower or "how" in lower:
                chosen_emotion = "surprised"  # High energy reaction
            elif "accuse" in lower or "defend" in lower or "protest" in lower or "not me" in lower:
                chosen_emotion = "angry"      # Sharp, defensive inflection
            elif "leader" in lower or "trust" in lower or "servant" in lower or "solid" in lower:
                chosen_emotion = "confident"  # Resonant, firm tone
            else:
                chosen_emotion = prosody.get("emotion", "neutral")
        else:
            chosen_emotion = emotion

        print(f"  [Higgs TTS] Synthesizing Player {seat} (Voice: {voice}, Speed: {chosen_speed}, Emotion: {chosen_emotion})...")

        # Synthesize audio
        await self.synthesize(
            text=text,
            voice=voice,
            save_path=save_file,
            emotion=chosen_emotion,
            speed=chosen_speed,
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
