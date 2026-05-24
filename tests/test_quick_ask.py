"""Coverage for quick_ask — mocks the backend dispatch so we never hit the
real `claude` CLI or the real Anthropic API."""
import json
import pathlib
import sys
import time

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from src import quick_ask
from src import quick_ask_backends


@pytest.fixture(autouse=True)
def _isolate_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(quick_ask, "SESSION_PATH", tmp_path / "session.json")
    # Point ~/.curby/config.json at tmp so backend resolution defaults
    # cleanly without picking up the real user config.
    monkeypatch.setenv("HOME", str(tmp_path))
    yield


# ── Backend dispatch ──────────────────────────────────────────────────────

def _fake_backend(*replies, errors=()):
    """Returns an ask() function suitable for monkeypatching load_backend."""
    state = {"i": 0, "calls": [], "errors": list(errors)}
    def ask(prompt, system, model="haiku"):
        state["calls"].append((prompt, system, model))
        if state["errors"]:
            err = state["errors"].pop(0)
            if err:
                raise RuntimeError(err)
        reply = replies[state["i"] % len(replies)]
        state["i"] += 1
        return reply, 1234
    ask.state = state  # expose for test inspection
    return ask


def test_run_quick_ask_uses_default_backend(monkeypatch):
    fake = _fake_backend("hello world")
    monkeypatch.setattr(quick_ask_backends, "load_backend",
                         lambda name: fake if name == "claude_cli" else (_ for _ in ()).throw(AssertionError("wrong backend")))
    reply, latency_ms, was_followup = quick_ask.run_quick_ask("hi")
    assert reply == "hello world"
    assert latency_ms == 1234
    assert was_followup is False
    assert len(fake.state["calls"]) == 1


def test_run_quick_ask_respects_configured_backend(monkeypatch, tmp_path):
    (tmp_path / ".curby").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".curby" / "config.json").write_text('{"backend": "api_key"}')
    fake = _fake_backend("api reply")
    monkeypatch.setattr(quick_ask_backends, "load_backend",
                         lambda name: fake if name == "api_key" else (_ for _ in ()).throw(AssertionError(f"got {name}")))
    reply, _, _ = quick_ask.run_quick_ask("hi")
    assert reply == "api reply"


def test_run_quick_ask_falls_back_to_claude_cli_on_failure(monkeypatch):
    """If the configured backend raises, we fall back to claude_cli so the
    user always gets an answer."""
    fallback = _fake_backend("from fallback")
    def loader(name):
        if name == "api_key":
            raise RuntimeError("backend boom")
        if name == "claude_cli":
            return fallback
        raise AssertionError(f"unexpected backend {name}")
    monkeypatch.setattr(quick_ask_backends, "load_backend", loader)
    # Make config select api_key:
    cfg = pathlib.Path(quick_ask.SESSION_PATH).parent / "config.json"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(quick_ask, "_resolve_backend_name", lambda: "api_key")
    reply, _, _ = quick_ask.run_quick_ask("hi")
    assert reply == "from fallback"


def test_run_quick_ask_passes_system_addendum(monkeypatch):
    fake = _fake_backend("ok")
    monkeypatch.setattr(quick_ask_backends, "load_backend", lambda _: fake)
    quick_ask.run_quick_ask("hi", system_addendum="ALWAYS WHISPER")
    _, system_used, _ = fake.state["calls"][0]
    assert "ALWAYS WHISPER" in system_used
    # Base system prompt should also be there.
    assert "tutor" in system_used.lower()


# ── Follow-up window ───────────────────────────────────────────────────────

def test_followup_flag_flips_within_window(monkeypatch):
    fake = _fake_backend("one", "two")
    monkeypatch.setattr(quick_ask_backends, "load_backend", lambda _: fake)
    _, _, first = quick_ask.run_quick_ask("first")
    _, _, second = quick_ask.run_quick_ask("second")
    assert first is False
    assert second is True


def test_followup_flag_resets_after_window(monkeypatch):
    monkeypatch.setattr(quick_ask, "FOLLOWUP_WINDOW_SECONDS", 0.01)
    fake = _fake_backend("one", "two")
    monkeypatch.setattr(quick_ask_backends, "load_backend", lambda _: fake)
    _, _, first = quick_ask.run_quick_ask("first")
    time.sleep(0.05)
    _, _, second = quick_ask.run_quick_ask("second")
    assert first is False
    assert second is False


# ── Logging ────────────────────────────────────────────────────────────────

def test_log_quick_ask_writes_jsonl_entry(tmp_path):
    log = tmp_path / "quick-ask-log.jsonl"
    quick_ask.log_quick_ask("hello", "hi there", 142, log_path=log)
    quick_ask.log_quick_ask("again", "yep", 88, was_followup=True, log_path=log)
    lines = log.read_text().strip().splitlines()
    assert len(lines) == 2
    first = json.loads(lines[0])
    assert first["prompt_text"] == "hello"
    assert first["was_followup"] is False
    assert json.loads(lines[1])["was_followup"] is True


def test_log_quick_ask_swallows_write_errors(tmp_path, capsys):
    blocker = tmp_path / "blocker"
    blocker.write_text("x")
    bad = blocker / "nested" / "log.jsonl"
    quick_ask.log_quick_ask("p", "r", 1, log_path=bad)
    assert "log write failed" in capsys.readouterr().out


# ── Backend loader ─────────────────────────────────────────────────────────

def test_load_backend_builtin_claude_cli():
    fn = quick_ask_backends.load_backend("claude_cli")
    assert callable(fn)


def test_load_backend_builtin_api_key():
    fn = quick_ask_backends.load_backend("api_key")
    assert callable(fn)


def test_load_backend_custom_file(tmp_path):
    plugin = tmp_path / "custom.py"
    plugin.write_text(
        "def ask(prompt, system, model='haiku'):\n"
        "    return f'custom:{prompt}', 99\n"
    )
    fn = quick_ask_backends.load_backend(str(plugin))
    reply, latency = fn("hello", "sys")
    assert reply == "custom:hello"
    assert latency == 99


def test_load_backend_rejects_unknown():
    with pytest.raises(ValueError, match="Unknown backend"):
        quick_ask_backends.load_backend("nonsense_backend_name")
