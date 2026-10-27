# SPDX-FileCopyrightText: 2026 Meshtastic HA Bot contributors
#
# SPDX-License-Identifier: MIT

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any
from unittest.mock import patch

import voluptuous as vol
from homeassistant.config_entries import ConfigEntryState

from custom_components.meshtastic_habot.assist import async_ask
from custom_components.meshtastic_habot.const import (
    CONF_ALLOW_SENSITIVE_DOMAINS,
    CONF_ALLOWED_SENDERS,
    CONF_ANSWER_LENGTH,
    CONF_CONTROL_AREAS,
    CONF_CONTROL_DOMAINS,
    CONF_CONTROL_ENTITIES,
    CONF_COOLDOWN,
    CONF_MAX_ANSWERS_PER_HOUR,
    CONF_READ_AREAS,
    CONF_READ_DOMAINS,
    CONF_READ_ENTITIES,
    CONF_SCRIPTS,
    CONF_TRIGGER,
    MAX_COMMAND_LENGTH,
)

from .conftest import ANNA, BOB, GATEWAY, called, say, setup_bot

if TYPE_CHECKING:
    from homeassistant.core import Event, HomeAssistant

ALLOWED = ["!a1b2c3d4"]


def decisions(commands: list[Event]) -> list[str]:
    return [event.data["decision"] for event in commands]


async def test_question_on_the_read_list_is_answered(hass: HomeAssistant, mesh, home, commands) -> None:
    await setup_bot(hass, mesh, **{CONF_READ_ENTITIES: ["lock.front_door"]})

    await say(hass, mesh, "@habot is the front door locked")

    assert [(m["channel"], m["text"], m["sent_by"], m["from"]) for m in mesh.sent] == [
        ("1", "habot: Yes", "habot", str(GATEWAY))
    ]
    assert commands[0].data == {
        "config_entry_id": commands[0].data["config_entry_id"],
        "channel": 1,
        "sender": ANNA,
        "sender_name": "!a1b2c3d4",
        "text": "@habot is the front door locked",
        "decision": "answered",
        "answer": "habot: Yes",
    }


async def test_question_off_the_read_list_is_not_allowed(hass: HomeAssistant, mesh, home, commands) -> None:
    await setup_bot(hass, mesh, **{CONF_READ_ENTITIES: ["light.kitchen"]})

    await say(hass, mesh, "@habot is the front door locked")

    assert [m["text"] for m in mesh.sent] == ["habot: not allowed"]
    assert decisions(commands) == ["not_allowed"]


async def test_nothing_is_allowed_by_default(hass: HomeAssistant, mesh, home, commands) -> None:
    await setup_bot(hass, mesh)

    await say(hass, mesh, "@habot is the front door locked")
    await say(hass, mesh, "@habot turn on the living room light", from_id=BOB)

    assert [m["text"] for m in mesh.sent] == ["habot: not allowed", "habot: not allowed"]
    assert home.calls["light.turn_on"] == []


async def test_questions_are_checked_on_everything_they_answer_with(hass: HomeAssistant, mesh, home, commands) -> None:
    entry = await setup_bot(hass, mesh, **{CONF_READ_ENTITIES: ["light.living_room"]})

    # lights that are on and lights that are off are both part of the answer
    await say(hass, mesh, "@habot which lights are on")
    assert [m["text"] for m in mesh.sent] == ["habot: not allowed"]

    hass.config_entries.async_update_entry(entry, options={CONF_READ_DOMAINS: ["light"]})
    await hass.async_block_till_done()
    mesh.sent.clear()
    await say(hass, mesh, "@habot which lights are on")
    assert [m["text"] for m in mesh.sent] == ["habot: Living Room Light"]


async def test_area_and_domain_lists_cover_what_is_in_them(hass: HomeAssistant, mesh, home, commands) -> None:
    await setup_bot(hass, mesh, **{CONF_READ_AREAS: [home.areas["living_room"]], CONF_READ_DOMAINS: ["weather"]})

    await say(hass, mesh, "@habot what is the temperature in the living room")
    await say(hass, mesh, "@habot what is the weather")

    assert [m["text"] for m in mesh.sent] == ["habot: 21.5 degrees", "habot: 18 °C and sunny"]


async def test_date_and_time_need_no_list(hass: HomeAssistant, mesh, home, commands) -> None:
    await setup_bot(hass, mesh)

    await say(hass, mesh, "@habot what time is it")

    assert decisions(commands) == ["answered"]
    assert mesh.sent[0]["text"].startswith("habot: ")


async def test_control_off_the_list_is_not_allowed(hass: HomeAssistant, mesh, home, commands) -> None:
    await setup_bot(hass, mesh, **{CONF_CONTROL_ENTITIES: ["light.living_room"], CONF_ALLOWED_SENDERS: ALLOWED})

    await say(hass, mesh, "@habot turn on the kitchen light")
    await say(hass, mesh, "@habot turn off all lights", from_id=ANNA)

    assert [m["text"] for m in mesh.sent] == ["habot: not allowed", "habot: not allowed"]
    assert home.calls["light.turn_on"] == []
    assert home.calls["light.turn_off"] == []


async def test_control_on_the_list_runs(hass: HomeAssistant, mesh, home, commands) -> None:
    await setup_bot(hass, mesh, **{CONF_CONTROL_ENTITIES: ["light.living_room"], CONF_ALLOWED_SENDERS: ALLOWED})

    await say(hass, mesh, "@habot turn on the living room light")

    assert called(home.calls["light.turn_on"]) == ["light.living_room"]
    assert [m["text"] for m in mesh.sent] == ["habot: Turned on the light"]
    assert decisions(commands) == ["answered"]


async def test_control_by_area_and_domain(hass: HomeAssistant, mesh, home, commands) -> None:
    await setup_bot(
        hass,
        mesh,
        **{
            CONF_CONTROL_AREAS: [home.areas["kitchen"]],
            CONF_CONTROL_DOMAINS: ["light"],
            CONF_ALLOWED_SENDERS: ALLOWED,
        },
    )

    await say(hass, mesh, "@habot turn on lights in the kitchen")
    await say(hass, mesh, "@habot turn off all lights")

    assert called(home.calls["light.turn_on"]) == ["light.kitchen"]
    assert called(home.calls["light.turn_off"]) == ["light.kitchen", "light.living_room"]
    assert decisions(commands) == ["answered", "answered"]


async def test_sensitive_domain_is_refused_without_the_option(hass: HomeAssistant, mesh, home, commands) -> None:
    # the built-in agent takes "lock" for "turn on" and "unlock" for "turn off" a lock, "open" for "turn on" a cover
    await setup_bot(
        hass,
        mesh,
        **{
            CONF_CONTROL_ENTITIES: ["lock.front_door"],
            CONF_CONTROL_DOMAINS: ["cover"],
            CONF_ALLOWED_SENDERS: ALLOWED,
        },
    )

    await say(hass, mesh, "@habot unlock the front door")
    await say(hass, mesh, "@habot open the garage door")

    assert [m["text"] for m in mesh.sent] == ["habot: not allowed", "habot: not allowed"]
    assert home.calls["lock.unlock"] == []
    assert home.calls["cover.open_cover"] == []


async def test_sensitive_domain_runs_with_the_option_when_named(hass: HomeAssistant, mesh, home, commands) -> None:
    await setup_bot(
        hass,
        mesh,
        **{
            CONF_CONTROL_ENTITIES: ["lock.front_door"],
            CONF_CONTROL_DOMAINS: ["cover"],
            CONF_ALLOW_SENSITIVE_DOMAINS: True,
            CONF_ALLOWED_SENDERS: ALLOWED,
        },
    )

    await say(hass, mesh, "@habot lock the front door")
    await say(hass, mesh, "@habot open the garage door")

    assert called(home.calls["lock.lock"]) == ["lock.front_door"]
    assert called(home.calls["cover.open_cover"]) == ["cover.garage"]


async def test_an_area_never_covers_a_sensitive_device(hass: HomeAssistant, mesh, home, commands) -> None:
    await setup_bot(
        hass,
        mesh,
        **{
            CONF_CONTROL_AREAS: [home.areas["hallway"]],
            CONF_ALLOW_SENSITIVE_DOMAINS: True,
            CONF_ALLOWED_SENDERS: ALLOWED,
        },
    )

    await say(hass, mesh, "@habot unlock the front door")

    assert [m["text"] for m in mesh.sent] == ["habot: not allowed"]
    assert home.calls["lock.unlock"] == []


async def test_script_on_the_list_runs(hass: HomeAssistant, mesh, home, commands) -> None:
    await setup_bot(hass, mesh, **{CONF_SCRIPTS: ["script.night_mode"], CONF_ALLOWED_SENDERS: ALLOWED})

    await say(hass, mesh, "@habot run night mode")

    assert called(home.calls["script.turn_on"]) == ["script.night_mode"]
    assert [m["text"] for m in mesh.sent] == ["habot: started Night Mode"]
    assert decisions(commands) == ["answered"]


async def test_script_off_the_list_is_not_allowed(hass: HomeAssistant, mesh, home, commands) -> None:
    await setup_bot(hass, mesh, **{CONF_SCRIPTS: ["script.night_mode"], CONF_ALLOWED_SENDERS: ALLOWED})

    # a script that exists but is not allowed looks like one that does not exist
    await say(hass, mesh, "@habot run burglar alarm")
    await say(hass, mesh, "@habot run nothing at all")
    await say(hass, mesh, "@habot run")

    assert [m["text"] for m in mesh.sent] == ["habot: not allowed"] * 3
    assert home.calls["script.turn_on"] == []


async def test_commands_that_cannot_be_resolved_fail_closed(hass: HomeAssistant, mesh, home, commands) -> None:
    await setup_bot(hass, mesh, **{CONF_CONTROL_DOMAINS: ["light"], CONF_ALLOWED_SENDERS: ALLOWED})

    # a sentence about something Assist does not know is simply not understood
    await say(hass, mesh, "@habot turn on the unknown thing")
    # an empty command
    await say(hass, mesh, "@habot")

    assert [m["text"] for m in mesh.sent] == ["habot: I did not understand"] * 2
    assert decisions(commands) == ["not_understood", "not_understood"]


async def test_unknown_sender_gets_no_answer(hass: HomeAssistant, mesh, home, commands) -> None:
    await setup_bot(hass, mesh, **{CONF_READ_DOMAINS: ["lock"], CONF_ALLOWED_SENDERS: ALLOWED})

    await say(hass, mesh, "@habot is the front door locked", from_id=BOB)

    assert mesh.sent == []
    assert [(e.data["sender"], e.data["decision"], e.data["answer"]) for e in commands] == [(BOB, "denied", None)]


async def test_a_command_that_is_too_long_is_dropped(hass: HomeAssistant, mesh, home, commands) -> None:
    await setup_bot(hass, mesh)

    await say(hass, mesh, "@habot what time is it " + "x" * MAX_COMMAND_LENGTH)

    assert mesh.sent == []
    assert decisions(commands) == ["denied"]


async def test_cooldown(hass: HomeAssistant, mesh, home, commands) -> None:
    await setup_bot(hass, mesh, **{CONF_COOLDOWN: 30})

    await say(hass, mesh, "@habot what time is it", wait=0)
    await say(hass, mesh, "@habot what time is it", wait=29)
    # another sender has a cooldown of their own
    await say(hass, mesh, "@habot what time is it", from_id=BOB, wait=0)
    await say(hass, mesh, "@habot what time is it", wait=2)

    assert decisions(commands) == ["answered", "rate_limited", "answered", "answered"]
    assert len(mesh.sent) == 3


async def test_answers_per_hour(hass: HomeAssistant, mesh, home, commands) -> None:
    await setup_bot(hass, mesh, **{CONF_COOLDOWN: 5, CONF_MAX_ANSWERS_PER_HOUR: 2})

    for sender in (ANNA, BOB, 0xC0C0C0C0):
        await say(hass, mesh, "@habot what time is it", from_id=sender)
    await say(hass, mesh, "@habot what time is it", wait=3600)

    assert decisions(commands) == ["answered", "answered", "rate_limited", "answered"]


async def test_lock_out_after_repeated_refusals(hass: HomeAssistant, mesh, home, commands) -> None:
    await setup_bot(hass, mesh, **{CONF_COOLDOWN: 30})

    for _ in range(5):
        await say(hass, mesh, "@habot is the front door locked")
    await say(hass, mesh, "@habot what time is it")
    # somebody else is not affected
    await say(hass, mesh, "@habot what time is it", from_id=BOB, wait=0)
    await say(hass, mesh, "@habot what time is it", wait=900)

    assert decisions(commands) == ["not_allowed"] * 5 + ["locked_out", "answered", "answered"]
    assert len(mesh.sent) == 5 + 2


async def test_own_messages_and_other_bots_are_ignored(hass: HomeAssistant, mesh, home, commands) -> None:
    await setup_bot(hass, mesh, **{CONF_ALLOWED_SENDERS: ["!a1b2c3d4", f"!{GATEWAY:08x}"]})

    await say(hass, mesh, "@habot what time is it", from_id=GATEWAY)
    # the answer of another bot of the same kind, which does not start with the trigger word as a word of its own
    await say(hass, mesh, "habot: 10:10 AM", from_id=ANNA)
    await say(hass, mesh, "@habot: 10:10 AM", from_id=ANNA)

    assert mesh.sent == []
    assert commands == []


async def test_only_commands_on_the_channel_are_read(hass: HomeAssistant, mesh, home, commands) -> None:
    await setup_bot(hass, mesh)

    await say(hass, mesh, "@habot what time is it", channel=2)
    await say(hass, mesh, "@habot what time is it", to_node=GATEWAY)
    await say(hass, mesh, "hello @habot what time is it")
    await say(hass, mesh, "@habotx what time is it")
    await say(hass, mesh, "@habot what time is it", entry_id="another-gateway")

    assert mesh.sent == []
    assert commands == []


async def test_trigger_word_is_case_insensitive_and_can_be_changed(hass: HomeAssistant, mesh, home, commands) -> None:
    await setup_bot(hass, mesh, **{CONF_TRIGGER: "@Casa"})

    await say(hass, mesh, "@HABOT what time is it")
    await say(hass, mesh, "@casa   what time is it")

    assert [m["text"][:6] for m in mesh.sent] == ["Casa: "]
    assert mesh.sent[0]["sent_by"] == "Casa"


async def test_a_retransmitted_packet_is_answered_once(hass: HomeAssistant, mesh, home, commands) -> None:
    await setup_bot(hass, mesh, **{CONF_COOLDOWN: 5})

    await say(hass, mesh, "@habot what time is it", message_id=77)
    await say(hass, mesh, "@habot what time is it", message_id=77)
    # the same packet id from somebody else is another packet
    await say(hass, mesh, "@habot what time is it", message_id=77, from_id=BOB)

    assert decisions(commands) == ["answered", "answered"]
    assert len(mesh.sent) == 2


async def test_answers_fit_the_configured_length(hass: HomeAssistant, mesh, home, commands) -> None:
    await setup_bot(hass, mesh, **{CONF_READ_DOMAINS: ["light"], CONF_ANSWER_LENGTH: 60})

    await say(hass, mesh, "@habot which lights are on")
    long = mesh.sent[0]["text"]
    assert len(long.encode()) <= 60

    mesh.sent.clear()
    await say(hass, mesh, "@habot what time is it", from_id=BOB)
    assert len(mesh.sent[0]["text"].encode()) <= 60


async def test_old_meshtastic_without_sent_by_still_gets_answers(hass: HomeAssistant, mesh, home, commands) -> None:
    hass.services.async_remove("meshtastic", "send_text")
    schema = vol.Schema(
        {vol.Required("text"): str, vol.Optional("from"): str, vol.Optional("channel"): str, vol.Optional("ack"): bool}
    )
    hass.services.async_register(
        "meshtastic", "send_text", lambda call: mesh.sent.append(dict(call.data)), schema=schema
    )
    await setup_bot(hass, mesh)

    await say(hass, mesh, "@habot what time is it")

    assert "sent_by" not in mesh.sent[0]


async def test_an_error_while_answering_is_reported(hass: HomeAssistant, mesh, home, commands) -> None:
    await setup_bot(hass, mesh)

    with patch("custom_components.meshtastic_habot.bot.async_ask", side_effect=RuntimeError("boom")):
        await say(hass, mesh, "@habot what time is it")

    assert [m["text"] for m in mesh.sent] == ["habot: that did not work"]
    assert decisions(commands) == ["error"]


async def test_a_busy_bot_drops_commands_it_cannot_queue(hass: HomeAssistant, mesh, home, commands) -> None:
    release = asyncio.Event()

    async def slow(*args: Any) -> Any:
        await release.wait()
        return await async_ask(*args)

    await setup_bot(hass, mesh, **{CONF_COOLDOWN: 5, CONF_MAX_ANSWERS_PER_HOUR: 100})
    with patch("custom_components.meshtastic_habot.bot.async_ask", slow):
        for sender in range(0x10000000, 0x10000006):
            hass.bus.async_fire(
                "meshtastic_api_text_message",
                {
                    "config_entry_id": mesh.gateway.entry_id,
                    "data": {"from": sender, "to": {"node": None, "channel": 1}, "message": "@habot what time is it"},
                },
            )
        # one command is being answered, three wait for it
        assert decisions(commands) == ["rate_limited"] * 2
        release.set()
        await hass.async_block_till_done()

    assert decisions(commands) == ["rate_limited"] * 2 + ["answered"] * 4


async def test_setup_refuses_changes_without_allowed_senders(hass: HomeAssistant, mesh, home) -> None:
    entry = await setup_bot(hass, mesh, **{CONF_CONTROL_DOMAINS: ["light"]})
    assert entry.state is ConfigEntryState.SETUP_ERROR

    entry = await setup_bot(hass, mesh, channel=3, **{CONF_SCRIPTS: ["script.night_mode"]})
    assert entry.state is ConfigEntryState.SETUP_ERROR


async def test_setup_refuses_channels_that_are_not_private(hass: HomeAssistant, mesh, home) -> None:
    # the primary channel, a channel with the default key, a channel that is not in use, one that does not exist
    for channel in (0, 2, 4, 7):
        entry = await setup_bot(hass, mesh, channel=channel)
        assert entry.state is ConfigEntryState.SETUP_ERROR, channel


async def test_setup_waits_for_the_gateway(hass: HomeAssistant, mesh, home) -> None:
    mesh.client.channels = []
    assert (await setup_bot(hass, mesh)).state is ConfigEntryState.SETUP_RETRY

    mesh.client.channels = [{"index": 1, "role": "SECONDARY", "settings": {"psk": "AAECAwQFBgcICQoLDA0ODw=="}}]
    mesh.gateway.mock_state(hass, ConfigEntryState.SETUP_IN_PROGRESS)
    assert (await setup_bot(hass, mesh)).state is ConfigEntryState.SETUP_RETRY


async def test_setup_without_channel_details_trusts_the_number(hass: HomeAssistant, mesh, home) -> None:
    mesh.gateway.runtime_data.client = object()

    assert (await setup_bot(hass, mesh)).state is ConfigEntryState.LOADED


async def test_unload_stops_listening(hass: HomeAssistant, mesh, home, commands) -> None:
    entry = await setup_bot(hass, mesh)
    assert await hass.config_entries.async_unload(entry.entry_id)

    await say(hass, mesh, "@habot what time is it")

    assert mesh.sent == []
    assert commands == []
