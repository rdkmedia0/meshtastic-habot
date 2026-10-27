# SPDX-FileCopyrightText: 2026 Meshtastic HA Bot contributors
#
# SPDX-License-Identifier: MIT

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from homeassistant.config_entries import SOURCE_USER
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.meshtastic_habot.const import (
    CONF_ALLOW_SENSITIVE_DOMAINS,
    CONF_ALLOWED_SENDERS,
    CONF_ANSWER_LENGTH,
    CONF_CHANNEL_INDEX,
    CONF_CONTROL_AREAS,
    CONF_CONTROL_DOMAINS,
    CONF_CONTROL_ENTITIES,
    CONF_COOLDOWN,
    CONF_GATEWAY_ENTRY_ID,
    CONF_MAX_ANSWERS_PER_HOUR,
    CONF_READ_AREAS,
    CONF_READ_DOMAINS,
    CONF_READ_ENTITIES,
    CONF_SCRIPTS,
    CONF_TRIGGER,
    DOMAIN,
)

from .conftest import setup_bot

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

# starting a flow sets up the integration, and with it the conversation integration it depends on
pytestmark = pytest.mark.usefixtures("home")

OPTIONS: dict[str, Any] = {
    CONF_TRIGGER: "@habot",
    CONF_ALLOW_SENSITIVE_DOMAINS: False,
    CONF_COOLDOWN: 30,
    CONF_MAX_ANSWERS_PER_HOUR: 30,
    CONF_ANSWER_LENGTH: 160,
}


def field(result: dict[str, Any], name: str) -> Any:
    """Return the selector of a field of a form."""
    return next(selector for key, selector in result["data_schema"].schema.items() if key == name)


async def start(hass: HomeAssistant, mesh) -> dict[str, Any]:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    return await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_GATEWAY_ENTRY_ID: mesh.gateway.entry_id}
    )


async def test_without_a_gateway_there_is_nothing_to_set_up(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})

    assert (result["type"], result["reason"]) == (FlowResultType.ABORT, "no_gateway")


async def test_only_private_channels_are_offered(hass: HomeAssistant, mesh) -> None:
    result = await start(hass, mesh)

    assert result["step_id"] == "channel"
    # the primary channel, the channel with the default key and the one that is not in use are left out
    options = field(result, CONF_CHANNEL_INDEX).config["options"]
    assert options == [
        {"value": "1", "label": "1: Family"},
        {"value": "3", "label": "3: Mqtt (MQTT uplink on)"},
    ]
    assert result["description_placeholders"] == {
        "unavailable": "0: Primary (primary channel), 2: Public (default key)"
    }


async def test_a_channel_is_set_up_with_its_allowed_senders(hass: HomeAssistant, mesh) -> None:
    result = await start(hass, mesh)

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_CHANNEL_INDEX: "1", CONF_ALLOWED_SENDERS: ["!A1B2C3D4", "2712847316", "!b0b0b0b0"]}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Home Gateway: Family"
    assert result["data"] == {CONF_GATEWAY_ENTRY_ID: mesh.gateway.entry_id, CONF_CHANNEL_INDEX: 1}
    assert result["options"] == {CONF_ALLOWED_SENDERS: ["!a1b2c3d4", "!b0b0b0b0"]}


async def test_the_senders_of_the_gateway_are_offered_and_others_can_be_typed(hass: HomeAssistant, mesh) -> None:
    result = await start(hass, mesh)

    config = field(result, CONF_ALLOWED_SENDERS).config
    assert config["options"] == [
        {"value": "!a1b2c3d4", "label": "Anna (!a1b2c3d4)"},
        {"value": "!b0b0b0b0", "label": "BO (!b0b0b0b0)"},
    ]
    assert config["custom_value"]


async def test_senders_are_optional(hass: HomeAssistant, mesh) -> None:
    result = await start(hass, mesh)

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_CHANNEL_INDEX: "1"})

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["options"] == {CONF_ALLOWED_SENDERS: []}


@pytest.mark.parametrize("sender", ["banana", "!xyz", "0", "!ffffffff", "-1"])
async def test_a_sender_has_to_be_a_node(hass: HomeAssistant, mesh, sender: str) -> None:
    result = await start(hass, mesh)

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_CHANNEL_INDEX: "1", CONF_ALLOWED_SENDERS: ["!a1b2c3d4", sender]}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_ALLOWED_SENDERS: "invalid_sender"}


async def test_a_channel_with_mqtt_uplink_needs_a_confirmation(hass: HomeAssistant, mesh) -> None:
    result = await start(hass, mesh)

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_CHANNEL_INDEX: "3"})
    assert (result["type"], result["step_id"]) == (FlowResultType.FORM, "uplink")

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Home Gateway: Mqtt"
    assert result["data"][CONF_CHANNEL_INDEX] == 3


async def test_a_gateway_without_private_channel_is_refused(hass: HomeAssistant, mesh) -> None:
    primary, _, public, *_ = mesh.client.channels
    mesh.client.channels = [primary, public]

    result = await start(hass, mesh)

    assert (result["type"], result["reason"]) == (FlowResultType.ABORT, "no_private_channel")
    assert result["description_placeholders"] == {
        "unavailable": "0: Primary (primary channel), 2: Public (default key)"
    }


@pytest.mark.parametrize("gateway_cannot_tell", ["no_api", "not_connected", "broken"])
async def test_without_channel_details_the_channel_is_a_number(
    hass: HomeAssistant, mesh, gateway_cannot_tell: str
) -> None:
    if gateway_cannot_tell == "no_api":
        mesh.gateway.runtime_data.client = object()
    elif gateway_cannot_tell == "not_connected":
        mesh.client.channels = []
    else:

        async def fail() -> None:
            msg = "no connection"
            raise OSError(msg)

        mesh.client.async_get_channels = fail

    result = await start(hass, mesh)

    assert result["step_id"] == "channel"
    config = field(result, CONF_CHANNEL_INDEX).config
    assert (config["min"], config["max"]) == (1, 7)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_CHANNEL_INDEX: 5})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Home Gateway: channel 5"
    assert result["data"][CONF_CHANNEL_INDEX] == 5


async def test_a_channel_is_set_up_once(hass: HomeAssistant, mesh) -> None:
    await setup_bot(hass, mesh, channel=1)
    MockConfigEntry(domain=DOMAIN, unique_id=f"{mesh.gateway.entry_id}|1").add_to_hass(hass)
    result = await start(hass, mesh)

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_CHANNEL_INDEX: "1"})

    assert (result["type"], result["reason"]) == (FlowResultType.ABORT, "already_configured")


async def configure_options(hass: HomeAssistant, entry: MockConfigEntry, **changes: Any) -> dict[str, Any]:
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert (result["type"], result["step_id"]) == (FlowResultType.FORM, "init")
    return await hass.config_entries.options.async_configure(result["flow_id"], {**OPTIONS, **changes})


async def test_options_start_empty(hass: HomeAssistant, mesh, home) -> None:
    entry = await setup_bot(hass, mesh)

    result = await hass.config_entries.options.async_init(entry.entry_id)

    defaults = {
        str(key): key.default() if callable(key.default) else key.default
        for key in result["data_schema"].schema
        if key.default is not None and str(key) in OPTIONS
    }
    assert defaults == OPTIONS
    for name in (CONF_READ_ENTITIES, CONF_CONTROL_ENTITIES, CONF_SCRIPTS):
        assert field(result, name).config["multiple"]


async def test_options_are_saved(hass: HomeAssistant, mesh, home) -> None:
    entry = await setup_bot(hass, mesh)

    result = await configure_options(
        hass,
        entry,
        **{
            CONF_TRIGGER: " casa ",
            CONF_ALLOWED_SENDERS: ["!A1B2C3D4"],
            CONF_READ_ENTITIES: ["sensor.living_room_temperature"],
            CONF_READ_AREAS: ["living_room"],
            CONF_READ_DOMAINS: ["weather"],
            CONF_CONTROL_ENTITIES: ["light.kitchen"],
            CONF_CONTROL_AREAS: ["kitchen"],
            CONF_CONTROL_DOMAINS: ["light"],
            CONF_SCRIPTS: ["script.night_mode"],
            CONF_COOLDOWN: 45.0,
            CONF_MAX_ANSWERS_PER_HOUR: 10.0,
            CONF_ANSWER_LENGTH: 120.0,
        },
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {
        CONF_TRIGGER: "casa",
        CONF_ALLOWED_SENDERS: ["!a1b2c3d4"],
        CONF_READ_ENTITIES: ["sensor.living_room_temperature"],
        CONF_READ_AREAS: ["living_room"],
        CONF_READ_DOMAINS: ["weather"],
        CONF_CONTROL_ENTITIES: ["light.kitchen"],
        CONF_CONTROL_AREAS: ["kitchen"],
        CONF_CONTROL_DOMAINS: ["light"],
        CONF_SCRIPTS: ["script.night_mode"],
        CONF_ALLOW_SENSITIVE_DOMAINS: False,
        CONF_COOLDOWN: 45,
        CONF_MAX_ANSWERS_PER_HOUR: 10,
        CONF_ANSWER_LENGTH: 120,
    }
    assert isinstance(entry.options[CONF_COOLDOWN], int)


async def test_a_list_can_be_emptied(hass: HomeAssistant, mesh, home) -> None:
    entry = await setup_bot(hass, mesh, **{CONF_READ_ENTITIES: ["light.kitchen"], CONF_READ_DOMAINS: ["weather"]})

    result = await configure_options(hass, entry)

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_READ_ENTITIES] == []
    assert entry.options[CONF_READ_DOMAINS] == []


@pytest.mark.parametrize("trigger", ["x", "@", "two words", "@" + "x" * 20, "@häbot", "@ha\tbot", ""])
async def test_the_trigger_word_is_validated(hass: HomeAssistant, mesh, home, trigger: str) -> None:
    entry = await setup_bot(hass, mesh)

    result = await configure_options(hass, entry, **{CONF_TRIGGER: trigger})

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_TRIGGER: "invalid_trigger"}


async def test_changing_things_needs_allowed_senders(hass: HomeAssistant, mesh, home) -> None:
    entry = await setup_bot(hass, mesh)

    for change in (
        {CONF_CONTROL_DOMAINS: ["light"]},
        {CONF_CONTROL_ENTITIES: ["light.kitchen"]},
        {CONF_CONTROL_AREAS: ["kitchen"]},
        {CONF_SCRIPTS: ["script.night_mode"]},
    ):
        result = await configure_options(hass, entry, **change)
        assert result["errors"] == {CONF_ALLOWED_SENDERS: "senders_required"}, change

    # reading does not
    result = await configure_options(hass, entry, **{CONF_READ_DOMAINS: ["light"]})
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_an_invalid_sender_is_reported_once(hass: HomeAssistant, mesh, home) -> None:
    entry = await setup_bot(hass, mesh)

    result = await configure_options(hass, entry, **{CONF_ALLOWED_SENDERS: ["banana"], CONF_CONTROL_DOMAINS: ["light"]})

    assert result["errors"] == {CONF_ALLOWED_SENDERS: "invalid_sender"}


async def test_sensitive_domains_cannot_be_controlled_without_the_option(hass: HomeAssistant, mesh, home) -> None:
    entry = await setup_bot(hass, mesh)
    senders = {CONF_ALLOWED_SENDERS: ["!a1b2c3d4"]}

    for change in ({CONF_CONTROL_DOMAINS: ["lock"]}, {CONF_CONTROL_ENTITIES: ["cover.garage"]}):
        result = await configure_options(hass, entry, **senders, **change)
        assert result["errors"] == {CONF_CONTROL_DOMAINS: "sensitive_not_allowed"}, change

    # an area does not name anything sensitive, and what is in it is protected when a command runs
    result = await configure_options(hass, entry, **senders, **{CONF_CONTROL_AREAS: ["hallway"]})
    assert result["type"] is FlowResultType.CREATE_ENTRY

    result = await configure_options(
        hass, entry, **senders, **{CONF_CONTROL_DOMAINS: ["lock"], CONF_ALLOW_SENSITIVE_DOMAINS: True}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_CONTROL_DOMAINS] == ["lock"]


async def test_the_form_keeps_what_was_entered_when_it_has_an_error(hass: HomeAssistant, mesh, home) -> None:
    entry = await setup_bot(hass, mesh)
    result = await hass.config_entries.options.async_init(entry.entry_id)

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {**OPTIONS, CONF_TRIGGER: "x", CONF_READ_DOMAINS: ["weather"]}
    )

    assert result["type"] is FlowResultType.FORM
    suggested = {
        str(key): key.description["suggested_value"]
        for key in result["data_schema"].schema
        if key.description and "suggested_value" in key.description
    }
    assert suggested[CONF_READ_DOMAINS] == ["weather"]
    assert field(result, CONF_TRIGGER) is not None
