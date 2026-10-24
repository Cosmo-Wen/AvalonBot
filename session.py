from typing import Callable, List, Optional

from src.server.task import Session
from src.typings import AgentOutput, ChatHistoryItem

from .backends import Completion, Transcript
from .retry import retry_async


def brevity_instruction(max_words: Optional[int]) -> str:
    if not max_words:
        return ""
    return (f"Keep every reply under {max_words} words. In discussion, speak one or two short sentences. "
            "When asked for a decision, give it in the requested answer format with at most one short "
            "sentence of reasoning. Do not think step by step at length.")


class ArenaSession(Session):
    r"""Shared session for all seats in one game.

    `MultiAgentProxy` swaps `self.history` per seat; this class routes each `action()` to the
    current seat's backend and returns an `AgentOutput`, which is what `AvalonSessionWrapper` expects.
    """

    def __init__(
        self,
        backends: List,
        max_retries: int,
        backoff_base_s: float,
        backoff_max_s: float,
        on_event: Optional[Callable[..., None]] = None,
        reply_max_words: Optional[int] = None,
    ):
        super().__init__()
        self.backends = backends
        self.proxy = None  # set after the proxy is built
        self.max_retries = max_retries
        self.backoff_base_s = backoff_base_s
        self.backoff_max_s = backoff_max_s
        self.on_event = on_event or (lambda type, **data: None)
        self.brevity = brevity_instruction(reply_max_words)

    async def call(self, backend, seat: int, system: str, transcript: Transcript) -> Completion:
        r"""One completion with backoff on transient failures (also used by the search planner)."""
        def on_retry(attempt, exc, delay):
            self.on_event("retry", scope="llm_call", seat=seat, attempt=attempt,
                          error=f"{type(exc).__name__}: {exc}", delay_s=delay)

        if self.brevity:
            system = f"{system}\n\n{self.brevity}" if system else self.brevity
        return await retry_async(
            lambda: backend.complete(system, transcript),
            max_retries=self.max_retries,
            base=self.backoff_base_s,
            cap=self.backoff_max_s,
            on_retry=on_retry,
        )

    async def action(self, *injection) -> AgentOutput:
        self.inject(list(injection))
        seat = self.proxy.current_agent if self.proxy is not None else 0
        messages = self.filter_messages(self.history)
        # the first message is the game instruction; it becomes the system prompt
        system = messages[0].content
        transcript = [(m.role, m.content) for m in messages[1:]]
        if not transcript:
            transcript = [("user", system)]

        c = await self.call(self.backends[seat], seat, system, transcript)
        self.on_event("llm_call", seat=seat, source="seat", prompt=transcript[-1][1], response=c.text,
                      model=c.model, input_tokens=c.input_tokens, output_tokens=c.output_tokens,
                      cost_usd=c.cost_usd, latency_s=c.duration_s)
        self.history.append(ChatHistoryItem(role="agent", content=c.text))
        return AgentOutput(content=c.text)
