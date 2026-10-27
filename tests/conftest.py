# SPDX-FileCopyrightText: 2026 Meshtastic HA Bot contributors
#
# SPDX-License-Identifier: MIT

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING, Any
from unittest.mock import patch

import pytest
import voluptuous as vol
from homeassistant.components.homeassistant.exposed_entities import async_expose_entity
from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    MockModule,
    async_capture_events,
    async_mock_service,
    mock_integration,
)

from custom_components.meshtastic_habot.const import CONF_CHANNEL_INDEX, CONF_GATEWAY_ENTRY_ID, DOMAIN, EVENT_COMMAND

if TYPE_CHECKING:
    from homeassistant.core import Event, HomeAssistant, ServiceCall

GATEWAY = 0x4904
ANNA = 0xA1B2C3D4
BOB = 0xB0B0B0B0
CHANNEL = 1
PRIVATE_KEY = "AAECAwQFBgcICQoLDA0ODw=="
DEFAULT_KEY = "AQ=="

SEND_TEXT_SCHEMA = vol.Schema(
    {
        vol.Required("text"): str,
        vol.Optional("from"): str,
        vol.Optional("to"): str,
        vol.Optional("channel"): str,
        vol.Optional("ack", default=False): bool,
        vol.Optional("sent_by"): str,
    }
)

# domain, object id, name, area, state, attributes
HOME_ENTITIES = [
    ("light", "living_room", "Living Room Light", "Living Room", "on", {}),
    ("light", "kitchen", "Kitchen Light", "Kitchen", "off", {}),
    ("lock", "front_door", "Front Door", "Hallway", "locked", {}),
    ("cover", "garage", "Garage Door", "Garage", "closed", {}),
    (
        "sensor",
        "living_room_temperature",
        "Living Room Temperature",
        "Living Room",
        "21.5",
        {"device_class": "temperature"},
    ),
    ("script", "night_mode", "Night Mode", None, "off", {}),
    ("script", "burglar_alarm", "Burglar Alarm", None, "off", {}),
    ("weather", "home", "Home", None, "sunny", {"temperature": 18, "temperature_unit": "°C"}),
]


def channel_dict(index: int, *, role: str = "SECONDARY", psk: str = PRIVATE_KEY, name: str = "", uplink: bool = False):
    return {
        "index": index,
        "role": role,
        "settings": {"name": name, "psk": psk, "uplinkEnabled": uplink},
    }


class FakeClient:
    """The two calls of the Meshtastic API client the bot uses."""

    def __init__(self) -> None:
        self.channels = [
            channel_dict(0, role="PRIMARY", psk=DEFAULT_KEY),
            channel_dict(1, name="Family"),
            channel_dict(2, name="Public", psk=DEFAULT_KEY),
            channel_dict(3, name="Mqtt", uplink=True),
            channel_dict(4, role="DISABLED", psk=""),
        ]
        self.nodes = {ANNA: {"user": {"longName": "Anna", "shortName": "AN"}}, BOB: {"user": {"shortName": "BO"}}}

    async def async_get_channels(self):
        return self.channels

    async def async_get_all_nodes(self):
        return self.nodes


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    return


@pytest.fixture
def mesh(hass: HomeAssistant):
    """Fake the parts of the Meshtastic integration the bot talks to."""
    mock_integration(hass, MockModule("meshtastic"))
    gateway = MockConfigEntry(domain="meshtastic", title="Home Gateway")
    gateway.add_to_hass(hass)
    client = FakeClient()
    gateway.runtime_data = SimpleNamespace(gateway_node={"num": GATEWAY}, client=client)
    gateway.mock_state(hass, ConfigEntryState.LOADED)

    sent: list[dict[str, Any]] = []

    def _send_text(call: ServiceCall) -> None:
        sent.append(dict(call.data))

    hass.services.async_register("meshtastic", "send_text", _send_text, schema=SEND_TEXT_SCHEMA)
    return SimpleNamespace(gateway=gateway, client=client, sent=sent)


@pytest.fixture
async def home(hass: HomeAssistant):
    """Set up a small home that Assist knows about, with the services the commands end up calling."""
    for component in ("homeassistant", "intent", "conversation", "light", "lock", "cover", "sensor", "weather"):
        assert await async_setup_component(hass, component, {})
    areas = ar.async_get(hass)
    registry = er.async_get(hass)
    for domain, object_id, name, area, state, attributes in HOME_ENTITIES:
        entry = registry.async_get_or_create(
            domain, "test", object_id, suggested_object_id=object_id, original_name=name
        )
        if area is not None:
            area_entry = areas.async_get_area_by_name(area) or areas.async_create(area)
            registry.async_update_entity(entry.entity_id, area_id=area_entry.id)
        hass.states.async_set(entry.entity_id, state, {"friendly_name": name, **attributes})
        async_expose_entity(hass, "conversation", entry.entity_id, should_expose=True)
    # "what is the temperature in the living room" is answered by the area's own temperature sensor
    living_room = areas.async_get_area_by_name("Living Room")
    areas.async_update(living_room.id, temperature_entity_id="sensor.living_room_temperature")
    calls = {
        service: async_mock_service(hass, *service.split("."))
        for service in (
            "light.turn_on",
            "light.turn_off",
            "lock.lock",
            "lock.unlock",
            "cover.open_cover",
            "cover.close_cover",
            "script.turn_on",
        )
    }
    await hass.async_block_till_done()
    return SimpleNamespace(
        calls=calls,
        areas={
            key: areas.async_get_area_by_name(name).id
            for key, name in (("living_room", "Living Room"), ("kitchen", "Kitchen"), ("hallway", "Hallway"))
        },
    )


def called(calls: list[ServiceCall]) -> list[str]:
    """List the entities a service was called for."""
    return sorted(entity_id for call in calls for entity_id in cv.ensure_list(call.data["entity_id"]))


class Clock:
    """Stands in for the monotonic clock of the bot."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


CLOCK = Clock()


@pytest.fixture(autouse=True)
def clock():
    CLOCK.now = 1000.0
    with patch("custom_components.meshtastic_habot.bot.monotonic", CLOCK):
        yield CLOCK


@pytest.fixture
def commands(hass: HomeAssistant) -> list[Event]:
    """Capture the audit events of the bot."""
    return async_capture_events(hass, EVENT_COMMAND)


async def setup_bot(hass: HomeAssistant, mesh: Any, *, channel: int = CHANNEL, **options: Any) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="bot",
        data={CONF_GATEWAY_ENTRY_ID: mesh.gateway.entry_id, CONF_CHANNEL_INDEX: channel},
        options=options,
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def say(  # noqa: PLR0913
    hass: HomeAssistant,
    mesh: Any,
    text: str,
    *,
    from_id: int = ANNA,
    to_node: int | None = None,
    channel: int | None = CHANNEL,
    message_id: int | None = None,
    entry_id: str | None = None,
    wait: float = 60,
) -> None:
    """Let ``wait`` seconds pass, make the gateway report a text message and let the bot deal with it."""
    CLOCK.now += wait
    hass.bus.async_fire(
        "meshtastic_api_text_message",
        {
            "config_entry_id": entry_id or mesh.gateway.entry_id,
            "data": {
                "from": from_id,
                "to": {"node": to_node, "channel": None if to_node is not None else channel},
                "gateway": GATEWAY,
                "message": text,
            },
            "message_id": message_id,
        },
    )
    await hass.async_block_till_done()
