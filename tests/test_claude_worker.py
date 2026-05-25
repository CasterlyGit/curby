"""Headless coverage of ClaudeWorker — uses tests/fixtures/fake_claude_worker.py
as the stand-in `claude` binary so we never spawn the real one."""
import pathlib
import sys
import textwrap

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from src.claude_worker import ClaudeWorker


@pytest.fixture
def fake_claude(tmp_path):
    """Writes a small python script that pretends to be `claude` in stream-json
    mode: emits init, then for each input line emits one assistant + result."""
    script = tmp_path / "fake_claude"
    script.write_text(
        "#!/usr/bin/env python3\n" +
        textwrap.dedent("""\
            import json, sys
            sys.stdout.write(json.dumps({"type":"system","subtype":"init"}) + "\\n")
            sys.stdout.flush()
            for line in sys.stdin:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                content = obj.get("message", {}).get("content", "")
                reply = f"echo: {content}"
                sys.stdout.write(json.dumps({
                    "type":"assistant",
                    "message":{"content":[{"type":"text","text":reply}]},
                }) + "\\n")
                sys.stdout.write(json.dumps({
                    "type":"result","is_error":False,"result":reply,
                }) + "\\n")
                sys.stdout.flush()
            sys.exit(0)
        """)
    )
    script.chmod(0o755)
    return str(script)


def test_worker_starts_and_answers(fake_claude, tmp_path):
    w = ClaudeWorker(system_prompt="be helpful", claude_cli=fake_claude, cwd=str(tmp_path))
    w.start()
    assert w.is_alive
    reply, latency_ms = w.ask("hello there")
    assert reply == "echo: hello there"
    assert latency_ms >= 0
    w.stop()
    assert not w.is_alive


def test_worker_handles_serial_questions(fake_claude, tmp_path):
    w = ClaudeWorker(system_prompt="x", claude_cli=fake_claude, cwd=str(tmp_path))
    w.start()
    a, _ = w.ask("first")
    b, _ = w.ask("second")
    c, _ = w.ask("third")
    assert a == "echo: first"
    assert b == "echo: second"
    assert c == "echo: third"
    w.stop()


def test_worker_respawns_after_death(fake_claude, tmp_path):
    w = ClaudeWorker(system_prompt="x", claude_cli=fake_claude, cwd=str(tmp_path))
    w.start()
    w.ask("first")
    # Kill the underlying process
    w._proc.terminate()
    w._proc.wait(timeout=2)
    # Next ask should transparently respawn.
    reply, _ = w.ask("second")
    assert reply == "echo: second"
    w.stop()


def test_worker_raises_when_cli_missing(tmp_path):
    w = ClaudeWorker(system_prompt="x", claude_cli="/nope/claude", cwd=str(tmp_path))
    with pytest.raises(Exception):
        w.start()
