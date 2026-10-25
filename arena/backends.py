import asyncio
import json
import os
import random
import re
import shutil
import tempfile
import time
import uuid
import weakref
from dataclasses import dataclass
from typing import Awaitable, Callable, List, Optional, Tuple

from .config import ArenaConfig, SeatSpec

Transcript = List[Tuple[str, str]]  # (role, text) with role in {"user", "agent"}


class BackendError(Exception):
    r"""A model call failed. Non-transient unless a subclass says otherwise."""


class TransientBackendError(BackendError):
    r"""Timeouts, overload, 5xx: retried with backoff."""


class UsageLimitReached(BackendError):
    r"""The subscription's usage window is exhausted: pause the run and resume later."""


class FatalBackendError(BackendError):
    r"""Retrying cannot help (not logged in, CLI missing, bad model): abort the whole run."""


class NotLoggedIn(FatalBackendError):
    pass


@dataclass
class Completion:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    model: str = ""
    duration_s: float = 0.0


PLAYER_FRAMING = (
    "You are playing a text-based game of The Resistance: Avalon. The user message contains the "
    "conversation so far: lines from the game moderator are under [Game] headings and your own earlier "
    "replies are under [You] headings. Reply only with your next message to the moderator, in plain text, "
    "following any answer template it asks for."
)


def render_transcript(transcript: Transcript) -> str:
    parts = []
    for role, text in transcript:
        parts.append(f"[{'You' if role == 'agent' else 'Game'}]\n{text}")
    return "\n\n".join(parts)


def strip_echoed_label(text: str) -> str:
    r"""Models sometimes start a reply with the transcript's own "[You]" heading; drop it."""
    stripped = text.lstrip()
    if stripped.startswith("[You]"):
        return stripped[len("[You]"):].lstrip()
    return text


# ---------------------------------------------------------------- claude_cli

AUTH_PATTERNS = re.compile(r"not logged in|please run /login|/login|authenticat|invalid api key|oauth token", re.I)
USAGE_PATTERNS = re.compile(r"usage limit|limit reached|limit will reset|resets at|out of (extra )?usage|weekly limit", re.I)
MODEL_PATTERNS = re.compile(r"issue with the selected model|model .* not (found|available)", re.I)
TRANSIENT_PATTERNS = re.compile(r"overloaded|timed? ?out|connection|temporarily|try again|internal server error", re.I)


def classify_cli_failure(status: Optional[int], message: str) -> BackendError:
    r"""Map a failed `claude -p` call to an error class from its api_error_status and message."""
    if status in (401, 403) or AUTH_PATTERNS.search(message):
        return NotLoggedIn(f"Claude Code is not logged in ({message.strip()[:200]}). Run `claude` and log in, then retry.")
    if USAGE_PATTERNS.search(message):
        return UsageLimitReached(message.strip()[:300])
    if status == 404 or MODEL_PATTERNS.search(message):
        return FatalBackendError(f"model unavailable: {message.strip()[:300]}")
    if status == 429 or (status is not None and status >= 500) or TRANSIENT_PATTERNS.search(message):
        return TransientBackendError(f"[{status}] {message.strip()[:300]}")
    return BackendError(f"[{status}] {message.strip()[:300]}")


def resolve_claude_bin(configured: Optional[str]) -> str:
    path = configured or shutil.which("claude")
    if not path:
        raise FatalBackendError("`claude` (Claude Code CLI) not found on PATH. Install Claude Code and run `claude` once to log in.")
    return path


# per event loop (weakly keyed, so a finished loop's objects are never handed to a new one)
_cli_semaphores = weakref.WeakKeyDictionary()


def _cli_semaphore(limit: int) -> asyncio.Semaphore:
    # one cap per event loop on concurrent `claude` processes, shared by all games and seats
    per_loop = _cli_semaphores.setdefault(asyncio.get_running_loop(), {})
    if limit not in per_loop:
        per_loop[limit] = asyncio.Semaphore(limit)
    return per_loop[limit]


class ClaudeCLIBackend:
    r"""Runs each completion through `claude -p` (Claude Code headless mode) on the user's own login.

    Tools, MCP servers and settings (hooks, plugins) are disabled, and the process runs in an empty
    temp dir so no project files or CLAUDE.md are loaded. The prompt goes over stdin and the system
    prompt through a file, which avoids command-line length limits on Windows.
    """

    def __init__(self, model: str, cfg: ArenaConfig, effort: Optional[str] = None):
        self.model = model
        self.effort = effort
        self.claude_bin = resolve_claude_bin(cfg.claude_bin)
        self.timeout_s = cfg.llm_timeout_s
        self.max_parallel = cfg.cli_max_parallel
        self._tmp = tempfile.TemporaryDirectory(prefix="avalon-arena-")

    def command(self, system_file: str) -> List[str]:
        cmd = [
            self.claude_bin, "-p",
            "--model", self.model,
            "--tools", "",
            "--system-prompt-file", system_file,
            "--output-format", "json",
            "--no-session-persistence",
            "--setting-sources", "",
            "--strict-mcp-config",
        ]
        if self.effort:
            cmd += ["--effort", self.effort]
        return cmd

    async def complete(self, system: str, transcript: Transcript) -> Completion:
        system_file = os.path.join(self._tmp.name, f"system-{uuid.uuid4().hex}.txt")
        with open(system_file, "w", encoding="utf-8") as f:
            f.write(PLAYER_FRAMING + "\n\n" + system)
        prompt = render_transcript(transcript).encode("utf-8")
        try:
            async with _cli_semaphore(self.max_parallel):
                start = time.monotonic()
                proc = await asyncio.create_subprocess_exec(
                    *self.command(system_file),
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=self._tmp.name,
                )
                try:
                    stdout, stderr = await asyncio.wait_for(proc.communicate(prompt), timeout=self.timeout_s)
                except BaseException:
                    # timeout or cancellation: don't leave the child running
                    if proc.returncode is None:
                        proc.kill()
                        await proc.wait()
                    raise
                duration = time.monotonic() - start
        except asyncio.TimeoutError:
            raise TransientBackendError(f"claude -p timed out after {self.timeout_s}s")
        except FileNotFoundError:
            raise FatalBackendError(f"could not run {self.claude_bin!r}; is Claude Code installed?")
        finally:
            try:
                os.remove(system_file)
            except OSError:
                pass
        return self.parse(proc.returncode, stdout.decode("utf-8", "replace"), stderr.decode("utf-8", "replace"), duration)

    def parse(self, returncode: int, stdout: str, stderr: str, duration: float) -> Completion:
        try:
            data = json.loads(stdout)
        except json.JSONDecodeError:
            raise classify_cli_failure(None, f"exit {returncode}: {stderr or stdout}")
        if data.get("is_error") or returncode != 0:
            message = f"{data.get('result') or ''} {stderr}"
            raise classify_cli_failure(data.get("api_error_status"), message)
        usage = data.get("usage") or {}
        model_usage = data.get("modelUsage") or {}
        return Completion(
            text=strip_echoed_label(data.get("result") or ""),
            input_tokens=sum(int(usage.get(k) or 0) for k in
                             ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")),
            output_tokens=int(usage.get("output_tokens") or 0),
            cost_usd=float(data.get("total_cost_usd") or 0.0),
            model=next(iter(model_usage), self.model),
            duration_s=round(duration, 3),
        )

    def close(self):
        self._tmp.cleanup()


# ---------------------------------------------------------------- anthropic (API key)

class ModelRefusal(BackendError):
    r"""The model declined (stop_reason "refusal"), after any server-side fallback also declined."""


API_MODEL_ALIASES = {"haiku": "claude-haiku-5-5", "sonnet": "claude-sonnet-5-5", "opus": "claude-opus-5-5"}
# models that accept server-side refusal fallback in its `fallbacks: "default"` form (not Haiku)
SERVER_FALLBACK_MODELS = {"claude-opus-5-5", "claude-opus-5", "claude-fable-5-1", "claude-fable-5", "claude-sonnet-5-5"}
SERVER_FALLBACK_BETA = "server-side-fallback-2026-07-01"
# USD per million tokens (input, output) for the cost estimate in logs; cache writes 1.25x, reads 0.1x
API_PRICES = {
    "claude-opus-5-5": (4.0, 20.0), "claude-opus-5": (5.0, 25.0), "claude-sonnet-5-5": (2.0, 10.0),
    "claude-sonnet-5": (2.0, 10.0), "claude-haiku-5-5": (0.10, 0.50), "claude-fable-5-1": (10.0, 50.0),
}

_api_clients = weakref.WeakKeyDictionary()


def _api_client(timeout_s: float):
    try:
        import anthropic
    except ImportError:
        raise FatalBackendError("provider `anthropic` needs the SDK: pip install 'anthropic>=2.0.0'")
    per_loop = _api_clients.setdefault(asyncio.get_running_loop(), {})
    if timeout_s not in per_loop:
        # credentials resolve as usual: ANTHROPIC_API_KEY, ANTHROPIC_AUTH_TOKEN, or an `ant auth login` profile.
        # max_retries=0: transient failures are retried (and logged) by ArenaSession instead.
        per_loop[timeout_s] = anthropic.AsyncAnthropic(max_retries=0, timeout=timeout_s)
    return per_loop[timeout_s]


def classify_api_error(exc) -> BackendError:
    import anthropic

    message = f"{type(exc).__name__}: {getattr(exc, 'message', exc)}"
    if isinstance(exc, (anthropic.AuthenticationError, anthropic.PermissionDeniedError)):
        return NotLoggedIn(f"API key rejected ({message}). Set ANTHROPIC_API_KEY to a valid key.")
    if isinstance(exc, anthropic.NotFoundError):
        return FatalBackendError(f"model unavailable: {message}")
    if isinstance(exc, (anthropic.RateLimitError, anthropic.InternalServerError, anthropic.APIConnectionError)):
        return TransientBackendError(message)
    if isinstance(exc, anthropic.APIStatusError):
        if exc.status_code == 402:  # billing_error: out of credits
            return UsageLimitReached(f"API credits exhausted ({message})")
        if exc.status_code >= 500:
            return TransientBackendError(message)
    return BackendError(message)


class AnthropicBackend:
    r"""Calls the Claude API with the official SDK, for anyone who has an API key.

    No sampling parameters (rejected since API version 2026-10-21), an explicit effort level,
    automatic prompt caching (each seat's transcript only grows), and server-side refusal fallback
    on the models that support it.
    """

    def __init__(self, model: str, cfg: ArenaConfig, effort: Optional[str]):
        self.model = API_MODEL_ALIASES.get(model, model)
        self.effort = effort
        self.timeout_s = cfg.llm_timeout_s
        self.max_tokens = cfg.api_max_tokens

    def request(self, system: str, transcript: Transcript) -> dict:
        messages = [{"role": "assistant" if role == "agent" else "user", "content": text} for role, text in transcript]
        if not messages or messages[0]["role"] != "user":
            # the history window can start on one of our own replies; the API needs a user turn first
            messages.insert(0, {"role": "user", "content": "(earlier conversation omitted)"})
        params = dict(model=self.model, max_tokens=self.max_tokens, messages=messages,
                      cache_control={"type": "ephemeral"})
        if system:
            params["system"] = system
        if self.effort:
            params["output_config"] = {"effort": self.effort}
        if self.model in SERVER_FALLBACK_MODELS:
            params["betas"] = [SERVER_FALLBACK_BETA]
            params["fallbacks"] = "default"
        return params

    async def complete(self, system: str, transcript: Transcript) -> Completion:
        import anthropic

        start = time.monotonic()
        try:
            client = _api_client(self.timeout_s)  # resolving credentials can fail here
            response = await client.beta.messages.create(**self.request(system, transcript))
        except anthropic.APIError as e:
            raise classify_api_error(e) from e
        except anthropic.AnthropicError as e:  # e.g. no credentials configured
            raise NotLoggedIn(f"{type(e).__name__}: {e}. Set ANTHROPIC_API_KEY.") from e
        if response.stop_reason == "refusal":
            details = getattr(response, "stop_details", None)
            raise ModelRefusal(f"model declined (category: {getattr(details, 'category', None)})")
        usage = response.usage
        written = usage.cache_creation_input_tokens or 0
        read = usage.cache_read_input_tokens or 0
        price_in, price_out = API_PRICES.get(response.model, (0.0, 0.0))
        cost = (usage.input_tokens * price_in + written * price_in * 1.25 + read * price_in * 0.1
                + usage.output_tokens * price_out) / 1e6
        return Completion(
            text="".join(b.text for b in response.content if b.type == "text"),
            input_tokens=usage.input_tokens + written + read,
            output_tokens=usage.output_tokens,
            cost_usd=round(cost, 6),
            model=response.model,
            duration_s=round(time.monotonic() - start, 3),
        )

    def close(self):
        pass


# ---------------------------------------------------------------- openai (any OpenAI-compatible endpoint)

def load_openai_credentials(cfg: ArenaConfig) -> Tuple[str, Optional[str]]:
    r"""(api_key, base_url) from the standard OpenAI variables; the key is never printed.

    OPENAI_API_KEY is required. The base URL is `cfg.openai_base_url`, else OPENAI_BASE_URL, else
    the SDK default (api.openai.com). The CLI loads both from a local `.env` (see README).
    """
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise NotLoggedIn("no OpenAI API key: set OPENAI_API_KEY (for example in a local .env file)")
    return key, cfg.openai_base_url or os.environ.get("OPENAI_BASE_URL")


_openai_clients = weakref.WeakKeyDictionary()


def _openai_client(cfg: ArenaConfig):
    try:
        import openai
    except ImportError:
        raise FatalBackendError("provider `openai` needs the SDK: pip install 'openai>=1.66,<2'")
    key, base_url = load_openai_credentials(cfg)
    per_loop = _openai_clients.setdefault(asyncio.get_running_loop(), {})
    cache_key = (base_url, cfg.llm_timeout_s, hash(key))
    if cache_key not in per_loop:
        # max_retries=0: ArenaSession decides what is safe to retry (see classify_openai_error)
        per_loop[cache_key] = openai.AsyncOpenAI(api_key=key, base_url=base_url, max_retries=0,
                                                 timeout=cfg.llm_timeout_s)
    return per_loop[cache_key]


QUOTA_PATTERNS = re.compile(r"insufficient_quota|quota|allowance|expired|usage limit", re.I)
KEY_PATTERN = re.compile(r"sk-[A-Za-z0-9_\-]{6,}")


def redact_keys(text: str) -> str:
    r"""Mask anything shaped like an API key; error text from a server ends up in the event logs."""
    return KEY_PATTERN.sub("sk-[redacted]", text)


def classify_openai_error(exc) -> BackendError:
    r"""Only errors where the request was surely not accepted are retryable.

    Metered resellers bill accepted requests even if the response is lost,
    so timeouts and 5xx are not retried: a retry could be billed twice.
    """
    import openai

    body = getattr(exc, "body", None)
    code = body.get("code") if isinstance(body, dict) else None
    message = redact_keys(f"{type(exc).__name__}: {getattr(exc, 'message', exc)}")
    if isinstance(exc, (openai.AuthenticationError, openai.PermissionDeniedError)):
        if QUOTA_PATTERNS.search(message):
            return UsageLimitReached(f"API key expired or out of allowance ({message})")
        return NotLoggedIn(f"API key rejected ({message}). Check the key and its usage page.")
    if isinstance(exc, openai.NotFoundError):
        return FatalBackendError(f"model or endpoint unavailable: {message}")
    if isinstance(exc, openai.RateLimitError):
        if code == "insufficient_quota" or QUOTA_PATTERNS.search(message):
            return UsageLimitReached(f"API allowance exhausted ({message})")
        return TransientBackendError(message)  # rejected before it ran: safe to retry
    if isinstance(exc, openai.APIStatusError) and exc.status_code == 402:
        return UsageLimitReached(f"API allowance exhausted ({message})")
    return BackendError(message)  # timeouts, connection drops, 5xx, bad requests: not retried


class OpenAIBackend:
    r"""Calls an OpenAI-compatible Responses API (`POST /responses`, `store=False`).

    No sampling parameters are sent. `effort` maps to `reasoning.effort`; set it to null for models
    without reasoning settings.
    """

    def __init__(self, model: str, cfg: ArenaConfig, effort: Optional[str]):
        self.model = model
        self.effort = effort
        self.cfg = cfg

    def request(self, system: str, transcript: Transcript) -> dict:
        params = dict(
            model=self.model,
            input=[{"role": "assistant" if role == "agent" else "user", "content": text}
                   for role, text in transcript],
            store=False,
            max_output_tokens=self.cfg.api_max_tokens,
        )
        if system:
            params["instructions"] = system
        if self.effort:
            params["reasoning"] = {"effort": self.effort}
        return params

    async def complete(self, system: str, transcript: Transcript) -> Completion:
        import openai

        start = time.monotonic()
        client = _openai_client(self.cfg)
        try:
            response = await client.responses.create(**self.request(system, transcript))
        except openai.APIError as e:
            raise classify_openai_error(e) from None  # don't chain: the SDK exception may echo request details
        usage = response.usage
        return Completion(
            text=response.output_text or "",
            input_tokens=getattr(usage, "input_tokens", 0) or 0,
            output_tokens=getattr(usage, "output_tokens", 0) or 0,
            cost_usd=0.0,  # the endpoint's pricing isn't known here; see its usage page
            model=response.model or self.model,
            duration_s=round(time.monotonic() - start, 3),
        )

    def close(self):
        pass


# ---------------------------------------------------------------- fake

class FakeBackend:
    r"""Scripted, offline responder: answers every prompt the arena sends in the format it parses.

    Used to check an install end to end (`run --fake`) and in tests. Decisions are random but seeded.
    """

    def __init__(self, seed: int):
        self.rng = random.Random(seed)
        self.model = "fake"

    async def complete(self, system: str, transcript: Transcript) -> Completion:
        last = transcript[-1][1] if transcript else system
        await asyncio.sleep(0)
        return Completion(text=self.respond(last), model=self.model)

    def respond(self, last: str) -> str:
        if m := re.search(r"Please choose (\d+) players", last):
            team = sorted(self.rng.sample(range(5), int(m.group(1))))
            return f"I will pick TEAM={team}"
        if "what team does the player choose" in last:
            picked = re.findall(r"TEAM=(\[[^\]]*\])", last)
            return "Answer: " + (picked[-1] if picked else "[0, 1]")
        if "approve the team" in last or "support the quest" in last:
            return "Answer: " + self.rng.choice(["Yes", "Yes", "No"])
        if "which player will be assassinated" in last:
            return f"Answer: [{self.rng.randrange(5)}]"
        if "believe for each player to be Good" in last:
            return "Answer: {" + ", ".join(f"{i}: {self.rng.random():.2f}" for i in range(5)) + "}"
        return "I have no strong read yet; let's watch how people vote."

    def close(self):
        pass


def make_backend(spec: SeatSpec, cfg: ArenaConfig, seed: int, model: Optional[str] = None):
    if spec.provider == "fake":
        return FakeBackend(seed)
    if spec.provider == "codex_cli":
        from .codex_backend import CodexCLIBackend
        return CodexCLIBackend(model or spec.model, cfg, spec.effort)
    if spec.provider == "anthropic":
        return AnthropicBackend(model or spec.model, cfg, spec.effort)
    if spec.provider == "openai":
        return OpenAIBackend(model or spec.model, cfg, spec.effort)
    return ClaudeCLIBackend(model or spec.model, cfg, spec.effort)
