"""
FastAPI WebSocket server for the Avalon spectator frontend.

Modes:
- Replay: steps through a recorded .jsonl game log with configurable delay.
- Live: runs a real game with HeuristicAgents, streaming events + TTS audio.

Run:  uvicorn server.ws_server:app --reload
"""

import asyncio
import glob
import json
import os
import sys
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from avalon.engine import Role, ROLE_NAMES  # noqa: E402
from avalon.agents import HeuristicAgent  # noqa: E402
from avalon.runner import AvalonGameRunner  # noqa: E402
from speech.boson_tts import HiggsTTSClient  # noqa: E402
from server.game_state import (  # noqa: E402
    serialize_game_state,
    serialize_event,
    translate_arena_event,
    PLAYER_NAMES,
)
from server.audio_proxy import (  # noqa: E402
    get_tts_audio,
    mint_realtime_token,
    build_realtime_session_config,
    BOSON_API_KEY,
)
from server.livekit_avatars import AvatarManager  # noqa: E402

app = FastAPI(title="AvalonBot Spectator Server")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

avatar_manager = AvatarManager()


@app.get("/api/health")
async def health():
    return {"status": "ok", "has_boson_key": bool(BOSON_API_KEY)}


@app.get("/api/games")
async def list_games():
    """Lists recorded game .jsonl files from runs/ directories."""
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    games = []
    for pattern in ["runs/*/games/game_*.jsonl", "runs/*/*/games/game_*.jsonl"]:
        for path in sorted(glob.glob(os.path.join(base, pattern))):
            if ".partial." in path:
                continue
            rel = os.path.relpath(path, base)
            games.append({"path": rel, "name": rel.replace("\\", "/")})
    return JSONResponse({"games": games})


@app.get("/api/realtime/token/{seat}")
async def realtime_token(seat: int):
    """Mints an ephemeral Higgs Realtime token for a given seat."""
    try:
        token = await mint_realtime_token()
        config = build_realtime_session_config(seat)
        return JSONResponse({"token": token, "session_config": config})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/avatar/status")
async def avatar_status():
    """Returns LiveKit avatar room info and whether avatars are available."""
    return JSONResponse(avatar_manager.get_room_info())


@app.post("/api/avatar/create")
async def create_avatars():
    """Creates avatar sessions for all 5 seats in the LiveKit room."""
    if not avatar_manager.is_available:
        return JSONResponse(
            {"error": "LiveKit credentials not configured", "available": False},
            status_code=503,
        )
    await avatar_manager.release_all()
    created = await avatar_manager.create_all()
    return JSONResponse({
        "created": len(created),
        "seats": {str(s): a.avatar_identity for s, a in created.items()},
        "room_info": avatar_manager.get_room_info(),
    })


@app.delete("/api/avatar/release")
async def release_avatars():
    """Releases all active avatar sessions."""
    await avatar_manager.release_all()
    return JSONResponse({"released": True})


@app.get("/api/avatar/token")
async def avatar_browser_token():
    """Mints a LiveKit room token for the browser spectator."""
    if not avatar_manager.is_available:
        return JSONResponse({"error": "LiveKit not configured"}, status_code=503)
    token = avatar_manager.get_browser_token()
    return JSONResponse({
        "token": token,
        "url": os.getenv("LIVEKIT_URL", ""),
        "room": avatar_manager.room_name,
    })


# ── Main game WebSocket ──────────────────────────────────────────────

class GameSession:
    """Tracks state for one spectator WebSocket connection."""

    def __init__(self, ws: WebSocket):
        self.ws = ws
        self.paused = False
        self.speed = 1.0  # multiplier for replay delay
        self.step_event = asyncio.Event()
        self.cancelled = False

    async def send(self, msg: Dict[str, Any]):
        await self.ws.send_json(msg)

    async def wait_delay(self, base_seconds: float):
        """Waits for a delay (respecting speed and pause), or returns immediately on step."""
        if self.cancelled:
            return
        delay = base_seconds / max(self.speed, 0.1)
        if self.paused:
            self.step_event.clear()
            await self.step_event.wait()
            if self.paused:
                return
        await asyncio.sleep(delay)


@app.websocket("/ws/game")
async def game_ws(ws: WebSocket):
    await ws.accept()
    session = GameSession(ws)

    # Control message handler runs concurrently
    async def control_loop():
        try:
            while True:
                raw = await ws.receive_text()
                msg = json.loads(raw)
                if msg.get("type") == "control":
                    action = msg.get("action")
                    if action == "pause":
                        session.paused = True
                    elif action == "resume":
                        session.paused = False
                        session.step_event.set()
                    elif action == "step":
                        session.step_event.set()
                    elif action == "speed":
                        session.speed = float(msg.get("value", 1.0))
                elif msg.get("type") == "start_game":
                    mode = msg.get("mode", "live")
                    if mode == "replay":
                        asyncio.ensure_future(run_replay(session, msg.get("replay_file", "")))
                    else:
                        asyncio.ensure_future(run_live_game(session))
        except WebSocketDisconnect:
            session.cancelled = True
        except Exception:
            session.cancelled = True

    await control_loop()


# ── Replay mode ──────────────────────────────────────────────────────

async def run_replay(session: GameSession, replay_file: str):
    """Steps through a recorded arena .jsonl file, sending translated events."""
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(base, replay_file)

    if not os.path.exists(path):
        await session.send({"type": "error", "data": {"message": f"File not found: {replay_file}"}})
        return

    from arena.events import read_events  # noqa: E402
    events = read_events(path)

    await session.send({"type": "replay_start", "data": {"file": replay_file, "total_events": len(events)}})

    for raw in events:
        if session.cancelled:
            break

        translated = translate_arena_event(raw)
        if translated is None:
            continue

        # For utterances, try to generate TTS audio
        if translated["type"] == "utterance":
            speaker = translated["data"].get("speaker", 0)
            text = translated["data"].get("text", "")
            audio_b64 = await get_tts_audio(text, speaker)
            if audio_b64:
                translated["audio"] = audio_b64

        await session.send(translated)

        # Delay based on event type
        if translated["type"] == "utterance":
            await session.wait_delay(2.5)
        elif translated["type"] in ("team_proposed", "team_vote_result", "quest_result"):
            await session.wait_delay(1.5)
        elif translated["type"] == "game_over":
            await session.wait_delay(0.5)
        else:
            await session.wait_delay(0.8)

    await session.send({"type": "replay_end", "data": {}})


# ── Live mode ────────────────────────────────────────────────────────

async def run_live_game(session: GameSession):
    """Runs a real game with HeuristicAgents, streaming every event."""
    agents = {
        i: HeuristicAgent(i, Role.LOYAL_SERVANT, condition="rule_graph", seed=i)
        for i in range(5)
    }

    tts = HiggsTTSClient(play_audio=False)
    seq_counter = [0]

    async def on_event(event_type: str, data: Dict[str, Any], recipients: List[int]):
        if session.cancelled:
            return
        seq_counter[0] += 1
        seq = seq_counter[0]

        msg = serialize_event(event_type, data, seq)

        # Generate TTS for utterances and evil chat
        if event_type in ("utterance", "evil_chat"):
            speaker = data.get("speaker", 0)
            text = data.get("text", "")
            audio_b64 = await get_tts_audio(text, speaker)
            if audio_b64:
                msg["audio"] = audio_b64

            # Notify frontend this player is speaking
            await session.send(serialize_event("speaking", {"seat": speaker, "active": True}, seq))

        await session.send(msg)

        if event_type in ("utterance", "evil_chat"):
            speaker = data.get("speaker", 0)
            await session.wait_delay(2.0)
            await session.send(serialize_event("speaking", {"seat": speaker, "active": False}, seq))
        elif event_type in ("team_proposed", "team_vote_result", "quest_result"):
            await session.wait_delay(1.5)

    runner = AvalonGameRunner(agents=agents, tts_client=None, verbose=False, on_event=on_event)

    await session.send({"type": "game_starting", "data": {"mode": "live"}})

    try:
        metrics = await runner.run_game()

        # Send final state with roles revealed
        roles_revealed = {
            str(seat): {"role": ROLE_NAMES[role], "side": "Good" if runner.engine.player_sides[seat] else "Evil"}
            for seat, role in runner.engine.player_roles.items()
        }
        await session.send(serialize_event("roles_revealed", {
            "roles": roles_revealed,
            "good_victory": metrics.good_victory,
            "win_reason": metrics.win_reason,
        }, seq_counter[0] + 1))

    except Exception as e:
        await session.send({"type": "error", "data": {"message": str(e)}})


# ── Realtime voice proxy ─────────────────────────────────────────────

@app.websocket("/ws/realtime/{seat}")
async def realtime_proxy(ws: WebSocket, seat: int):
    """Proxies audio between browser and Higgs Realtime for a seat's voice."""
    await ws.accept()

    try:
        token_data = await mint_realtime_token()
    except Exception as e:
        await ws.send_json({"type": "error", "data": {"message": str(e)}})
        await ws.close()
        return

    import websockets  # noqa: E402

    token = token_data["value"]
    subprotocols = ["realtime", f"bai-client-secret.{token}"]

    try:
        async with websockets.connect(
            "wss://api.boson.ai/v1/realtime/",
            subprotocols=subprotocols,
        ) as higgs_ws:
            # Send session config
            config = build_realtime_session_config(seat)
            await higgs_ws.send(json.dumps(config))

            async def browser_to_higgs():
                try:
                    while True:
                        data = await ws.receive_bytes()
                        await higgs_ws.send(data)
                except WebSocketDisconnect:
                    pass

            async def higgs_to_browser():
                try:
                    async for msg in higgs_ws:
                        if isinstance(msg, bytes):
                            await ws.send_bytes(msg)
                        else:
                            await ws.send_text(msg)
                except Exception:
                    pass

            await asyncio.gather(browser_to_higgs(), higgs_to_browser())

    except Exception as e:
        await ws.send_json({"type": "error", "data": {"message": str(e)}})
    finally:
        try:
            await ws.close()
        except Exception:
            pass


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server.ws_server:app", host="0.0.0.0", port=8000, reload=True)
