"""Tests for the live style preferences module."""
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from src import preferences


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(preferences, "PREFS_PATH", tmp_path / "preferences.json")
    yield


def test_load_empty_when_no_file():
    assert preferences.load() == []


def test_append_and_load_roundtrip():
    preferences.append("Keep answers under 10 words.")
    assert preferences.load() == ["Keep answers under 10 words."]


def test_append_caps_at_max_kept():
    for i in range(preferences.MAX_KEPT + 3):
        preferences.append(f"directive {i}")
    prefs = preferences.load()
    assert len(prefs) == preferences.MAX_KEPT
    # FIFO eviction — oldest gone, newest kept
    assert prefs[-1] == f"directive {preferences.MAX_KEPT + 2}"


def test_append_empty_is_noop():
    preferences.append("first")
    preferences.append("   ")
    assert preferences.load() == ["first"]


def test_clear():
    preferences.append("one")
    preferences.append("two")
    preferences.clear()
    assert preferences.load() == []


def test_as_system_addendum_empty():
    assert preferences.as_system_addendum() == ""


def test_as_system_addendum_renders_numbered_list():
    preferences.append("Keep answers under 10 words.")
    preferences.append("Use only English words.")
    out = preferences.as_system_addendum()
    assert "1. Keep answers under 10 words." in out
    assert "2. Use only English words." in out
    assert "most recent last" in out


def test_parse_reply_detects_directive():
    is_pref, payload = preferences.parse_reply("PREFERENCE_UPDATE: Keep answers brief.")
    assert is_pref is True
    assert payload == "Keep answers brief."


def test_parse_reply_detects_reset():
    is_pref, payload = preferences.parse_reply("PREFERENCE_UPDATE: RESET")
    assert is_pref is True
    assert payload == "RESET"


def test_parse_reply_passes_through_non_directive():
    is_pref, payload = preferences.parse_reply("websockets are persistent connections.")
    assert is_pref is False
    assert payload == "websockets are persistent connections."


def test_parse_reply_handles_leading_whitespace():
    is_pref, payload = preferences.parse_reply("\n  PREFERENCE_UPDATE: Be technical.")
    assert is_pref is True
    assert payload == "Be technical."
