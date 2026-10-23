"""
Boson AI Higgs TTS 3 Client.

Provides streaming and file-based text-to-speech synthesis using
the Higgs TTS 3 endpoint (https://api.boson.ai/v1/audio/speech).
Maps each bot seat to a distinct voice personality.
"""

import os
import aiohttp
import asyncio
from typing import Dict, Optional
from pathlib import Path


DEFAULT_SEAT_VOICES: Dict[int, str] = {
    0: "male_1",
    1: "female_1",
    2: "male_2",
    3: "female_2",
    4: "default",
}


class HiggsTTSClient:
    """
    Client for Boson AI Higgs TTS 3 synthesis.
    """

    BASE_URL: str = "https://api.boson.ai/v1/audio/speech"

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "higgs-tts-3",
        seat_voices: Optional[Dict[int, str]] = None,
        cache_dir: Optional[str] = "audio_cache",
    ):
        self.api_key = api_key or os.getenv("BOSON_API_KEY", "")
        self.model = model
        self.seat_voices = seat_voices or DEFAULT_SEAT_VOICES
        self.cache_dir = Path(cache_dir) if cache_dir else None
        if self.cache_dir:
            self.cache_dir.mkdir(parents=True, exist_ok=True)

    def get_voice_for_seat(self, seat: int) -> str:
        return self.seat_voices.get(seat, "default")

    async def synthesize(
        self,
        text: str,
        voice: str = "default",
        response_format: str = "wav",
        save_path: Optional[str] = None,
    ) -> bytes:
        """
        Synthesizes text into audio bytes via Higgs TTS 3.
        """
        if not self.api_key:
            raise ValueError("BOSON_API_KEY is not set.")

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": self.model,
            "input": text,
            "voice": voice,
            "response_format": response_format,
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(self.BASE_URL, json=payload, headers=headers) as resp:
                if resp.status != 200:
                    err_text = await resp.text()
                    raise RuntimeError(f"Higgs TTS error (status {resp.status}): {err_text}")
                audio_bytes = await resp.read()

        if save_path:
            p = Path(save_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(audio_bytes)

        return audio_bytes

    async def speak_seat_utterance(
        self,
        seat: int,
        text: str,
        turn: int,
        round_num: int,
    ) -> Optional[bytes]:
        """
        Synthesizes a bot's spoken line using their designated seat voice.
        """
        voice = self.get_voice_for_seat(seat)
        save_file = None
        if self.cache_dir:
            save_file = str(self.cache_dir / f"turn_{turn}_round_{round_num}_seat_{seat}.wav")

        try:
            return await self.synthesize(text=text, voice=voice, save_path=save_file)
        except Exception as e:
            print(f"[HiggsTTS] Failed to synthesize seat {seat} ({voice}): {e}")
            return None
