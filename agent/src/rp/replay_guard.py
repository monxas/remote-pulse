"""Replay protection for signed remote commands (review M3).

Maintains a persistent set of recently-executed command_ids so that an attacker
who captures a valid signed command cannot replay it within its expiry window
(60s per ADR-0008 §13).

State is stored at ``/var/lib/rp/command-nonces.json`` (root-owned, mode 0600).
Entries older than the longest expected expiry (5 minutes by default — well
above the 60s signature TTL with margin) are pruned on every check.

This is a complement, not a replacement, for server-side replay protection
(future v1.1). For now, defense-in-depth at the agent.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Iterable

logger = logging.getLogger(__name__)

DEFAULT_STATE_PATH = Path("/var/lib/rp/command-nonces.json")
# Hold nonces for 5 minutes — 5× the default 60s signature TTL gives a safe margin.
DEFAULT_TTL_SECONDS = 300


class ReplayGuard:
    """Agent-local store of executed command_ids to reject replays."""

    def __init__(
        self,
        state_path: Path = DEFAULT_STATE_PATH,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
    ) -> None:
        self.state_path = Path(state_path)
        self.ttl_seconds = ttl_seconds

    # --------------------------------------------------------------------- #
    # Persistence (best-effort; on a fresh boot the set starts empty, which
    # is acceptable because by definition no command issued before boot can
    # still be within its signature TTL window).
    # --------------------------------------------------------------------- #
    def _load(self) -> dict[str, float]:
        if not self.state_path.exists():
            return {}
        try:
            data = json.loads(self.state_path.read_text())
            return {str(k): float(v) for k, v in data.items()}
        except (json.JSONDecodeError, OSError, ValueError) as exc:
            logger.warning(
                "replay-guard state unreadable; resetting",
                extra={"path": str(self.state_path), "error": str(exc)},
            )
            return {}

    def _save(self, entries: dict[str, float]) -> None:
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            logger.warning(
                "replay-guard parent dir unwritable; nonces volatile this session",
                extra={"path": str(self.state_path.parent), "error": str(exc)},
            )
            return

        tmp = self.state_path.with_suffix(".tmp")
        try:
            tmp.write_text(json.dumps(entries, separators=(",", ":")))
            os.chmod(tmp, 0o600)
            os.replace(tmp, self.state_path)
        except OSError as exc:
            logger.warning(
                "replay-guard save failed; continuing in volatile mode",
                extra={"path": str(self.state_path), "error": str(exc)},
            )

    # --------------------------------------------------------------------- #
    # Public API
    # --------------------------------------------------------------------- #
    def has_seen(self, command_id: str) -> bool:
        """Return True if this command_id was already executed within the TTL."""
        entries = self._load()
        return self._prune(entries).get(command_id) is not None

    def mark_executed(self, command_id: str) -> None:
        """Record that this command_id has now been executed."""
        entries = self._prune(self._load())
        entries[command_id] = time.time()
        self._save(entries)

    def purge(self, command_ids: Iterable[str] | None = None) -> None:
        """Remove specific command_ids or all entries. Mostly for tests."""
        if command_ids is None:
            self._save({})
            return
        entries = self._load()
        for cid in command_ids:
            entries.pop(cid, None)
        self._save(entries)

    # --------------------------------------------------------------------- #
    def _prune(self, entries: dict[str, float]) -> dict[str, float]:
        cutoff = time.time() - self.ttl_seconds
        return {cid: ts for cid, ts in entries.items() if ts >= cutoff}
