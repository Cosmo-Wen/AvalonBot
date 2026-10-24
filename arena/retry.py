import asyncio
import random
from typing import Awaitable, Callable, Optional, TypeVar

T = TypeVar("T")

# matched against class names in the exception's MRO, so we don't need to import every SDK
TRANSIENT_NAME_HINTS = (
    "RateLimit", "Timeout", "APIConnection", "ConnectionError", "InternalServer",
    "ServiceUnavailable", "Overloaded", "APIStatusError", "ServerError", "ClientOSError",
    "ServerDisconnected", "Transient",
)


def is_transient(exc: BaseException) -> bool:
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError, ConnectionError)):
        return True
    names = [cls.__name__ for cls in type(exc).__mro__]
    return any(hint in name for name in names for hint in TRANSIENT_NAME_HINTS)


def backoff_delay(attempt: int, base: float, cap: float, rng: Optional[random.Random] = None) -> float:
    r"""Full-jitter exponential backoff: uniform(0, min(cap, base * 2**attempt))."""
    rng = rng or random
    return rng.uniform(0, min(cap, base * (2 ** attempt)))


async def retry_async(
    fn: Callable[[], Awaitable[T]],
    max_retries: int,
    base: float,
    cap: float,
    should_retry: Callable[[BaseException], bool] = is_transient,
    on_retry: Optional[Callable[[int, BaseException, float], None]] = None,
) -> T:
    attempt = 0
    while True:
        try:
            return await fn()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            if attempt >= max_retries or not should_retry(e):
                raise
            delay = backoff_delay(attempt, base, cap)
            if on_retry is not None:
                on_retry(attempt, e, delay)
            await asyncio.sleep(delay)
            attempt += 1
