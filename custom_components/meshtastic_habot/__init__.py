# SPDX-FileCopyrightText: 2026 Meshtastic HA Bot contributors
#
# SPDX-License-Identifier: MIT

"""Let the people on a private Meshtastic channel talk to Home Assistant's Assist."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.config_entries import ConfigEntry

from .bot import HaBot

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

type HabotConfigEntry = ConfigEntry[HaBot]


async def async_setup_entry(hass: HomeAssistant, entry: HabotConfigEntry) -> bool:
    bot = HaBot(hass, entry)
    await bot.async_setup()
    entry.runtime_data = bot
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: HabotConfigEntry) -> bool:  # noqa: ARG001
    await entry.runtime_data.async_unload()
    return True


async def _async_update_listener(hass: HomeAssistant, entry: HabotConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
