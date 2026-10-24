"""
Boson AI Higgs Realtime Speech-to-Speech & STT Client.

Based on the official Boson AI Higgs Realtime API tutorial:
- Mints short-lived ephemeral client secrets (POST /v1/realtime/client_secrets)
- Connects to wss://api.boson.ai/v1/realtime/
- Configures server VAD (voice activity detection) & live STT (higgs-stt-3.1)
- Enables the human player to speak directly to the table with automatic transcription
"""

import os
import json
import asyncio
import aiohttp
from typing import Dict, List, Optional, Callable, Any


class HiggsRealtimeManager:
    """
    Manages Higgs Realtime sessions and ephemeral token generation.
    """

    CLIENT_SECRETS_URL: str = "https://api.boson.ai/v1/realtime/client_secrets"
    WS_REALTIME_URL: str = "wss://api.boson.ai/v1/realtime/"

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("BOSON_API_KEY_4") or os.getenv("BOSON_API_KEY") or os.getenv("BOSON_API_KEY_1") or ""

    async def mint_ephemeral_token(self, expires_seconds: int = 600) -> Dict[str, Any]:
        """
        Mints an ephemeral token safe for browser consumption.
        """
        if not self.api_key:
            raise ValueError("BOSON_API_KEY is not set.")

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {"expires_after": {"seconds": expires_seconds}}

        async with aiohttp.ClientSession() as session:
            async with session.post(self.CLIENT_SECRETS_URL, json=payload, headers=headers) as resp:
                if resp.status != 200:
                    err_text = await resp.text()
                    raise RuntimeError(f"Failed to mint client secret ({resp.status}): {err_text}")
                data = await resp.json()
                return {"value": data.get("value"), "expires_at": data.get("expires_at")}

    @staticmethod
    def build_session_config(
        instructions: str = "You are a player in a game of Avalon.",
        voice: str = "default",
        enable_vad: bool = True,
        stt_model: str = "higgs-stt-3.1",
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: str = "auto",
    ) -> Dict[str, Any]:
        """
        Builds the standard session.update event for Higgs Realtime.
        """
        audio_config: Dict[str, Any] = {
            "input": {
                "format": {"type": "audio/pcm", "rate": 24000},
                "transcription": {"model": stt_model, "language": "en"},
            },
            "output": {
                "format": {"type": "audio/pcm", "rate": 24000},
                "voice": voice,
            },
        }

        if enable_vad:
            audio_config["input"]["turn_detection"] = {"type": "server_vad"}

        session_payload: Dict[str, Any] = {
            "model": "higgs-realtime",
            "instructions": instructions,
            "output_modalities": ["audio"],
            "audio": audio_config,
        }

        if tools is not None:
            session_payload["tools"] = tools
            session_payload["tool_choice"] = tool_choice

        return {
            "type": "session.update",
            "session": session_payload,
        }
