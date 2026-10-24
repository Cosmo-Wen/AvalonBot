"""
Higgs Avatar integration via LiveKit Cloud.

One avatar per seat joins a shared LiveKit room. Each avatar lip-syncs to speech sent by its own
voice participant (`avalon-voice-{seat}`) over a LiveKit data stream (`DataStreamAudioOutput`,
24 kHz 16-bit mono PCM), and republishes that audio with its video. The browser joins the same room
as a subscriber and renders each seat's video and audio.

Requires BOSON_API_KEY, LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET and `pip install livekit-agents livekit-api`.
Without them, `is_available` is False and the frontend falls back to portraits plus WebSocket audio.
"""

import asyncio
import audioop  # removed in Python 3.13; this project runs on 3.12
import io
import os
import wave
from datetime import timedelta
from typing import Dict, List, Optional

import aiohttp
from dotenv import load_dotenv

load_dotenv()

BOSON_BASE_URL = os.getenv("BOSON_BASE_URL", "https://api.boson.ai/v1")
BOSON_API_KEY = os.getenv("BOSON_API_KEY", "")
LIVEKIT_URL = os.getenv("LIVEKIT_URL", "")
LIVEKIT_API_KEY = os.getenv("LIVEKIT_API_KEY", "")
LIVEKIT_API_SECRET = os.getenv("LIVEKIT_API_SECRET", "")

try:
    from livekit import api as lk_api, rtc
    from livekit.agents.voice.avatar import DataStreamAudioOutput
    HAS_LIVEKIT = True
except ImportError:
    HAS_LIVEKIT = False

SAMPLE_RATE = 24000
FRAME_MS = 20
MAX_DURATION_SECONDS = 3600
PLAYOUT_TIMEOUT = 60.0
CREATE_ATTEMPTS = 5

# Boson's presets (GET /v1/avatars). Override per seat with BOSON_AVATAR_<seat>.
PRESET_AVATARS = [
    "builtin_james_v1",
    "builtin_claire_v1",
    "builtin_emma_v1",
    "builtin_claire_v1",
    "builtin_emma_v1",
]


def avatar_identity(seat: int) -> str:
    return f"avatar-seat-{seat}"


def voice_identity(seat: int) -> str:
    return f"avalon-voice-{seat}"


def wav_to_pcm24k(wav_bytes: bytes) -> bytes:
    """Decodes a WAV file to 24 kHz 16-bit mono PCM."""
    with wave.open(io.BytesIO(wav_bytes)) as w:
        channels, width, rate = w.getnchannels(), w.getsampwidth(), w.getframerate()
        pcm = w.readframes(w.getnframes())
    if width != 2:
        pcm = audioop.lin2lin(pcm, width, 2)
    if channels == 2:
        pcm = audioop.tomono(pcm, 2, 0.5, 0.5)
    if rate != SAMPLE_RATE:
        pcm, _ = audioop.ratecv(pcm, 2, 1, rate, SAMPLE_RATE, None)
    return pcm


class SeatAvatar:
    def __init__(self, seat: int, session_id: str):
        self.seat = seat
        self.session_id = session_id
        self.room: Optional["rtc.Room"] = None
        self.output: Optional["DataStreamAudioOutput"] = None

    @property
    def ready(self) -> bool:
        return self.output is not None


class AvatarManager:
    """Creates, drives and releases the 5 seat avatars in one LiveKit room."""

    def __init__(self, room_name: str = "avalon-game"):
        self.room_name = room_name
        self.seats: Dict[int, SeatAvatar] = {}
        self.errors: Dict[int, str] = {}
        self._lock = asyncio.Lock()

    @property
    def is_available(self) -> bool:
        return HAS_LIVEKIT and bool(LIVEKIT_URL and LIVEKIT_API_KEY and LIVEKIT_API_SECRET and BOSON_API_KEY)

    def has_seat(self, seat: int) -> bool:
        avatar = self.seats.get(seat)
        return avatar is not None and avatar.ready

    def _token(self, identity: str, publish: bool, subscribe: bool, publish_on_behalf: Optional[str] = None) -> str:
        grants = lk_api.VideoGrants(
            room_join=True,
            room=self.room_name,
            can_publish=publish,
            can_subscribe=subscribe,
            can_publish_data=True,
            can_publish_sources=["camera", "microphone"] if publish else None,
        )
        token = (
            lk_api.AccessToken(LIVEKIT_API_KEY, LIVEKIT_API_SECRET)
            .with_identity(identity)
            .with_grants(grants)
            .with_ttl(timedelta(seconds=MAX_DURATION_SECONDS + 300))
        )
        if publish_on_behalf:
            token = token.with_kind("agent").with_attributes({"lk.publish_on_behalf": publish_on_behalf})
        return token.to_jwt()

    def get_browser_token(self, identity: str = "spectator") -> Optional[str]:
        if not self.is_available:
            return None
        return self._token(identity, publish=False, subscribe=True)

    async def _create_session(self, http: aiohttp.ClientSession, seat: int) -> Optional[SeatAvatar]:
        # Boson answers 404 avatar_not_found when it can't host another session of a listed preset
        # right now, so fall back to the other faces rather than leaving the seat empty.
        preferred = os.getenv(f"BOSON_AVATAR_{seat}", PRESET_AVATARS[seat % len(PRESET_AVATARS)])
        for avatar_id in [preferred] + [a for a in dict.fromkeys(PRESET_AVATARS) if a != preferred]:
            avatar = await self._create_with(http, seat, avatar_id)
            if avatar is not None or "avatar_not_found" not in self.errors.get(seat, ""):
                return avatar
        return None

    async def _create_with(self, http: aiohttp.ClientSession, seat: int, avatar_id: str) -> Optional[SeatAvatar]:
        body = {
            "model": "higgs-avatar",
            "avatar_id": avatar_id,
            "transport": {
                "type": "livekit",
                "url": LIVEKIT_URL,
                "room_name": self.room_name,
                "participant_token": self._token(
                    avatar_identity(seat), publish=True, subscribe=False, publish_on_behalf=voice_identity(seat)
                ),
                "participant_identity": avatar_identity(seat),
                "publisher_identity": voice_identity(seat),
                "audio_source": "data_stream",
            },
            "max_duration_seconds": MAX_DURATION_SECONDS,
        }
        headers = {"Authorization": f"Bearer {BOSON_API_KEY}"}
        for attempt in range(CREATE_ATTEMPTS):
            try:
                async with http.post(f"{BOSON_BASE_URL}/avatar/sessions", json=body, headers=headers,
                                     timeout=aiohttp.ClientTimeout(total=90)) as resp:
                    if resp.status == 201:
                        self.errors.pop(seat, None)
                        print(f"[avatar] seat {seat}: {avatar_id}")
                        return SeatAvatar(seat, (await resp.json())["id"])
                    self.errors[seat] = f"{avatar_id}: create failed {resp.status}: {(await resp.text())[:200]}"
                    if resp.status != 429:
                        break
                    retry_after = float(resp.headers.get("Retry-After", 2 + 2 * attempt))
            except Exception as exc:  # network errors, timeouts: creation is not idempotent, so don't retry
                self.errors[seat] = f"create error: {exc}"
                break
            await asyncio.sleep(retry_after)
        print(f"[avatar] seat {seat}: {self.errors[seat]}")
        return None

    async def _connect_voice(self, avatar: SeatAvatar) -> None:
        room = rtc.Room()
        await room.connect(LIVEKIT_URL, self._token(voice_identity(avatar.seat), publish=True, subscribe=True))
        avatar.room = room
        avatar.output = DataStreamAudioOutput(
            room,
            destination_identity=avatar_identity(avatar.seat),
            sample_rate=SAMPLE_RATE,
            wait_remote_track=rtc.TrackKind.KIND_AUDIO,
        )

    async def start(self) -> Dict[int, SeatAvatar]:
        """Starts any seat avatar that isn't running yet. Safe to call repeatedly."""
        if not self.is_available:
            return {}
        async with self._lock:
            missing = [s for s in range(5) if s not in self.seats]
            # One at a time: parallel creates hit Boson's rate limit
            async with aiohttp.ClientSession() as http:
                for seat in missing:
                    avatar = await self._create_session(http, seat)
                    if avatar is None:
                        continue
                    self.seats[seat] = avatar
                    self.errors.pop(seat, None)
                    try:
                        await self._connect_voice(avatar)
                    except Exception as exc:
                        self.errors[seat] = f"voice connect error: {exc}"
                        print(f"[avatar] seat {seat}: {self.errors[seat]}")
            return dict(self.seats)

    async def speak(self, seat: int, wav_bytes: bytes) -> bool:
        """Streams one utterance to the seat's avatar and waits until it has been played."""
        avatar = self.seats.get(seat)
        if avatar is None or not avatar.ready:
            return False
        pcm = wav_to_pcm24k(wav_bytes)
        step = SAMPLE_RATE * FRAME_MS // 1000 * 2
        for i in range(0, len(pcm), step):
            chunk = pcm[i:i + step]
            await avatar.output.capture_frame(rtc.AudioFrame(chunk, SAMPLE_RATE, 1, len(chunk) // 2))
        avatar.output.flush()
        try:
            await asyncio.wait_for(avatar.output.wait_for_playout(), PLAYOUT_TIMEOUT)
        except asyncio.TimeoutError:
            print(f"[avatar] seat {seat}: no playback_finished within {PLAYOUT_TIMEOUT}s")
        return True

    async def release_all(self) -> None:
        async with self._lock:
            headers = {"Authorization": f"Bearer {BOSON_API_KEY}"}
            async with aiohttp.ClientSession() as http:
                for avatar in self.seats.values():
                    try:
                        await http.delete(f"{BOSON_BASE_URL}/avatar/sessions/{avatar.session_id}", headers=headers)
                    except Exception:
                        pass
                    if avatar.room is not None:
                        await avatar.room.disconnect()
            self.seats.clear()

    def get_room_info(self) -> Dict:
        return {
            "available": self.is_available,
            "room_name": self.room_name,
            "livekit_url": LIVEKIT_URL if self.is_available else None,
            "seats": {
                str(seat): {"identity": avatar_identity(seat), "session_id": a.session_id, "ready": a.ready}
                for seat, a in self.seats.items()
            },
            "errors": {str(s): e for s, e in self.errors.items()},
        }

    def identities(self) -> List[str]:
        return [avatar_identity(s) for s in range(5)]
