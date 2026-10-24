import asyncio
import json
import os
import stat
import sys
import textwrap
import time

import pytest

from arena.backends import (BackendError, ClaudeCLIBackend, FatalBackendError, NotLoggedIn,
                                TransientBackendError, UsageLimitReached, classify_cli_failure)
from arena.retry import is_transient

from .conftest import make_cfg

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="stub CLI is a POSIX shebang script")

# Behaves like `claude -p --output-format json`; the --model value picks the scenario.
STUB = textwrap.dedent('''\
    #!{python}
    import json, os, sys, time
    args = sys.argv[1:]
    model = args[args.index("--model") + 1]
    system = open(args[args.index("--system-prompt-file") + 1], encoding="utf-8").read()
    prompt = sys.stdin.read()
    log = os.environ.get("STUB_LOG")
    if log:
        with open(log, "a") as f:
            f.write(json.dumps({{"start": time.time(), "cwd": os.getcwd(), "args": args}}) + "\\n")
    def out(code, **d):
        print(json.dumps(d)); sys.exit(code)
    if model == "hang":
        time.sleep(30)
    if model == "slow":
        time.sleep(0.3)
    if model == "garbage":
        print("not json"); sys.exit(3)
    if model == "usage":
        out(1, type="result", is_error=True, api_error_status=429, result="Claude usage limit reached. Your limit will reset at 5pm.")
    if model == "auth":
        out(1, type="result", is_error=True, api_error_status=401, result="Not logged in · Please run /login")
    if model == "nomodel":
        out(1, type="result", is_error=True, api_error_status=404, result="There's an issue with the selected model (nomodel).")
    if model == "overloaded":
        out(1, type="result", is_error=True, api_error_status=529, result="API Error: Overloaded")
    out(0, type="result", is_error=False, result="echo:" + prompt.splitlines()[-1] + "|sys:" + str("Answer tersely" in system),
        total_cost_usd=0.001, usage={{"input_tokens": 3, "cache_creation_input_tokens": 600, "cache_read_input_tokens": 0, "output_tokens": 5}},
        modelUsage={{"claude-stub-1": {{}}}})
''')


@pytest.fixture
def stub(tmp_path, monkeypatch):
    path = tmp_path / "claude"
    path.write_text(STUB.format(python=sys.executable))
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    log = tmp_path / "calls.jsonl"
    monkeypatch.setenv("STUB_LOG", str(log))
    return str(path), log


def backend(stub_path, model, **cfg):
    return ClaudeCLIBackend(model, make_cfg(claude_bin=stub_path, **cfg))


def test_success_parses_result_and_usage(stub):
    path, log = stub
    b = backend(path, "ok")
    c = asyncio.run(b.complete("Answer tersely.", [("user", "intro"), ("agent", "me"), ("user", "Reply OK")]))
    assert c.text == "echo:Reply OK|sys:True"
    assert (c.input_tokens, c.output_tokens, c.cost_usd, c.model) == (603, 5, 0.001, "claude-stub-1")
    call = json.loads(log.read_text().splitlines()[0])
    assert "--strict-mcp-config" in call["args"] and call["args"][call["args"].index("--tools") + 1] == ""
    assert not os.listdir(call["cwd"])  # empty sandbox dir; the system prompt file was cleaned up
    b.close()
    assert not os.path.exists(call["cwd"])


@pytest.mark.parametrize("model,exc", [
    ("usage", UsageLimitReached),
    ("auth", NotLoggedIn),
    ("nomodel", FatalBackendError),
    ("overloaded", TransientBackendError),
    ("garbage", BackendError),
])
def test_failures_are_classified(stub, model, exc):
    b = backend(stub[0], model)
    with pytest.raises(exc):
        asyncio.run(b.complete("", [("user", "hi")]))
    b.close()


def test_timeout_kills_process_and_is_transient(stub):
    b = backend(stub[0], "hang", llm_timeout_s=0.5)
    start = time.monotonic()
    with pytest.raises(TransientBackendError) as ei:
        asyncio.run(b.complete("", [("user", "hi")]))
    assert time.monotonic() - start < 10
    assert is_transient(ei.value)
    b.close()


def test_parallel_cap(stub):
    path, log = stub

    async def main():
        bs = [backend(path, "slow", cli_max_parallel=2) for _ in range(4)]
        await asyncio.gather(*(b.complete("", [("user", "hi")]) for b in bs))
        for b in bs:
            b.close()

    asyncio.run(main())
    starts = sorted(json.loads(l)["start"] for l in log.read_text().splitlines())
    assert len(starts) == 4
    assert starts[2] - starts[0] > 0.25  # the third process waited for a slot


def test_missing_cli_is_fatal(monkeypatch, tmp_path):
    monkeypatch.setenv("PATH", str(tmp_path))
    with pytest.raises(FatalBackendError, match="not found"):
        ClaudeCLIBackend("haiku", make_cfg(claude_bin=None))


def test_classify_messages_without_status():
    assert isinstance(classify_cli_failure(None, "Claude AI usage limit reached|1760000000"), UsageLimitReached)
    assert isinstance(classify_cli_failure(None, "Invalid API key · Please run /login"), NotLoggedIn)
    assert type(classify_cli_failure(None, "something odd")) is BackendError


def test_effort_flag_passed_only_when_set(stub):
    path, log = stub
    for effort in (None, "low"):
        b = ClaudeCLIBackend("ok", make_cfg(claude_bin=path), effort)
        asyncio.run(b.complete("", [("user", "hi")]))
        b.close()
    first, second = [json.loads(l)["args"] for l in log.read_text().splitlines()]
    assert "--effort" not in first
    assert second[second.index("--effort") + 1] == "low"


def test_echoed_transcript_label_is_stripped():
    from arena.backends import strip_echoed_label
    assert strip_echoed_label("[You] Let's wait.") == "Let's wait."
    assert strip_echoed_label("I said [You] earlier") == "I said [You] earlier"
