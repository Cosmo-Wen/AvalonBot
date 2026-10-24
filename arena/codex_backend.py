"""Codex login-backed completions and a Chat Completions adapter for Avalon tools."""

import asyncio
import json
import os
import shutil
import tempfile
import time
import uuid
from pathlib import Path

from .backends import (BackendError, Completion, FatalBackendError, NotLoggedIn,
                       TransientBackendError, UsageLimitReached, _cli_semaphore,
                       redact_keys, render_transcript)


class CodexCLIBackend:
    def __init__(self, model, cfg, effort=None):
        self.model = model
        self.cfg = cfg
        self.effort = effort
        self.binary = cfg.codex_bin or shutil.which("codex")
        if not self.binary:
            raise FatalBackendError("Codex CLI missing: install Codex and run `codex login`.")

    async def complete(self, system, transcript):
        return await self._run(system + "\n\n" + render_transcript(transcript))

    async def _run(self, prompt, schema=None):
        # Each seat receives only the prompt supplied by its own memory. Never run in the repo.
        async with _cli_semaphore(self.cfg.cli_max_parallel):
            with tempfile.TemporaryDirectory(prefix="avalon-codex-") as directory:
                command = [self.binary, "exec", "--ignore-user-config", "--ignore-rules",
                           "--skip-git-repo-check", "--ephemeral", "--sandbox", "read-only",
                           "--json", "--color", "never", "--model", self.model,
                           "-c", 'approval_policy="never"',
                           "-c", 'model_provider="openai"',
                           "-c", "features.shell_tool=false",
                           "-c", "features.apply_patch=false"]
                if self.effort:
                    command += ["-c", "model_reasoning_effort=" + json.dumps(self.effort)]
                if schema is not None:
                    schema_path = Path(directory) / "response.json"
                    schema_path.write_text(json.dumps(schema), encoding="utf-8")
                    command += ["--output-schema", str(schema_path)]
                command.append("-")
                env = os.environ.copy()
                # Prefer the existing ChatGPT login over API credentials inherited from .env.
                for key in ("OPENAI_API_KEY", "OPENAI_BASE_URL", "CODEX_API_KEY"):
                    env.pop(key, None)
                start = time.monotonic()
                try:
                    proc = await asyncio.create_subprocess_exec(
                        *command, cwd=directory, env=env, stdin=asyncio.subprocess.PIPE,
                        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
                    try:
                        stdout, stderr = await asyncio.wait_for(
                            proc.communicate(prompt.encode()), self.cfg.llm_timeout_s)
                    except BaseException:
                        if proc.returncode is None:
                            proc.kill()
                            await proc.wait()
                        raise
                except asyncio.TimeoutError:
                    raise TransientBackendError("Codex request timed out") from None
                except FileNotFoundError:
                    raise FatalBackendError("Codex executable unavailable") from None
                return self.parse(proc.returncode, stdout.decode("utf-8", "replace"),
                                  stderr.decode("utf-8", "replace"), time.monotonic() - start)

    def parse(self, returncode, stdout, stderr, duration):
        messages, failures, usage = [], [], {}
        try:
            for line in stdout.splitlines():
                event = json.loads(line)
                if event.get("type") == "item.completed":
                    item = event.get("item", {})
                    if item.get("type") == "agent_message":
                        messages.append(item.get("text", ""))
                elif event.get("type") == "turn.completed":
                    usage = event.get("usage") or {}
                elif event.get("type") in ("turn.failed", "error"):
                    failures.append(str(event.get("error") or event.get("message") or "Codex failed"))
        except (ValueError, TypeError, AttributeError):
            raise BackendError("Codex returned malformed event output") from None
        if returncode or failures or not messages:
            message = redact_keys(" ".join(failures) or stderr or "Codex returned no answer")[:400]
            lowered = message.lower()
            if any(s in lowered for s in ("usage limit", "quota", "limit reached")):
                raise UsageLimitReached(message)
            if any(s in lowered for s in ("log in", "login", "unauthorized", "authentication", "401")):
                raise NotLoggedIn("Codex login required: run `codex login`. " + message)
            if any(s in lowered for s in ("rate limit", "overloaded", "temporarily", "connection")):
                raise TransientBackendError(message)
            raise FatalBackendError(message)
        return Completion(messages[-1], usage.get("input_tokens", 0),
                          usage.get("output_tokens", 0), model=self.model, duration_s=duration)

    async def chat(self, payload):
        tools = [t["function"] for t in payload.get("tools", [])]
        choice = payload.get("tool_choice")
        if isinstance(choice, dict):
            tools = [t for t in tools if t["name"] == choice["function"]["name"]]
        prompt = ("Play Avalon using only the supplied messages. Do not access files or execute tools.\n"
                  + json.dumps(payload["messages"]))
        schema = None
        if tools:
            # Arguments stay a JSON string so open-ended belief maps retain their original schema.
            schema = {"type": "object", "properties": {
                "name": {"type": "string", "enum": [t["name"] for t in tools]},
                "arguments": {"type": "string"}},
                "required": ["name", "arguments"], "additionalProperties": False}
            prompt += ("\nSelect one function below. Return its name and arguments as a JSON-encoded "
                       "object string conforming to that function's parameters.\n" + json.dumps(tools))
        result = await self._run(prompt, schema)
        message = {"role": "assistant", "content": result.text}
        if tools:
            try:
                call = json.loads(result.text)
                if call["name"] not in [t["name"] for t in tools] or not isinstance(json.loads(call["arguments"]), dict):
                    raise ValueError()
            except (ValueError, KeyError, TypeError):
                raise BackendError("Codex returned an invalid Avalon function call") from None
            message = {"role": "assistant", "content": None, "tool_calls": [{
                "id": uuid.uuid4().hex, "type": "function", "function": call}]}
        return {"model": result.model, "choices": [{"message": message}], "usage": {
            "prompt_tokens": result.input_tokens, "completion_tokens": result.output_tokens}}

    def close(self):
        pass
