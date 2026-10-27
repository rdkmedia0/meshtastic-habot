# SPDX-FileCopyrightText: 2026 Meshtastic HA Bot contributors
#
# SPDX-License-Identifier: MIT

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from custom_components.meshtastic_habot.const import DOMAIN, EVENT_COMMAND
from custom_components.meshtastic_habot.logbook import async_describe_events

from .conftest import say, setup_bot

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant


async def test_commands_are_described_for_the_logbook(hass: HomeAssistant, mesh, home, commands) -> None:
    registered: dict[tuple[str, str], Any] = {}
    async_describe_events(
        hass, lambda domain, event_type, describe: registered.update({(domain, event_type): describe})
    )
    describe = registered[(DOMAIN, EVENT_COMMAND)]
    await setup_bot(hass, mesh)

    await say(hass, mesh, "@habot is the front door locked")
    await say(hass, mesh, "@habot what time is it", from_id=0xB0B0B0B0)
    commands[1].data["answer"] = None

    assert describe(commands[0]) == {
        "name": "Meshtastic HA Bot",
        "message": "!a1b2c3d4: @habot is the front door locked (not_allowed), answered habot: not allowed",
    }
    assert describe(commands[1])["message"] == "!b0b0b0b0: @habot what time is it (answered)"
