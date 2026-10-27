# SPDX-FileCopyrightText: 2026 Meshtastic HA Bot contributors
#
# SPDX-License-Identifier: MIT

"""Describe the commands of the bot in the logbook."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.core import callback

from .const import DOMAIN, EVENT_COMMAND

if TYPE_CHECKING:
    from collections.abc import Callable

    from homeassistant.core import Event, HomeAssistant

LOGBOOK_NAME = "Meshtastic HA Bot"


@callback
def async_describe_events(
    hass: HomeAssistant,  # noqa: ARG001
    async_describe_event: Callable[[str, str, Callable[[Event], dict[str, str]]], None],
) -> None:
    @callback
    def describe(event: Event) -> dict[str, str]:
        data = event.data
        message = f"{data['sender_name']}: {data['text']} ({data['decision']})"
        if data["answer"]:
            message += f", answered {data['answer']}"
        return {"name": LOGBOOK_NAME, "message": message}

    async_describe_event(DOMAIN, EVENT_COMMAND, describe)
