# SPDX-FileCopyrightText: 2026 Meshtastic HA Bot contributors
#
# SPDX-License-Identifier: MIT

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from .const import (
    DECISION_LOCKED_OUT,
    DECISION_RATE_LIMITED,
    HOUR,
    LOCKOUT_DURATION,
    LOCKOUT_REFUSALS,
    LOCKOUT_WINDOW,
    MAX_TRACKED_SENDERS,
)


@dataclass
class _Sender:
    last_command: float = 0.0
    locked_until: float = 0.0
    refusals: deque[float] = field(default_factory=lambda: deque(maxlen=LOCKOUT_REFUSALS))

    def is_idle(self, now: float, cooldown: float) -> bool:
        return now - self.last_command >= cooldown and now >= self.locked_until


class CommandLimiter:
    """
    Keeps the bot from being used to fill the channel.

    Every sender has a cooldown between two commands and is locked out for a while after repeated refused commands;
    the whole bot has a cap on the answers it gives per hour. Times are monotonic seconds passed in by the caller.
    """

    def __init__(self, cooldown: float, max_answers_per_hour: int) -> None:
        self._cooldown = cooldown
        self._max_answers_per_hour = max_answers_per_hour
        self._senders: dict[int, _Sender] = {}
        self._answers: deque[float] = deque()

    def admit(self, sender: int, now: float) -> str | None:
        """Return why a command from ``sender`` is dropped, or None after counting it as an answer to come."""
        state = self._senders.get(sender)
        if state is not None and now < state.locked_until:
            return DECISION_LOCKED_OUT
        if state is not None and now - state.last_command < self._cooldown:
            return DECISION_RATE_LIMITED
        while self._answers and now - self._answers[0] >= HOUR:
            self._answers.popleft()
        if len(self._answers) >= self._max_answers_per_hour:
            return DECISION_RATE_LIMITED
        if state is None:
            if len(self._senders) >= MAX_TRACKED_SENDERS:
                self._forget_idle(now)
            if len(self._senders) >= MAX_TRACKED_SENDERS:
                return DECISION_RATE_LIMITED
            state = self._senders[sender] = _Sender()
        state.last_command = now
        self._answers.append(now)
        return None

    def record_refusal(self, sender: int, now: float) -> None:
        """Count a refused command; enough of them in a short time lock the sender out."""
        state = self._senders.get(sender)
        if state is None:
            return
        state.refusals.append(now)
        if len(state.refusals) == LOCKOUT_REFUSALS and now - state.refusals[0] <= LOCKOUT_WINDOW:
            state.locked_until = now + LOCKOUT_DURATION
            state.refusals.clear()

    def _forget_idle(self, now: float) -> None:
        self._senders = {
            sender: state for sender, state in self._senders.items() if not state.is_idle(now, self._cooldown)
        }
