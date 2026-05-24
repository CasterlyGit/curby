"""Coverage for voice_config — mocks `say -v ?` so tests never depend on
which voices are actually installed."""
import pathlib
import subprocess
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from src import voice_config


# Sample output from `say -v ?` (real macOS format)
_FAKE_VOICES_BASIC = """\
Albert              en_US    # Hello! My name is Albert.
Samantha (English (US)) en_US    # Hello! My name is Samantha.
Karen               en_AU    # Hello! My name is Karen.
"""

_FAKE_VOICES_WITH_PREMIUM = """\
Ava (Premium)       en_US    # Hello! My name is Ava.
Samantha (English (US)) en_US    # Hello! My name is Samantha.
Zoe (Premium)       en_US    # Hello! My name is Zoe.
"""


@pytest.fixture(autouse=True)
def _isolate_config(tmp_path, monkeypatch):
    monkeypatch.setattr(voice_config, "CONFIG_PATH", tmp_path / "config.json")
    yield


def _patch_voices(monkeypatch, raw):
    def fake_run(cmd, **kw):
        if cmd[:3] == ["say", "-v", "?"]:
            return subprocess.CompletedProcess(cmd, 0, stdout=raw, stderr="")
        raise AssertionError("unexpected subprocess call: %r" % cmd)
    monkeypatch.setattr(voice_config.subprocess, "run", fake_run)
    monkeypatch.setattr(voice_config.shutil, "which", lambda _: "/usr/bin/say")


def test_picks_premium_when_available(monkeypatch):
    _patch_voices(monkeypatch, _FAKE_VOICES_WITH_PREMIUM)
    voice, rate, is_premium = voice_config.resolve_voice()
    assert voice == "Ava (Premium)"
    assert is_premium is True
    assert rate == voice_config.DEFAULT_RATE


def test_falls_back_to_basic_when_no_premium(monkeypatch):
    _patch_voices(monkeypatch, _FAKE_VOICES_BASIC)
    voice, _, is_premium = voice_config.resolve_voice()
    assert voice == "Samantha"
    assert is_premium is False


def test_user_config_overrides_preference(monkeypatch, tmp_path):
    _patch_voices(monkeypatch, _FAKE_VOICES_WITH_PREMIUM)
    (voice_config.CONFIG_PATH).write_text('{"voice": "Karen", "rate": 180}')
    voice, rate, is_premium = voice_config.resolve_voice()
    assert voice == "Karen"
    assert rate == 180
    assert is_premium is False


def test_user_config_premium_marked(monkeypatch, tmp_path):
    _patch_voices(monkeypatch, _FAKE_VOICES_BASIC)  # premium not installed
    (voice_config.CONFIG_PATH).write_text('{"voice": "Zoe (Premium)"}')
    voice, _, is_premium = voice_config.resolve_voice()
    assert voice == "Zoe (Premium)"
    assert is_premium is True  # the name says so


def test_no_say_returns_none(monkeypatch):
    monkeypatch.setattr(voice_config.shutil, "which", lambda _: None)
    voice, _, is_premium = voice_config.resolve_voice()
    assert voice is None
    assert is_premium is False


def test_corrupt_config_is_ignored(monkeypatch, tmp_path):
    _patch_voices(monkeypatch, _FAKE_VOICES_WITH_PREMIUM)
    voice_config.CONFIG_PATH.write_text("{not valid json")
    voice, _, _ = voice_config.resolve_voice()
    assert voice == "Ava (Premium)"  # fell through to preferred-list pick
