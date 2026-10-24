"""
Asynchronous Audio Pipelining Orchestrator for Avalon Bot.

Eliminates conversational dead-air latency between AI players.
While Player N is playing their synthesized line on the speaker,
Player N+1's speech is pre-synthesized concurrently in the background.

Architecture:
- PlaybackQueue: Sequential audio player running on worker thread.
- PreSynthesisWorker: Eagerly downloads audio for upcoming speaker turns.
- Fallback & Budget-Aware: Automatically delegates to offline tones if budget is exhausted.
"""

import asyncio
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any, Callable
from dataclasses import dataclass

from speech.boson_tts import HiggsTTSClient
from speech.budget import global_budget_tracker
from speech.emotion_mapper import GameStateDelivery, GameStateEmotionMapper


@dataclass
class SpokenTurn:
    seat: int
    text: str
    turn: int
    round_num: int
    delivery: GameStateDelivery
    save_path: Path
    ready_event: asyncio.Event
    audio_path: Optional[Path] = None
    error: Optional[str] = None


class AudioPipeline:
    """
    Pipelined audio generation and playback system.
    """

    def __init__(
        self,
        tts_client: HiggsTTSClient,
        max_concurrent_synthesis: int = 2,
    ):
        self.tts = tts_client
        self.max_concurrent_synthesis = max_concurrent_synthesis
        self.queue: asyncio.Queue[SpokenTurn] = asyncio.Queue()
        self.semaphore = asyncio.Semaphore(max_concurrent_synthesis)
        self.is_running = False
        self._playback_task: Optional[asyncio.Task] = None
        self._pre_synthesis_tasks: List[asyncio.Task] = []

    async def start(self):
        """Starts the background playback loop."""
        if not self.is_running:
            self.is_running = True
            self._playback_task = asyncio.create_task(self._playback_worker())

    async def stop(self):
        """Flushes and halts pipeline workers."""
        self.is_running = False
        if self._playback_task:
            self._playback_task.cancel()
            try:
                await self._playback_task
            except asyncio.CancelledError:
                pass
        for t in self._pre_synthesis_tasks:
            t.cancel()
        self._pre_synthesis_tasks.clear()

    async def _playback_worker(self):
        """Consumes ready SpokenTurns and plays them in strict chronological sequence."""
        while self.is_running:
            try:
                turn_item = await self.queue.get()
                # Wait until synthesis of this specific clip completes
                await turn_item.ready_event.wait()

                if turn_item.audio_path and turn_item.audio_path.exists():
                    print(f"  [Pipeline Playback] Playing Player {turn_item.seat} utterance...")
                    loop = asyncio.get_running_loop()
                    await loop.run_in_executor(None, self.tts.play_wav_file, turn_item.audio_path)

                self.queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[Pipeline Playback Error] {e}")

    async def _synthesize_task(self, item: SpokenTurn):
        """Fetches/synthesizes audio for a SpokenTurn within concurrency limits."""
        async with self.semaphore:
            try:
                # Prepend dynamic delivery tags
                tagged_text = item.delivery.format_utterance(item.text)
                voice = self.tts.get_voice_for_seat(item.seat)

                audio_bytes = await self.tts.synthesize(
                    text=tagged_text,
                    voice=voice,
                    save_path=item.save_path,
                    seat=item.seat,
                )
                if item.save_path.exists():
                    item.audio_path = item.save_path
            except Exception as e:
                item.error = str(e)
            finally:
                item.ready_event.set()

    def enqueue_turn(
        self,
        seat: int,
        text: str,
        turn: int,
        round_num: int,
        delivery: GameStateDelivery,
    ) -> SpokenTurn:
        """
        Enqueues an utterance into the pipeline. Immediately triggers background synthesis
        so it is ready when the playback worker reaches it.
        """
        save_file = self.tts.cache_dir / f"turn_{turn + 1}_round_{round_num + 1}_seat_{seat}.wav"
        spoken_turn = SpokenTurn(
            seat=seat,
            text=text,
            turn=turn,
            round_num=round_num,
            delivery=delivery,
            save_path=save_file,
            ready_event=asyncio.Event(),
        )

        # Enqueue for playback
        self.queue.put_nowait(spoken_turn)

        # Launch concurrent background synthesis task immediately
        task = asyncio.create_task(self._synthesize_task(spoken_turn))
        self._pre_synthesis_tasks.append(task)
        # Clean up completed tasks
        self._pre_synthesis_tasks = [t for t in self._pre_synthesis_tasks if not t.done()]

        return spoken_turn

    async def wait_until_idle(self):
        """Awaits playback of all currently enqueued spoken turns."""
        await self.queue.join()
