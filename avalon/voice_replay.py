"""
avalon/voice_replay.py - Voice Reenactment for Recorded Avalon-LLM Transcripts

Replays historical LLM games (e.g. from experiments/avalon-llm-haiku-pilot/game4-all-fixes/games/game_00000.jsonl)
through the Boson AI voice pipeline, bringing recorded LLM dialogues to life with distinct character voices,
emotional prosody, and live visual game tracking.

Usage:
  python -m avalon.voice_replay <game.jsonl> [--mute] [--quest N] [--max-lines N]
"""

import sys
import json
import asyncio
from pathlib import Path
from typing import Dict, List, Any, Optional

from avalon.engine import Role, ROLE_NAMES
from speech.boson_tts import HiggsTTSClient
from speech.intent_compiler import SpeechIntentCompiler, DeliveryIntent
from speech.belief_prosody_coupler import BeliefProsodyCoupler
from speech.emotion_mapper import GameStateEmotionMapper
from speech.budget import global_budget_tracker

ROLE_MAP: Dict[str, Role] = {
    "Merlin": Role.MERLIN,
    "Assassin": Role.ASSASSIN,
    "Servant": Role.LOYAL_SERVANT,
    "Loyal Servant": Role.LOYAL_SERVANT,
    "Minion": Role.MINION,
}

# Distinct character voices matching player personalities
SEAT_VOICES: Dict[int, str] = {
    0: "chloe",    # Merlin (warm, insightful female guidance)
    1: "oliver",   # Assassin (composed, calculating male strategist)
    2: "jake",     # Servant 1 (high-energy, proactive male loyalist)
    3: "eleanor",  # Servant 2 (poised, articulate female analyst)
    4: "marcus",   # Minion (deep, authoritative male bluffer)
}


class VoiceReplayRunner:
    """Plays back a recorded JSONL game log through Boson AI Higgs TTS 3."""

    def __init__(self, tts_client: HiggsTTSClient):
        self.tts = tts_client

    async def replay_game(
        self,
        jsonl_path: str,
        filter_quest: Optional[int] = None,
        max_utterances: Optional[int] = None,
    ):
        path = Path(jsonl_path)
        if not path.exists():
            print(f"[Error] File not found: {jsonl_path}")
            return

        with open(path, "r", encoding="utf-8") as f:
            events = [json.loads(line) for line in f if line.strip()]

        # 1. Parse game_start to establish player roles and seats
        start_event = next((e for e in events if e.get("type") == "game_start"), None)
        if not start_event:
            print("[Error] No game_start event found in transcript.")
            return

        seats_data = start_event["data"]["seats"]
        roles: Dict[int, Role] = {}
        for s in seats_data:
            seat_num = s["seat"]
            role_str = s.get("role", "Servant")
            roles[seat_num] = ROLE_MAP.get(role_str, Role.LOYAL_SERVANT)

        print("\n" + "=" * 65)
        print("BOSON AI VOICE REENACTMENT: HISTORICAL LLM AVALON GAME")
        print("=" * 65)
        print(f"Log File: {path.name}")
        print("Table Roster:")
        for seat, role in sorted(roles.items()):
            side = "Good" if role in [Role.MERLIN, Role.LOYAL_SERVANT] else "Evil"
            voice = SEAT_VOICES.get(seat, "default")
            print(f"  Seat {seat}: {ROLE_NAMES[role]:<14} ({side:<4}) -> Voice: '{voice}'")
        print("=" * 65 + "\n")

        # 2. Iterate through events and reenact discussions and actions
        utterance_count = 0
        last_quest_result = None
        quest_results = []
        current_quest = 0

        for event in events:
            ev_type = event.get("type")
            d = event.get("data", {})

            if ev_type == "discussion":
                quest = d.get("quest", current_quest)
                current_quest = quest
                if filter_quest is not None and (quest + 1) != filter_quest:
                    continue

                if max_utterances is not None and utterance_count >= max_utterances:
                    print(f"\n[Limit reached] Replayed {max_utterances} utterances.")
                    break

                seat = d.get("seat", 0)
                text = d.get("text", "")
                round_num = d.get("round", 0)
                role = roles.get(seat, Role.LOYAL_SERVANT)
                is_leader = d.get("is_leader", False)
                voice = SEAT_VOICES.get(seat, "default")

                # Derive context-driven emotion & prosody
                delivery = GameStateEmotionMapper.get_delivery_for_utterance(
                    seat=seat,
                    role=role,
                    turn=quest,
                    round_num=round_num,
                    last_quest_result=last_quest_result,
                    quest_results=quest_results,
                    is_hammer_round=(round_num >= 4),
                    recent_rejections=round_num,
                )

                # Format and compile tags safely
                intent = DeliveryIntent(
                    emotion=delivery.emotion,
                    prosody=delivery.prosody,
                    style=delivery.style,
                    sfx=delivery.sfx,
                )
                compiled_text = SpeechIntentCompiler.compile_utterance(text, intent)

                leader_tag = " (Leader)" if is_leader else ""
                print(f"[Q{quest+1} R{round_num+1}] Player {seat} ({ROLE_NAMES[role]}){leader_tag}:")
                print(f"  Text: \"{text}\"")
                print(f"  Boson Tags: [Voice: {voice} | Emotion: {delivery.emotion} | Prosody: {delivery.prosody}]")

                # Synthesize and play through Boson TTS
                save_file = self.tts.cache_dir / f"replay_q{quest+1}_r{round_num+1}_p{seat}_{utterance_count}.wav"
                await self.tts.synthesize(
                    text=compiled_text,
                    voice=voice,
                    seat=seat,
                    save_path=save_file,
                )
                if self.tts.play_audio and save_file.exists():
                    self.tts.play_wav_file(save_file)
                utterance_count += 1
                await asyncio.sleep(0.3)

            elif ev_type == "team_proposed":
                quest = d.get("quest", current_quest)
                if filter_quest is not None and (quest + 1) != filter_quest:
                    continue
                leader = d.get("leader")
                team = d.get("team")
                print(f"\n>> [Proposal] Leader Player {leader} proposes Team {team} for Quest {quest+1}")

            elif ev_type == "team_result":
                quest = d.get("quest", current_quest)
                if filter_quest is not None and (quest + 1) != filter_quest:
                    continue
                approved = d.get("approved", False)
                votes = d.get("votes", {})
                vote_str = ", ".join(f"P{p}:{'Y' if v else 'N'}" for p, v in votes.items())
                status = "APPROVED" if approved else "REJECTED"
                print(f">> [Vote Result] Team {status} ({vote_str})\n")

            elif ev_type == "quest_result":
                quest = d.get("quest", current_quest)
                if filter_quest is not None and (quest + 1) != filter_quest:
                    continue
                success = d.get("succeeded", False)
                num_fails = d.get("num_fails", 0)
                quest_results.append(success)
                last_quest_result = {"success": success, "num_fails": num_fails}
                res_str = "SUCCEEDED" if success else "FAILED"
                print(f"\n{'*'*50}")
                print(f">> [QUEST {quest+1} OUTCOME] Mission {res_str} ({num_fails} Fail votes)")
                print(f"{'*'*50}\n")

            elif ev_type == "game_end":
                winner = d.get("winner", "Unknown").upper()
                reason = d.get("win_reason", "")
                print("\n" + "#" * 60)
                print(f"GAME COMPLETED: {winner} TEAM VICTORY!")
                if reason:
                    print(f"Reason: {reason}")
                print("#" * 60)

        budget = global_budget_tracker.get_summary()
        print(f"\nReplay Finished. Boson API Calls: {budget['total_calls']}/{budget['max_calls']} (Remaining: {budget['remaining']})")


async def main():
    if len(sys.argv) < 2:
        print("Usage: python -m avalon.voice_replay <path_to_game.jsonl> [--mute] [--quest N] [--max-lines N]")
        sys.exit(1)

    jsonl_file = sys.argv[1]
    enable_playback = "--mute" not in sys.argv

    filter_quest = None
    if "--quest" in sys.argv:
        try:
            q_idx = sys.argv.index("--quest")
            filter_quest = int(sys.argv[q_idx + 1])
        except (IndexError, ValueError):
            filter_quest = None

    max_lines = None
    if "--max-lines" in sys.argv:
        try:
            m_idx = sys.argv.index("--max-lines")
            max_lines = int(sys.argv[m_idx + 1])
        except (IndexError, ValueError):
            max_lines = None

    tts_client = HiggsTTSClient(play_audio=enable_playback)
    runner = VoiceReplayRunner(tts_client)
    await runner.replay_game(
        jsonl_path=jsonl_file,
        filter_quest=filter_quest,
        max_utterances=max_lines,
    )


if __name__ == "__main__":
    asyncio.run(main())
