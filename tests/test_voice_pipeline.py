"""
Unit and integration tests for Boson Voice Pipeline components:
- BosonBudgetTracker
- GameStateEmotionMapper
- AudioPipeline
- HumanVoiceAgent
"""

import os
import json
import asyncio
import tempfile
from pathlib import Path
import pytest

from avalon.engine import Role, AvalonEngine
from speech.budget import BosonBudgetTracker
from speech.emotion_mapper import GameStateEmotionMapper, GameStateDelivery
from speech.boson_tts import HiggsTTSClient
from speech.audio_pipeline import AudioPipeline
from speech.human_agent import HumanVoiceAgent


def test_budget_tracker_limits_and_records():
    with tempfile.TemporaryDirectory() as tmpdir:
        log_file = Path(tmpdir) / "test_budget.json"
        tracker = BosonBudgetTracker(max_calls=3, log_file=log_file)

        assert tracker.can_call() is True
        assert tracker.remaining_budget() == 3

        tracker.record_call(endpoint="/v1/audio/speech", voice="marcus", text_length=50, status_code=200, byte_size=1000)
        assert tracker.remaining_budget() == 2

        tracker.record_call(endpoint="/v1/audio/speech", voice="eleanor", text_length=40, status_code=200, byte_size=1200)
        tracker.record_call(endpoint="/v1/audio/speech", voice="jake", text_length=30, status_code=200, byte_size=800)

        assert tracker.can_call() is False
        assert tracker.remaining_budget() == 0

        # Reload from disk and verify persistence
        tracker_reloaded = BosonBudgetTracker(max_calls=3, log_file=log_file)
        assert tracker_reloaded.can_call() is False
        assert tracker_reloaded.calls_count == 3


def test_emotion_mapper_hammer_round():
    # Loyal Servant during hammer round (round 4)
    delivery = GameStateEmotionMapper.get_delivery_for_utterance(
        seat=1,
        role=Role.LOYAL_SERVANT,
        turn=2,
        round_num=4,
        is_hammer_round=True,
    )
    assert delivery.emotion == "fear"
    assert delivery.style == "shouting"
    assert "speed_very_fast" in delivery.prosody

    # Merlin during hammer round
    merlin_delivery = GameStateEmotionMapper.get_delivery_for_utterance(
        seat=4,
        role=Role.MERLIN,
        turn=2,
        round_num=4,
        is_hammer_round=True,
    )
    assert merlin_delivery.style == "whispering"
    assert merlin_delivery.sfx == "sigh"


def test_emotion_mapper_quest_failure():
    # Loyal servant reacts with anger to failed quest
    failed_result = {"turn": 0, "team": [0, 1], "success": False, "num_fails": 1}
    delivery = GameStateEmotionMapper.get_delivery_for_utterance(
        seat=2,
        role=Role.LOYAL_SERVANT,
        turn=1,
        round_num=0,
        last_quest_result=failed_result,
        quest_results=[False],
    )
    assert delivery.emotion == "anger"

    # 2 fails -> shouting anger
    double_fail = {"turn": 0, "team": [0, 1, 2], "success": False, "num_fails": 2}
    delivery_severe = GameStateEmotionMapper.get_delivery_for_utterance(
        seat=1,
        role=Role.LOYAL_SERVANT,
        turn=1,
        round_num=0,
        last_quest_result=double_fail,
        quest_results=[False],
    )
    assert delivery_severe.emotion == "anger"
    assert delivery_severe.style == "shouting"


def test_emotion_mapper_quest_success():
    success_result = {"turn": 0, "team": [1, 2], "success": True, "num_fails": 0}
    delivery = GameStateEmotionMapper.get_delivery_for_utterance(
        seat=1,
        role=Role.LOYAL_SERVANT,
        turn=1,
        round_num=0,
        last_quest_result=success_result,
        quest_results=[True],
    )
    assert delivery.emotion in ("elation", "enthusiasm")

    merlin_delivery = GameStateEmotionMapper.get_delivery_for_utterance(
        seat=4,
        role=Role.MERLIN,
        turn=1,
        round_num=0,
        last_quest_result=success_result,
        quest_results=[True],
    )
    assert merlin_delivery.emotion == "relief"
    assert merlin_delivery.style == "whispering"


def test_delivery_prefix_formatting():
    delivery = GameStateDelivery(
        emotion="anger",
        style="shouting",
        prosody=["speed_fast", "expressive_high"],
        sfx="sigh",
    )
    tags = delivery.to_prefix_tags()
    assert "<|style:shouting|>" in tags
    assert "<|emotion:anger|>" in tags
    assert "<|prosody:speed_fast|>" in tags
    assert "<|prosody:expressive_high|>" in tags
    assert "<|sfx:sigh|>" in tags

    formatted = delivery.format_utterance("I don't trust Player 0!")
    assert formatted.startswith("<|style:shouting|>")
    assert formatted.endswith("I don't trust Player 0!")

    # Existing tags are not duplicated
    pre_tagged = "<|emotion:anger|>Already tagged"
    assert delivery.format_utterance(pre_tagged) == pre_tagged

    # Legacy tag auto-sanitization test
    legacy_delivery = GameStateDelivery(
        emotion="anger",
        prosody=["expressiveness_high"],
    )
    legacy_tags = legacy_delivery.to_prefix_tags()
    assert "<|prosody:expressive_high|>" in legacy_tags


def test_audio_pipeline_offline_fallback():
    async def _run():
        with tempfile.TemporaryDirectory() as tmpdir:
            # Client without API key generates offline tone wavs
            tts_client = HiggsTTSClient(api_key="", cache_dir=tmpdir, play_audio=False)
            pipeline = AudioPipeline(tts_client=tts_client, max_concurrent_synthesis=2)

            await pipeline.start()
            try:
                delivery = GameStateDelivery(emotion="determination")
                turn_0 = pipeline.enqueue_turn(seat=0, text="Hello table", turn=0, round_num=0, delivery=delivery)
                turn_1 = pipeline.enqueue_turn(seat=1, text="I am innocent", turn=0, round_num=0, delivery=delivery)

                await pipeline.wait_until_idle()

                assert turn_0.audio_path is not None
                assert turn_0.audio_path.exists()
                assert turn_1.audio_path is not None
                assert turn_1.audio_path.exists()
            finally:
                await pipeline.stop()

    asyncio.run(_run())


def test_human_agent_initialization():
    agent = HumanVoiceAgent(player_id=1, role=Role.LOYAL_SERVANT, use_mic=False)
    assert agent.player_id == 1
    assert agent.role == Role.LOYAL_SERVANT
    assert agent.side is True
    assert agent.condition == "human"
    assert agent.is_human is True


def test_narrator_voice_and_synthesis():
    async def _run():
        with tempfile.TemporaryDirectory() as tmpdir:
            tts_client = HiggsTTSClient(api_key="", cache_dir=tmpdir, play_audio=False)
            assert tts_client.get_voice_for_seat(-1) == "nora"

            wav_path = await tts_client.speak_narrator(
                text="The proposed team is APPROVED.",
                tag="test_vote",
                turn=0,
                round_num=0,
            )
            assert wav_path is not None
            assert wav_path.exists()
            assert "narrator" in wav_path.name

    asyncio.run(_run())


def test_runner_helpers_and_human_bypass():
    from avalon.runner import AvalonGameRunner
    from avalon.agents import HeuristicAgent

    agents = {
        0: HumanVoiceAgent(player_id=0, role=Role.LOYAL_SERVANT, use_mic=False),
        1: HeuristicAgent(player_id=1, role=Role.LOYAL_SERVANT, condition="belief_graph"),
    }
    runner = AvalonGameRunner(agents=agents, verbose=False)

    # Human detection
    assert runner._is_human(0) is True
    assert runner._is_human(1) is False
    assert runner._is_human(99) is False

    # English team name formatting
    assert runner._format_team_names([0]) == "Player 0"
    assert runner._format_team_names([0, 1]) == "Player 0 and Player 1"
    assert runner._format_team_names([0, 2, 4]) == "Player 0, Player 2, and Player 4"

