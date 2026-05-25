"""Tests for replay protection (review M3)."""

from __future__ import annotations

import time

import pytest

from rp.replay_guard import ReplayGuard


@pytest.fixture
def guard(tmp_path):
    state = tmp_path / "command-nonces.json"
    return ReplayGuard(state_path=state, ttl_seconds=2)


def test_unseen_command(guard):
    assert guard.has_seen("cmd-1") is False


def test_seen_command_blocked(guard):
    guard.mark_executed("cmd-1")
    assert guard.has_seen("cmd-1") is True


def test_persistence_across_instances(guard, tmp_path):
    guard.mark_executed("cmd-persist")
    state = tmp_path / "command-nonces.json"
    other = ReplayGuard(state_path=state, ttl_seconds=2)
    assert other.has_seen("cmd-persist") is True


def test_ttl_expiry(guard):
    guard.mark_executed("cmd-old")
    time.sleep(2.1)
    assert guard.has_seen("cmd-old") is False


def test_purge_clears_state(guard):
    guard.mark_executed("a")
    guard.mark_executed("b")
    guard.purge()
    assert guard.has_seen("a") is False
    assert guard.has_seen("b") is False


def test_purge_specific(guard):
    guard.mark_executed("keep")
    guard.mark_executed("drop")
    guard.purge(["drop"])
    assert guard.has_seen("keep") is True
    assert guard.has_seen("drop") is False


def test_corrupted_state_resets_gracefully(tmp_path):
    state = tmp_path / "command-nonces.json"
    state.write_text("not valid json {{{")
    guard = ReplayGuard(state_path=state, ttl_seconds=60)
    assert guard.has_seen("anything") is False  # Should not crash
