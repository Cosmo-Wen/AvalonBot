"""
Proxy for Boson AI Higgs TTS 3 and Higgs Realtime APIs.

Mints ephemeral tokens for browser Realtime connections and synthesizes
TTS audio with per-seat vocal profiles matching speech/boson_tts.py.
"""

import base64
import os
from typing import Any, Dict, Optional

import aiohttp
from dotenv import load_dotenv

load_dotenv()

BOSON_API_KEY = os.getenv("BOSON_API_KEY", "")

TTS_URL = "https://api.boson.ai/v1/audio/speech"
CLIENT_SECRETS_URL = "https://api.boson.ai/v1/realtime/client_secrets"
REALTIME_WS_URL = "wss://api.boson.ai/v1/realtime/"

DEFAULT_VOICES = {
    -1: os.getenv("BOSON_VOICE_NARRATOR", "nora"),
    0: os.getenv("BOSON_VOICE_0", "marcus"),
    1: os.getenv("BOSON_VOICE_1", "eleanor"),
    2: os.getenv("BOSON_VOICE_2", "jake"),
    3: os.getenv("BOSON_VOICE_3", "oliver"),
    4: os.getenv("BOSON_VOICE_4", "chloe"),
}

SEAT_PROFILES = {
    -1: {"emotion": "contemplation", "style": None, "prosody": ["expressive_high"]},
    0: {"emotion": "determination", "style": None, "prosody": ["expressive_high"]},
    1: {"emotion": "enthusiasm", "style": None, "prosody": ["expressive_high"]},
    2: {"emotion": "anger", "style": None, "prosody": ["speed_fast", "expressive_high"]},
    3: {"emotion": "amusement", "style": None, "prosody": ["speed_slow", "expressive_high"]},
    4: {"emotion": "contemplation", "style": "whispering", "prosody": ["expressive_high"]},
}

SEAT_VOICE_IDS = {
    i: DEFAULT_VOICES.get(i, "default") for i in range(-1, 5)
}


def _build_control_tags(seat: int) -> str:
    profile = SEAT_PROFILES.get(seat, SEAT_PROFILES[0])
    tags = ""
    if profile["style"]:
        tags += f"<|style:{profile['style']}|>"
    if profile["emotion"]:
        tags += f"<|emotion:{profile['emotion']}|>"
    for p in profile.get("prosody", []):
        token = "expressive_high" if p == "expressiveness_high" else p
        tags += f"<|prosody:{token}|>"
    return tags


async def mint_realtime_token(expires_seconds: int = 600) -> Dict[str, Any]:
    """Mints an ephemeral Higgs Realtime client secret safe for browser use."""
    if not BOSON_API_KEY:
        raise ValueError("BOSON_API_KEY not set")

    headers = {
        "Authorization": f"Bearer {BOSON_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {"expires_after": {"seconds": expires_seconds}}

    async with aiohttp.ClientSession() as session:
        async with session.post(CLIENT_SECRETS_URL, json=payload, headers=headers) as resp:
            if resp.status != 200:
                err = await resp.text()
                raise RuntimeError(f"Token mint failed ({resp.status}): {err}")
            data = await resp.json()
            return {"value": data.get("value"), "expires_at": data.get("expires_at")}


async def get_tts_audio(text: str, seat: int = 0) -> Optional[str]:
    """Synthesizes speech via Higgs TTS 3 and returns base64-encoded WAV.
    Returns None if no API key or the call fails."""
    if not BOSON_API_KEY:
        return None

    tags = _build_control_tags(seat)
    formatted_text = f"{tags}{text}" if not text.startswith("<|") else text

    headers = {
        "Authorization": f"Bearer {BOSON_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": "higgs-tts-3",
        "input": formatted_text,
        "voice": SEAT_VOICE_IDS.get(seat, "default"),
        "response_format": "wav",
        "normalize": True,
        "language": "eng",
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(TTS_URL, json=payload, headers=headers) as resp:
                if resp.status == 200:
                    audio_bytes = await resp.read()
                    return base64.b64encode(audio_bytes).decode("ascii")
                else:
                    err = await resp.text()
                    print(f"[TTS] HTTP {resp.status}: {err}")
                    return None
    except Exception as e:
        print(f"[TTS] Error: {e}")
        return None


def build_realtime_session_config(seat: int = 0) -> Dict[str, Any]:
    """Builds a Higgs Realtime session.update config for a given seat's voice."""
    profile = SEAT_PROFILES.get(seat, SEAT_PROFILES[0])
    voice = SEAT_VOICE_IDS.get(seat, "default")

    return {
        "type": "session.update",
        "session": {
            "model": "higgs-realtime",
            "instructions": f"You are Player {seat} in a game of The Resistance: Avalon. Speak in character.",
            "output_modalities": ["audio"],
            "audio": {
                "input": {
                    "format": {"type": "audio/pcm", "rate": 24000},
                    "transcription": {"model": "higgs-stt-3.1", "language": "en"},
                },
                "output": {
                    "format": {"type": "audio/pcm", "rate": 24000},
                    "voice": voice,
                },
            },
        },
    }
