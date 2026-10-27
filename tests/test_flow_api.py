# SPDX-FileCopyrightText: 2026 Meshtastic HA Bot contributors
#
# SPDX-License-Identifier: MIT

"""The frontend gets the forms as JSON; some selectors and translations do not survive that."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.setup import async_setup_component

from custom_components.meshtastic_habot.const import DOMAIN

from .conftest import setup_bot

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

# the config_entry selector is not supported by the frontend in flows, only selectors like these are
SUPPORTED = {"select", "text", "number", "entity", "area", "boolean"}


def selectors(data: dict[str, Any]) -> dict[str, str]:
    return {field["name"]: next(iter(field["selector"])) for field in data["data_schema"]}


async def test_forms_are_serialised_for_the_frontend(hass: HomeAssistant, hass_client, mesh, home) -> None:
    entry = await setup_bot(hass, mesh)
    assert await async_setup_component(hass, "config", {})
    client = await hass_client()

    response = await client.post("/api/config/config_entries/flow", json={"handler": DOMAIN})
    assert response.status == 200, await response.text()
    data = await response.json()
    assert selectors(data) == {"gateway_entry_id": "select"}
    assert data["data_schema"][0]["selector"]["select"]["options"] == [
        {"value": mesh.gateway.entry_id, "label": "Home Gateway"}
    ]

    response = await client.post(
        f"/api/config/config_entries/flow/{data['flow_id']}", json={"gateway_entry_id": mesh.gateway.entry_id}
    )
    assert response.status == 200, await response.text()
    data = await response.json()
    assert (data["type"], data["step_id"]) == ("form", "channel")
    assert selectors(data) == {"channel_index": "select", "allowed_senders": "select"}

    response = await client.post("/api/config/config_entries/options/flow", json={"handler": entry.entry_id})
    assert response.status == 200, await response.text()
    data = await response.json()
    assert (data["type"], data["step_id"]) == ("form", "init")
    kinds = selectors(data)
    assert list(kinds) == [
        "trigger",
        "allowed_senders",
        "read_entities",
        "read_areas",
        "read_domains",
        "control_entities",
        "control_areas",
        "control_domains",
        "scripts",
        "allow_sensitive_domains",
        "cooldown",
        "max_answers_per_hour",
        "answer_length",
    ]
    assert set(kinds.values()) <= SUPPORTED
