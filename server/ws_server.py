"""
FastAPI WebSocket server for the Avalon spectator frontend.

Modes:
- Replay: steps through a recorded arena game (`games/game_*.jsonl`), rebuilding every player's
  memory and knowledge graph as it goes (with `talk_edges.json` from the same folder, if present).
- Live: runs a game with HeuristicAgents and streams every event plus each agent's own memory.

Speech: each utterance is synthesized with Higgs TTS. If the seat's LiveKit avatar is running, the
audio goes to the avatar (the browser hears it from LiveKit); otherwise it is sent over this socket.

Messages to the browser (all {"type", "seq", "data"}):
  game_list, game_start, role_reveal, utterance, evil_chat, speaking, audio, team_proposed,
  team_vote_result, quest_result, assassination, game_over, memory_update, replay_end, error

Run:  py -3.12 -m uvicorn server.ws_server:app --port 8000
"""

import asyncio
import base64
import contextlib
import glob
import io
import json
import os
import sys
import uuid
import wave
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from avalon.agents import HeuristicAgent  # noqa: E402
from avalon.arena_adapter import ArenaGraphAdapter  # noqa: E402
from avalon.engine import ROLE_NAMES, Role  # noqa: E402
from avalon.replay import load_events, load_talk_edges  # noqa: E402
from avalon.runner import AvalonGameRunner  # noqa: E402
from server.audio_proxy import BOSON_API_KEY, get_tts_audio  # noqa: E402
from server.livekit_avatars import AvatarManager  # noqa: E402
from server.memory_view import serialize_memories  # noqa: E402
from server.human_web_agent import HumanWebAgent  # noqa: E402

GAME_PATTERNS = ["runs/**/games/game_*.jsonl", "experiments/**/games/game_*.jsonl"]

avatar_manager = AvatarManager()


@contextlib.asynccontextmanager
async def lifespan(_app: FastAPI):
    yield
    await avatar_manager.release_all()


app = FastAPI(title="AvalonBot Spectator Server", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


def list_game_files() -> List[str]:
    found = set()
    for pattern in GAME_PATTERNS:
        for path in glob.glob(os.path.join(ROOT, pattern), recursive=True):
            if ".partial." not in path:
                found.add(os.path.relpath(path, ROOT).replace("\\", "/"))
    return sorted(found)


def talk_edges_for(game_path: str) -> List[Dict[str, Any]]:
    """Hand-labelled or extracted talk edges stored next to the game's `games/` folder."""
    folder = os.path.dirname(os.path.dirname(game_path))
    path = os.path.join(folder, "talk_edges.json")
    return load_talk_edges(path) if os.path.exists(path) else []


def wav_seconds(wav_bytes: bytes) -> float:
    with wave.open(io.BytesIO(wav_bytes)) as w:
        return w.getnframes() / float(w.getframerate())


@app.get("/api/health")
async def health():
    return {"status": "ok", "has_boson_key": bool(BOSON_API_KEY), "avatars": avatar_manager.is_available}


@app.get("/api/games")
async def api_games():
    return JSONResponse({"games": list_game_files()})


@app.get("/api/avatar/status")
async def avatar_status():
    return JSONResponse(avatar_manager.get_room_info())


@app.post("/api/avatar/start")
async def avatar_start():
    if not avatar_manager.is_available:
        return JSONResponse({"error": "LiveKit or Boson credentials not configured", "available": False}, status_code=503)
    await avatar_manager.start()
    return JSONResponse(avatar_manager.get_room_info())


@app.post("/api/avatar/say/{seat}")
async def avatar_say(seat: int, text: str = "I am a loyal servant of Arthur."):
    """Makes one seat's avatar speak a line, to check voice and lip-sync."""
    wav_b64 = await get_tts_audio(text, seat)
    if not wav_b64:
        return JSONResponse({"error": "TTS failed"}, status_code=502)
    spoke = await avatar_manager.speak(seat, base64.b64decode(wav_b64))
    return JSONResponse({"spoke": spoke, "seconds": round(wav_seconds(base64.b64decode(wav_b64)), 2)})


@app.delete("/api/avatar/release")
async def avatar_release():
    await avatar_manager.release_all()
    return JSONResponse({"released": True})


@app.get("/api/avatar/token")
async def avatar_token():
    if not avatar_manager.is_available:
        return JSONResponse({"error": "LiveKit not configured"}, status_code=503)
    return JSONResponse({
        "token": avatar_manager.get_browser_token(f"spectator-{uuid.uuid4().hex[:8]}"),
        "url": os.getenv("LIVEKIT_URL", ""),
        "room": avatar_manager.room_name,
        "identities": avatar_manager.identities(),
    })


# ── Session: one spectator connection ────────────────────────────────

class GameSession:
    def __init__(self, ws: WebSocket):
        self.ws = ws
        self.paused = False
        self.speed = 1.0
        self.voice = True
        self.wake = asyncio.Event()
        self.task: Optional[asyncio.Task] = None
        self.closed = False
        self.human_seat: Optional[int] = None
        self.human_agent: Optional[HumanWebAgent] = None

    def resolve_human_action(self, action: str, data: Dict[str, Any]) -> None:
        if self.human_agent:
            self.human_agent.resolve_action(action, data)

    async def send(self, type_: str, data: Dict[str, Any], seq: int = 0) -> None:
        if self.closed:
            return
        try:
            await self.ws.send_json({"type": type_, "seq": seq, "data": data})
        except Exception:
            self.closed = True

    def start(self, coro) -> None:
        if self.task is not None and not self.task.done():
            self.task.cancel()
        self.paused = False
        self.task = asyncio.create_task(self._run(coro))

    async def _run(self, coro) -> None:
        try:
            await coro
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            await self.send("error", {"message": f"{type(exc).__name__}: {exc}"})
            raise

    def step(self) -> None:
        self.wake.set()

    async def gate(self) -> None:
        """Blocks while paused, until the spectator resumes or steps once."""
        while self.paused:
            self.wake.clear()
            await self.wake.wait()
            if self.paused:  # a single step
                return

    async def sleep(self, seconds: float) -> None:
        """Waits `seconds` (scaled by speed); a step or resume cuts it short."""
        self.wake.clear()
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(self.wake.wait(), seconds / max(self.speed, 0.1))

    async def speak(self, seat: int, text: str, seq: int) -> None:
        """Voices one line: through the seat's avatar if it is running, else over this socket."""
        await self.send("speaking", {"seat": seat, "active": True}, seq)
        wav_b64 = await get_tts_audio(text, seat) if self.voice and self.speed <= 2 else None
        if wav_b64 and avatar_manager.has_seat(seat):
            await avatar_manager.speak(seat, base64.b64decode(wav_b64))
        elif wav_b64:
            await self.send("audio", {"speaker": seat, "audio": wav_b64, "format": "wav"}, seq)
            await self.sleep(wav_seconds(base64.b64decode(wav_b64)) + 0.3)
        else:
            await self.sleep(min(6.0, 1.2 + 0.045 * len(text.split()) * 6))
        await self.send("speaking", {"seat": seat, "active": False}, seq)


def roles_payload(roles: Dict[int, Role], sides: Dict[int, bool]) -> Dict[str, Any]:
    return {"roles": {str(s): {"role": ROLE_NAMES[r], "side": "Good" if sides[s] else "Evil"} for s, r in roles.items()}}


@app.websocket("/ws/game")
async def game_ws(ws: WebSocket):
    await ws.accept()
    session = GameSession(ws)
    await session.send("game_list", {"games": list_game_files()})
    try:
        while True:
            msg = json.loads(await ws.receive_text())
            kind = msg.get("type")
            if kind == "list_games":
                await session.send("game_list", {"games": list_game_files()})
            elif kind == "start_game":
                if msg.get("mode") == "replay":
                    session.start(run_replay(session, msg.get("replay_file") or ""))
                else:
                    human_seat = msg.get("human_seat")
                    session.start(run_live_game(session, human_seat=human_seat))
            elif kind == "human_action_response":
                session.resolve_human_action(msg.get("action", ""), msg.get("data", {}))
            elif kind == "stop":
                if session.task is not None:
                    session.task.cancel()
            elif kind == "settings":
                if "voice" in msg:
                    session.voice = bool(msg["voice"])
            elif kind == "control":
                action = msg.get("action")
                if action == "pause":
                    session.paused = True
                elif action == "resume":
                    session.paused = False
                    session.step()
                elif action == "step":
                    session.step()
                elif action == "speed":
                    session.speed = float(msg.get("value", 1.0))
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        session.closed = True
        if session.task is not None:
            session.task.cancel()


# ── Replay ───────────────────────────────────────────────────────────

async def run_replay(session: GameSession, replay_file: str) -> None:
    path = os.path.normpath(os.path.join(ROOT, replay_file))
    if not path.startswith(ROOT) or not os.path.exists(path):
        await session.send("error", {"message": f"Replay not found: {replay_file}"})
        return
    events = load_events(path)
    adapter = ArenaGraphAdapter(talk_edges_for(path))
    pending_votes: Dict[str, bool] = {}

    for raw in events:
        kind, seq, d = raw["type"], raw["seq"], raw.get("data", {})
        if kind in ("llm_call", "beliefs", "quest_votes", "team_votes"):
            if kind == "team_votes":
                pending_votes = {str(i): bool(v) for i, v in enumerate(d.get("votes", []))}
            adapter.feed(raw)
            continue

        await session.gate()
        stepped = adapter.feed(raw)

        if kind == "game_start":
            state = adapter.state
            await session.send("game_start", {"mode": "replay", "file": replay_file, "leader": d.get("quest_leader", 0)}, seq)
            await session.send("role_reveal", roles_payload(state.roles, adapter.engine.player_sides), seq)
            await session.send("memory_update", {"players": serialize_memories(adapter.memories)}, seq)
            continue

        if kind == "discussion":
            data = {"turn": d["quest"], "round_num": d["round"], "speaker": d["seat"], "text": d["text"]}
            await session.send("utterance", data, seq)
        elif kind == "evil_chat":
            await session.send("evil_chat", {"turn": d.get("quest", 0), "speaker": d["seat"], "text": d["text"]}, seq)
        elif kind == "team_proposed":
            await session.send("team_proposed", {"turn": d["quest"], "round_num": d["round"],
                                                 "leader": d["leader"], "team": d["team"]}, seq)
        elif kind == "team_result":
            await session.send("team_vote_result", {"turn": d["quest"], "round_num": d["round"], "team": d["team"],
                                                    "votes": pending_votes, "approved": d["approved"]}, seq)
            pending_votes = {}
        elif kind == "quest_result":
            await session.send("quest_result", {"turn": d["quest"], "team": d["team"],
                                                "success": d["succeeded"], "num_fails": d["num_fails"]}, seq)
        elif kind == "assassination":
            await session.send("assassination", {"assassin": d.get("assassin"), "target": d.get("target"),
                                                 "hit_merlin": d.get("hit_merlin")}, seq)
        elif kind == "game_end":
            winner = "Good" if str(d.get("winner", "")).lower() == "good" else "Evil"
            await session.send("game_over", {"winner": winner, "reason": d.get("reason", "")}, seq)

        if stepped:
            await session.send("memory_update", {"players": serialize_memories(adapter.memories)}, seq)

        if kind in ("discussion", "evil_chat"):
            await session.speak(d["seat"], d["text"], seq)
        elif kind in ("team_proposed", "team_result", "quest_result"):
            await session.sleep(1.6)

    await session.send("replay_end", {"violations": adapter.state.violations if adapter.state else []})


# ── Live ─────────────────────────────────────────────────────────────

async def run_live_game(session: GameSession, human_seat: Optional[int] = None) -> None:
    session.human_seat = human_seat
    agents: Dict[int, Any] = {}
    for i in range(5):
        if human_seat is not None and i == human_seat:
            session.human_agent = HumanWebAgent(i, session=session, role=Role.LOYAL_SERVANT)
            agents[i] = session.human_agent
        else:
            agents[i] = HeuristicAgent(i, Role.LOYAL_SERVANT, condition="rule_graph", seed=None, merlin_graph=True)

    runner: Optional[AvalonGameRunner] = None
    started = False

    async def announce_start() -> None:
        nonlocal started
        if started:
            return
        started = True
        engine = runner.engine
        await session.send("game_start", {"mode": "live", "leader": engine.leader, "human_seat": human_seat})
        await session.send("role_reveal", roles_payload(engine.player_roles, engine.player_sides))

    def memories():
        return {p: a.memory for p, a in agents.items() if getattr(a, "memory", None) is not None}

    async def on_event(event_type: str, data: Dict[str, Any], recipients: List[int]) -> None:
        await announce_start()
        await session.gate()
        seq = int(data.pop("seq", 0))
        if event_type in ("utterance", "evil_chat"):
            await session.send(event_type, data, seq)
            # Only synthesize voice if speaker is not the human player
            if human_seat is None or data.get("speaker") != human_seat:
                await session.speak(data["speaker"], data["text"], seq)
        elif event_type in ("team_proposed", "team_vote_result", "quest_result"):
            data["votes"] = {str(p): v for p, v in data.get("votes", {}).items()}
            await session.send(event_type, data, seq)
            await session.send("memory_update", {"players": serialize_memories(memories())}, seq)
            await session.sleep(1.6)
        elif event_type == "assassination":
            await session.send("assassination", data, seq)
            await session.sleep(2.0)

    runner = AvalonGameRunner(agents=agents, tts_client=None, verbose=False, on_event=on_event)
    metrics = await runner.run_game()
    await session.send("memory_update", {"players": serialize_memories(memories())}, runner.seq + 1)
    await session.send("game_over", {
        "winner": "Good" if metrics.good_victory else "Evil",
        "reason": metrics.win_reason,
    }, runner.seq + 1)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server.ws_server:app", host="0.0.0.0", port=8000)
