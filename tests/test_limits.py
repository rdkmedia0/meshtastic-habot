# SPDX-FileCopyrightText: 2026 Meshtastic HA Bot contributors
#
# SPDX-License-Identifier: MIT

from __future__ import annotations

from custom_components.meshtastic_habot.const import (
    DECISION_LOCKED_OUT,
    DECISION_RATE_LIMITED,
    LOCKOUT_DURATION,
    LOCKOUT_REFUSALS,
    LOCKOUT_WINDOW,
    MAX_TRACKED_SENDERS,
)
from custom_components.meshtastic_habot.limits import CommandLimiter


def refuse(limiter: CommandLimiter, sender: int, now: float) -> str | None:
    """Send a command that is admitted and then refused."""
    result = limiter.admit(sender, now)
    if result is None:
        limiter.record_refusal(sender, now)
    return result


def test_cooldown_is_per_sender() -> None:
    limiter = CommandLimiter(30, 100)

    assert limiter.admit(1, 0) is None
    assert limiter.admit(1, 29.9) == DECISION_RATE_LIMITED
    assert limiter.admit(2, 29.9) is None
    assert limiter.admit(1, 30) is None


def test_a_dropped_command_does_not_extend_the_cooldown() -> None:
    limiter = CommandLimiter(30, 100)
    limiter.admit(1, 0)

    assert limiter.admit(1, 20) == DECISION_RATE_LIMITED
    assert limiter.admit(1, 30) is None


def test_answers_per_hour_are_capped_for_the_whole_bot() -> None:
    limiter = CommandLimiter(5, 3)

    assert [limiter.admit(sender, 0) for sender in (1, 2, 3)] == [None, None, None]
    assert limiter.admit(4, 10) == DECISION_RATE_LIMITED
    assert limiter.admit(4, 3599) == DECISION_RATE_LIMITED
    # the answers leave the hour and there is room for three more
    assert [limiter.admit(sender, 3600) for sender in (4, 5, 6)] == [None, None, None]
    assert limiter.admit(7, 3601) == DECISION_RATE_LIMITED


def test_repeated_refusals_lock_a_sender_out() -> None:
    limiter = CommandLimiter(5, 100)
    now = 0.0
    for _ in range(LOCKOUT_REFUSALS):
        assert refuse(limiter, 1, now) is None
        now += 10

    assert limiter.admit(1, now) == DECISION_LOCKED_OUT
    assert limiter.admit(2, now) is None
    assert limiter.admit(1, now + LOCKOUT_DURATION) is None


def test_slow_refusals_do_not_lock_out() -> None:
    limiter = CommandLimiter(5, 1000)
    now = 0.0
    for _ in range(LOCKOUT_REFUSALS * 3):
        assert refuse(limiter, 1, now) is None
        now += LOCKOUT_WINDOW / (LOCKOUT_REFUSALS - 1) + 1


def test_a_lock_out_starts_over_after_it_ends() -> None:
    limiter = CommandLimiter(5, 1000)
    now = 0.0
    for _ in range(LOCKOUT_REFUSALS):
        refuse(limiter, 1, now)
        now += 6
    now += LOCKOUT_DURATION

    # one more refusal is not enough to lock out again
    assert refuse(limiter, 1, now) is None
    assert limiter.admit(1, now + 6) is None


def test_a_refusal_from_a_sender_the_limiter_does_not_know_is_ignored() -> None:
    limiter = CommandLimiter(5, 100)

    limiter.record_refusal(1, 0)

    assert limiter.admit(1, 0) is None


def test_the_number_of_senders_that_are_tracked_is_bounded() -> None:
    limiter = CommandLimiter(5, 10_000)
    for sender in range(MAX_TRACKED_SENDERS):
        assert limiter.admit(sender, 0) is None

    # all of them are still waiting out their cooldown: no room for another one
    assert limiter.admit(MAX_TRACKED_SENDERS, 1) == DECISION_RATE_LIMITED
    # once they are idle again there is
    assert limiter.admit(MAX_TRACKED_SENDERS, 10) is None


def test_a_locked_out_sender_is_not_forgotten_to_make_room() -> None:
    limiter = CommandLimiter(5, 10_000)
    for step in range(LOCKOUT_REFUSALS):
        refuse(limiter, 0, step * 6)
    for sender in range(1, MAX_TRACKED_SENDERS):
        limiter.admit(sender, 31)

    # the table is full of senders that are idle again, except for the one that is locked out
    assert limiter.admit(MAX_TRACKED_SENDERS, 100) is None
    assert limiter.admit(0, 101) == DECISION_LOCKED_OUT
