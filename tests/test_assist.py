# SPDX-FileCopyrightText: 2026 Meshtastic HA Bot contributors
#
# SPDX-License-Identifier: MIT

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING, Any
from unittest.mock import patch

import pytest
from homeassistant.components import conversation
from homeassistant.core import Context

from custom_components.meshtastic_habot.access import AccessPolicy
from custom_components.meshtastic_habot.assist import async_ask, async_run_script, run_target
from custom_components.meshtastic_habot.const import (
    CONF_ALLOW_SENSITIVE_DOMAINS,
    CONF_CONTROL_AREAS,
    CONF_CONTROL_DOMAINS,
    CONF_CONTROL_ENTITIES,
    CONF_READ_AREAS,
    CONF_READ_DOMAINS,
    CONF_READ_ENTITIES,
    CONF_SCRIPTS,
)

from .conftest import called

if TYPE_CHECKING:
    from collections.abc import Callable

    from homeassistant.core import HomeAssistant


def fake_recognition(intent_name: str, **slots: Any) -> SimpleNamespace:
    """Build what the agent recognised: an intent and the values of its slots."""
    return SimpleNamespace(
        intent=SimpleNamespace(name=intent_name),
        entities={name: SimpleNamespace(value=value) for name, value in slots.items()},
    )


async def ask(hass: HomeAssistant, text: str, **options: Any):
    return await async_ask(hass, AccessPolicy.from_options(options), text, Context())


@pytest.mark.parametrize(
    "recognition",
    [
        # nothing in the sentence says what it is about
        fake_recognition("HassNevermind"),
        fake_recognition("HassTurnOn"),
        fake_recognition("SomeCustomIntent", item="milk"),
        # what it is about does not exist, or does not exist as far as Assist is concerned
        fake_recognition("HassTurnOn", name="Nonexistent Thing"),
        fake_recognition("HassTurnOn", area="Nowhere", domain="light"),
        fake_recognition("HassTurnOn", name="all"),
        fake_recognition("HassTurnOn", domain="no_such_domain"),
        # a slot that is not about an entity is not a target either
        fake_recognition("HassSetVolume", volume_level=40),
    ],
)
async def test_commands_with_targets_that_cannot_be_resolved_fail_closed(
    hass: HomeAssistant, home, recognition: SimpleNamespace
) -> None:
    executed = []

    async def recognise_and_run(*_: Any, intent_filter: Callable[[Any], bool]) -> None:
        if not intent_filter(recognition):
            executed.append(recognition)

    # every list is as wide as it gets: whatever is refused here is refused because nothing could be resolved
    options = {CONF_CONTROL_DOMAINS: ["light", "script"], CONF_CONTROL_AREAS: list(home.areas.values())}
    with patch.object(conversation, "async_handle_intents", recognise_and_run):
        answer = await ask(hass, "anything", **options)

    assert executed == []
    assert (answer.decision, answer.text) == ("not_allowed", "not allowed")


async def test_a_sentence_that_means_nothing_is_not_understood(hass: HomeAssistant, home) -> None:
    answer = await ask(hass, "tell me a joke", **{CONF_CONTROL_DOMAINS: ["light"]})

    assert (answer.decision, answer.text) == ("not_understood", "I did not understand")


async def test_never_mind_is_refused_as_a_command_without_target(hass: HomeAssistant, home) -> None:
    answer = await ask(hass, "never mind", **{CONF_CONTROL_DOMAINS: ["light"]})

    assert answer.decision == "not_allowed"


async def test_the_agent_is_not_asked_to_run_what_the_lists_refuse(hass: HomeAssistant, home) -> None:
    answer = await ask(hass, "turn on the kitchen light", **{CONF_CONTROL_ENTITIES: ["light.living_room"]})

    assert answer.decision == "not_allowed"
    assert home.calls["light.turn_on"] == []


async def test_a_read_is_answered_after_the_entities_it_answered_with_are_checked(hass: HomeAssistant, home) -> None:
    answer = await ask(hass, "is the front door locked", **{CONF_READ_ENTITIES: ["lock.front_door"]})
    assert (answer.decision, answer.text) == ("answered", "Yes")

    answer = await ask(hass, "is the front door locked", **{CONF_READ_AREAS: [home.areas["hallway"]]})
    assert (answer.decision, answer.text) == ("answered", "Yes")

    answer = await ask(hass, "is the front door locked", **{CONF_READ_DOMAINS: ["lock"]})
    assert (answer.decision, answer.text) == ("answered", "Yes")

    answer = await ask(hass, "is the front door locked", **{CONF_READ_DOMAINS: ["light"]})
    assert (answer.decision, answer.text) == ("not_allowed", "not allowed")


async def test_the_read_list_does_not_allow_control(hass: HomeAssistant, home) -> None:
    answer = await ask(
        hass, "turn on the kitchen light", **{CONF_READ_DOMAINS: ["light"], CONF_READ_ENTITIES: ["light.kitchen"]}
    )

    assert answer.decision == "not_allowed"
    assert home.calls["light.turn_on"] == []


async def test_the_control_list_does_not_allow_reading(hass: HomeAssistant, home) -> None:
    answer = await ask(hass, "which lights are on", **{CONF_CONTROL_DOMAINS: ["light"]})

    assert answer.decision == "not_allowed"


async def test_sensitive_domains_need_the_option_and_a_list_that_names_them(hass: HomeAssistant, home) -> None:
    refused = [
        {CONF_CONTROL_DOMAINS: ["lock"]},
        {CONF_CONTROL_AREAS: [home.areas["hallway"]], CONF_ALLOW_SENSITIVE_DOMAINS: True},
        {CONF_CONTROL_ENTITIES: ["light.living_room"], CONF_ALLOW_SENSITIVE_DOMAINS: True},
    ]
    for options in refused:
        assert (await ask(hass, "unlock the front door", **options)).decision == "not_allowed", options
    assert home.calls["lock.unlock"] == []

    for options in (
        {CONF_CONTROL_DOMAINS: ["lock"], CONF_ALLOW_SENSITIVE_DOMAINS: True},
        {CONF_CONTROL_ENTITIES: ["lock.front_door"], CONF_ALLOW_SENSITIVE_DOMAINS: True},
    ):
        assert (await ask(hass, "unlock the front door", **options)).decision == "answered", options
    assert len(home.calls["lock.unlock"]) == 2


@pytest.mark.parametrize(
    ("command", "script"),
    [
        ("run night mode", "night mode"),
        ("RUN   Night  Mode ", "Night  Mode"),
        ("run", ""),
        ("run  ", ""),
        ("what time is it", None),
        ("rundown the house", None),
        ("", None),
    ],
)
def test_run_commands(command: str, script: str | None) -> None:
    assert run_target(command) == script


async def test_scripts_are_found_by_name_or_by_id(hass: HomeAssistant, home) -> None:
    hass.states.async_set("script.evening", "off", {"friendly_name": "Lights out"})
    policy = AccessPolicy.from_options({CONF_SCRIPTS: ["script.night_mode", "script.evening"]})

    for name in ("Night Mode", "night_mode", "  night   MODE ", "Lights out!", "evening"):
        answer = await async_run_script(hass, policy, name, Context())
        assert answer.decision == "answered", name
    assert called(home.calls["script.turn_on"]) == ["script.evening"] * 2 + ["script.night_mode"] * 3


async def test_two_scripts_of_the_same_name_are_not_guessed_between(hass: HomeAssistant, home) -> None:
    hass.states.async_set("script.night_mode_copy", "off", {"friendly_name": "Night Mode"})
    policy = AccessPolicy.from_options({CONF_SCRIPTS: ["script.night_mode", "script.night_mode_copy"]})

    answer = await async_run_script(hass, policy, "night mode", Context())

    assert answer.decision == "not_allowed"
    assert home.calls["script.turn_on"] == []


async def test_a_script_that_is_gone_is_not_run(hass: HomeAssistant, home) -> None:
    policy = AccessPolicy.from_options({CONF_SCRIPTS: ["script.deleted"]})

    assert (await async_run_script(hass, policy, "deleted", Context())).decision == "not_allowed"
