"""
Higgs Avatar integration via LiveKit Cloud.

One avatar per seat joins a shared LiveKit room. Each avatar lip-syncs to speech sent by its own
voice participant (`avalon-voice-{seat}`) over a LiveKit data stream (`DataStreamAudioOutput`,
24 kHz 16-bit mono PCM), and republishes that audio with its video. The browser joins the same room
as a subscriber and renders each seat's video and audio.

Requires BOSON_API_KEY_1 through BOSON_API_KEY_3 for the faces. Key 4 is speech only. LIVEKIT_URL,
LIVEKIT_API_KEY, LIVEKIT_API_SECRET and `pip install livekit-agents livekit-api`.
Without them, `is_available` is False and the frontend falls back to portraits plus WebSocket audio.
"""

import asyncio
import io
import json
try:
    import audioop
except ImportError:
    import audioop_lts as audioop
import os
import wave
from datetime import timedelta
from pathlib import Path
from typing import Dict, List, Optional

import aiohttp
from dotenv import load_dotenv

load_dotenv()

BOSON_BASE_URL = os.getenv("BOSON_BASE_URL", "https://api.boson.ai/v1")
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
SESSION_FILE = Path(__file__).with_name("avatar_sessions.json")

# GET /v1/avatars on every key returns only these three public faces.
# The same preset cannot run twice on one key, so a repeated face uses another key.
# Key 4 is not a face account: it could not start a session. Speech uses it.
# Seat: (avatar id, BOSON_API_KEY slot). BOSON_AVATAR_<seat> still overrides the id.
SEAT_FACES = [
    ("builtin_james_v1", 1),
    ("builtin_claire_v1", 2),
    ("builtin_emma_v1", 3),
    ("builtin_james_v1", 2),
    ("builtin_claire_v1", 3),
]


def boson_key(slot: int) -> str:
    """Slot 1..4 are BOSON_API_KEY_1..4. Slot 0 is the legacy BOSON_API_KEY."""
    if slot <= 0:
        return os.getenv("BOSON_API_KEY", "").strip()
    return os.getenv(f"BOSON_API_KEY_{slot}", "").strip()


def key_slot_for_seat(seat: int) -> Optional[int]:
    """Key that starts this seat. A repeated face is placed on a key that is not already using it."""
    if seat < 0 or seat >= len(SEAT_FACES):
        return None
    slot = SEAT_FACES[seat][1]
    if boson_key(slot):
        return slot
    return None


def face_for_seat(seat: int) -> Optional[str]:
    override = os.getenv(f"BOSON_AVATAR_{seat}", "").strip()
    if override:
        return override
    if 0 <= seat < len(SEAT_FACES):
        return SEAT_FACES[seat][0]
    return None


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
    def __init__(self, seat: int, session_id: str, key_slot: int = 0):
        self.seat = seat
        self.session_id = session_id
        self.key_slot = key_slot
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
        return HAS_LIVEKIT and bool(LIVEKIT_URL and LIVEKIT_API_KEY and LIVEKIT_API_SECRET and any(boson_key(i) for i in range(5)))

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
        slot = key_slot_for_seat(seat)
        if slot is None:
            wanted = SEAT_FACES[seat][1] if 0 <= seat < len(SEAT_FACES) else seat + 1
            self.errors[seat] = f"BOSON_API_KEY_{wanted} is not set"
            print(f"[avatar] seat {seat}: {self.errors[seat]}")
            return None
        avatar_id = face_for_seat(seat)
        if avatar_id is None:
            self.errors[seat] = (
                f"No face for this seat. Set BOSON_AVATAR_{seat} to an avatar uploaded on BOSON_API_KEY_{slot}."
            )
            print(f"[avatar] seat {seat}: {self.errors[seat]}")
            return None
        return await self._create_with(http, seat, avatar_id, slot)

    async def _create_with(self, http: aiohttp.ClientSession, seat: int, avatar_id: str, key_slot: int) -> Optional[SeatAvatar]:
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
        headers = {"Authorization": f"Bearer {boson_key(key_slot)}"}
        for attempt in range(CREATE_ATTEMPTS):
            try:
                async with http.post(f"{BOSON_BASE_URL}/avatar/sessions", json=body, headers=headers,
                                     timeout=aiohttp.ClientTimeout(total=90)) as resp:
                    if resp.status == 201:
                        self.errors.pop(seat, None)
                        print(f"[avatar] seat {seat}: {avatar_id} on key {key_slot}")
                        return SeatAvatar(seat, (await resp.json())["id"], key_slot)
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

    def _remember(self) -> None:
        """Session ids survive a server reload, so the next process can release them."""
        saved = {
            str(seat): {"id": a.session_id, "slot": a.key_slot}
            for seat, a in self.seats.items() if a.session_id.startswith("avrt_")
        }
        SESSION_FILE.write_text(json.dumps(saved))

    async def _delete_session(self, http: aiohttp.ClientSession, session_id: str, key_slot: int) -> None:
        if not session_id.startswith("avrt_"):
            return
        try:
            await http.delete(
                f"{BOSON_BASE_URL}/avatar/sessions/{session_id}",
                headers={"Authorization": f"Bearer {boson_key(key_slot)}"},
            )
        except Exception:
            pass

    async def _seats_in_room(self) -> set:
        """Seats whose avatar is already publishing in the room, even after a restart forgot them."""
        lk = lk_api.LiveKitAPI(LIVEKIT_URL.replace("wss://", "https://").replace("ws://", "http://"),
                               LIVEKIT_API_KEY, LIVEKIT_API_SECRET)
        try:
            parts = await lk.room.list_participants(lk_api.ListParticipantsRequest(room=self.room_name))
        except Exception:
            return set()
        finally:
            await lk.aclose()
        seats = set()
        for p in parts.participants:
            if p.identity.startswith("avatar-seat-") and p.identity.rsplit("-", 1)[-1].isdigit():
                seats.add(int(p.identity.rsplit("-", 1)[-1]))
        return seats

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
            # A reload used to forget the running sessions and then fail to make new ones,
            # because Boson was still full. Take the ones already in the room back over.
            for seat in await self._seats_in_room():
                if seat in self.seats:
                    continue
                avatar = SeatAvatar(seat, "")
                self.seats[seat] = avatar
                try:
                    await self._connect_voice(avatar)
                    self.errors.pop(seat, None)
                    print(f"[avatar] seat {seat}: reconnected voice to the running avatar")
                except Exception as exc:
                    self.seats.pop(seat, None)
                    self.errors[seat] = f"voice connect error: {exc}"
                    print(f"[avatar] seat {seat}: {self.errors[seat]}")

            missing = [s for s in range(5) if s not in self.seats]
            # One at a time: parallel creates hit Boson's rate limit
            async with aiohttp.ClientSession() as http:
                for seat in missing:
                    avatar = await self._create_session(http, seat)
                    if avatar is None:
                        continue
                    self.seats[seat] = avatar
                    self.errors.pop(seat, None)
                    self._remember()
                    try:
                        await self._connect_voice(avatar)
                    except Exception as exc:
                        self.errors[seat] = f"voice connect error: {exc}"
                        print(f"[avatar] seat {seat}: {self.errors[seat]}")
            self._remember()
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

    async def detach_voices(self) -> None:
        """Drops our voice connections but leaves the avatars in the room, so a restart can resume them."""
        async with self._lock:
            for avatar in self.seats.values():
                if avatar.room is not None:
                    await avatar.room.disconnect()
                    avatar.room = None
                    avatar.output = None
            self.seats.clear()

    async def release_all(self) -> None:
        async with self._lock:
            async with aiohttp.ClientSession() as http:
                for avatar in self.seats.values():
                    await self._delete_session(http, avatar.session_id, avatar.key_slot)
                    if avatar.room is not None:
                        await avatar.room.disconnect()
            self.seats.clear()
            self._remember()

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
