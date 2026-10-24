"""
Higgs Avatar integration via LiveKit Cloud.

Creates 5 avatar sessions (one per player seat) in a shared LiveKit room.
Each avatar lip-syncs to the speech audio produced by Higgs Realtime/TTS
for that player. The browser joins the room and subscribes to all 5 video
tracks to see the talking-head avatars around the Round Table.

Requires: BOSON_API_KEY, LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET

Falls back gracefully when credentials are missing or avatar capacity is full.
"""

import asyncio
import base64
import json
import os
import time
from typing import Dict, List, Optional

import aiohttp

BOSON_BASE_URL = os.getenv("BOSON_BASE_URL", "https://api.boson.ai/v1")
BOSON_API_KEY = os.getenv("BOSON_API_KEY", "")
LIVEKIT_URL = os.getenv("LIVEKIT_URL", "")
LIVEKIT_API_KEY = os.getenv("LIVEKIT_API_KEY", "")
LIVEKIT_API_SECRET = os.getenv("LIVEKIT_API_SECRET", "")

PRESET_AVATARS = [
    "builtin_claire_v1",
    "builtin_emma_v1",
    "builtin_james_v1",
    "builtin_claire_v1",
    "builtin_emma_v1",
]

SEAT_IDENTITIES = [f"avatar-seat-{i}" for i in range(5)]
AGENT_IDENTITY = "avalon-game-agent"


def _has_livekit_credentials() -> bool:
    return bool(LIVEKIT_URL and LIVEKIT_API_KEY and LIVEKIT_API_SECRET and BOSON_API_KEY)


def _mint_livekit_token(identity: str, room: str, ttl: int = 3600,
                        can_publish: bool = False, can_subscribe: bool = False,
                        can_publish_data: bool = False) -> str:
    """Mint a LiveKit JWT. Uses the livekit-api package if available, otherwise
    falls back to a manual JWT construction."""
    try:
        from livekit.api import AccessToken, VideoGrants
        token = AccessToken(LIVEKIT_API_KEY, LIVEKIT_API_SECRET)
        token.identity = identity
        token.ttl = ttl
        grants = VideoGrants(
            room_join=True,
            room=room,
            can_publish=can_publish,
            can_subscribe=can_subscribe,
            can_publish_data=can_publish_data,
        )
        if can_publish:
            grants.can_publish_sources = ["camera", "microphone"]
        token.video_grants = grants
        return token.to_jwt()
    except ImportError:
        import hashlib
        import hmac
        header = base64.urlsafe_b64encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode()).rstrip(b"=")
        now = int(time.time())
        claims = {
            "iss": LIVEKIT_API_KEY,
            "sub": identity,
            "iat": now,
            "exp": now + ttl,
            "video": {
                "roomJoin": True,
                "room": room,
                "canPublish": can_publish,
                "canSubscribe": can_subscribe,
                "canPublishData": can_publish_data,
            },
        }
        if can_publish:
            claims["video"]["canPublishSources"] = ["camera", "microphone"]
        payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=")
        signing_input = header + b"." + payload
        sig = base64.urlsafe_b64encode(
            hmac.new(LIVEKIT_API_SECRET.encode(), signing_input, hashlib.sha256).digest()
        ).rstrip(b"=")
        return (signing_input + b"." + sig).decode()


async def list_avatars() -> List[Dict]:
    if not BOSON_API_KEY:
        return []
    async with aiohttp.ClientSession() as session:
        async with session.get(
            f"{BOSON_BASE_URL}/avatars",
            headers={"Authorization": f"Bearer {BOSON_API_KEY}"},
        ) as resp:
            if resp.status != 200:
                return []
            data = await resp.json()
            return data.get("data", data) if isinstance(data, dict) else data


class AvatarSession:
    """Manages one Higgs Avatar realtime session for a player seat."""

    def __init__(self, seat: int, session_id: str, avatar_identity: str):
        self.seat = seat
        self.session_id = session_id
        self.avatar_identity = avatar_identity
        self.active = True

    async def release(self):
        if not self.active:
            return
        self.active = False
        try:
            async with aiohttp.ClientSession() as session:
                await session.delete(
                    f"{BOSON_BASE_URL}/avatar/sessions/{self.session_id}",
                    headers={"Authorization": f"Bearer {BOSON_API_KEY}"},
                )
        except Exception:
            pass


class AvatarManager:
    """Creates and manages avatar sessions for all 5 player seats in a LiveKit room."""

    def __init__(self, room_name: str = "avalon-game"):
        self.room_name = room_name
        self.sessions: Dict[int, AvatarSession] = {}
        self._available = _has_livekit_credentials()

    @property
    def is_available(self) -> bool:
        return self._available

    def get_browser_token(self, identity: str = "spectator", ttl: int = 3600) -> Optional[str]:
        if not self._available:
            return None
        return _mint_livekit_token(
            identity=identity,
            room=self.room_name,
            ttl=ttl,
            can_subscribe=True,
        )

    async def create_session(self, seat: int, avatar_id: Optional[str] = None) -> Optional[AvatarSession]:
        if not self._available:
            return None

        avatar_id = avatar_id or PRESET_AVATARS[seat % len(PRESET_AVATARS)]
        identity = SEAT_IDENTITIES[seat]

        avatar_token = _mint_livekit_token(
            identity=identity,
            room=self.room_name,
            ttl=7200,
            can_publish=True,
            can_publish_data=True,
        )

        body = {
            "avatar_id": avatar_id,
            "transport": {
                "type": "livekit",
                "url": LIVEKIT_URL,
                "room_name": self.room_name,
                "participant_token": avatar_token,
                "participant_identity": identity,
                "publisher_identity": AGENT_IDENTITY,
            },
            "max_duration_seconds": 3600,
            "output": {"size": "480x640"},
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{BOSON_BASE_URL}/avatar/sessions",
                    headers={
                        "Authorization": f"Bearer {BOSON_API_KEY}",
                        "Content-Type": "application/json",
                    },
                    json=body,
                ) as resp:
                    if resp.status == 201:
                        data = await resp.json()
                        avatar_session = AvatarSession(
                            seat=seat,
                            session_id=data["id"],
                            avatar_identity=identity,
                        )
                        self.sessions[seat] = avatar_session
                        return avatar_session
                    elif resp.status == 429:
                        error = await resp.json()
                        if error.get("code") == "capacity_exhausted":
                            retry_after = resp.headers.get("Retry-After", "10")
                            print(f"[avatar] seat {seat}: capacity full, retry after {retry_after}s")
                        return None
                    else:
                        text = await resp.text()
                        print(f"[avatar] seat {seat}: create failed {resp.status}: {text}")
                        return None
        except Exception as e:
            print(f"[avatar] seat {seat}: create error: {e}")
            return None

    async def create_all(self, avatar_ids: Optional[List[str]] = None) -> Dict[int, AvatarSession]:
        tasks = []
        for seat in range(5):
            avatar_id = avatar_ids[seat] if avatar_ids and seat < len(avatar_ids) else None
            tasks.append(self.create_session(seat, avatar_id))

        results = await asyncio.gather(*tasks, return_exceptions=True)
        created = {}
        for seat, result in enumerate(results):
            if isinstance(result, AvatarSession):
                created[seat] = result
        return created

    async def release_all(self):
        tasks = [s.release() for s in self.sessions.values()]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self.sessions.clear()

    def get_avatar_identities(self) -> Dict[int, str]:
        return {seat: s.avatar_identity for seat, s in self.sessions.items()}

    def get_room_info(self) -> Dict:
        return {
            "available": self._available,
            "room_name": self.room_name,
            "livekit_url": LIVEKIT_URL if self._available else None,
            "seats": {
                seat: {
                    "avatar_identity": s.avatar_identity,
                    "session_id": s.session_id,
                    "active": s.active,
                }
                for seat, s in self.sessions.items()
            },
        }
