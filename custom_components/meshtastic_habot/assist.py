# SPDX-FileCopyrightText: 2026 Meshtastic HA Bot contributors
#
# SPDX-License-Identifier: MIT

"""Hand a command to Home Assistant's built-in conversation agent, and to scripts, within the bot's lists."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from homeassistant.components import conversation
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import intent
from homeassistant.helpers.chat_session import async_get_chat_session

from .const import (
    ASSISTANT,
    DECISION_ANSWERED,
    DECISION_ERROR,
    DECISION_NOT_ALLOWED,
    DECISION_NOT_UNDERSTOOD,
    READ_INTENTS,
    REPLY_ERROR,
    REPLY_NOT_ALLOWED,
    REPLY_NOT_UNDERSTOOD,
    REPLY_SCRIPT_STARTED,
    RUN_WORD,
    TARGETLESS_READ_INTENTS,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from hassil.models import MatchEntity
    from hassil.recognize import RecognizeResult
    from homeassistant.core import Context, HomeAssistant

    from .access import AccessPolicy

SCRIPT_DOMAIN = "script"
SERVICE_TURN_ON = "turn_on"


@dataclass(frozen=True)
class Answer:
    decision: str
    text: str


async def async_ask(hass: HomeAssistant, policy: AccessPolicy, text: str, context: Context) -> Answer:
    """
    Let the built-in agent answer ``text``, if the lists allow what it is about.

    Only exact sentences about entities that are exposed to Assist are understood (no sentence triggers, no other
    agents). What a command would change is looked up and checked before the agent runs it. A question changes
    nothing, so the agent answers first and the entities it answered with are checked before the answer is sent.
    """
    intent_name = ""
    refused = False

    def refuse_control(result: RecognizeResult) -> bool:
        nonlocal intent_name, refused
        intent_name = result.intent.name
        if intent_name not in READ_INTENTS:
            refused = not policy.can_control(hass, _command_targets(hass, result))
        return refused

    user_input = conversation.ConversationInput(
        text=text,
        context=context,
        conversation_id=None,
        device_id=None,
        satellite_id=None,
        language=hass.config.language,
        agent_id=conversation.HOME_ASSISTANT_AGENT,
    )
    with (
        async_get_chat_session(hass, None) as session,
        conversation.async_get_chat_log(hass, session, user_input) as chat_log,
    ):
        response = await conversation.async_handle_intents(hass, user_input, chat_log, intent_filter=refuse_control)

    if refused:
        return Answer(DECISION_NOT_ALLOWED, REPLY_NOT_ALLOWED)
    if response is None:
        return Answer(DECISION_NOT_UNDERSTOOD, REPLY_NOT_UNDERSTOOD)
    speech = response.speech.get("plain", {}).get("speech", "")
    if response.response_type is intent.IntentResponseType.ERROR:
        return Answer(DECISION_ERROR, speech or REPLY_ERROR)
    if (
        intent_name in READ_INTENTS
        and intent_name not in TARGETLESS_READ_INTENTS
        and not policy.can_read(hass, _answered_entities(response))
    ):
        return Answer(DECISION_NOT_ALLOWED, REPLY_NOT_ALLOWED)
    return Answer(DECISION_ANSWERED, speech)


def run_target(command: str) -> str | None:
    """Return the script name of a ``run <name>`` command, or None when the command is something else."""
    word, _, name = command.strip().partition(" ")
    return name.strip() if word.casefold() == RUN_WORD else None


async def async_run_script(hass: HomeAssistant, policy: AccessPolicy, name: str, context: Context) -> Answer:
    """Start the allowed script that goes by ``name``; one that is not on the list is refused like an unknown one."""
    wanted = _words(name)
    matches = [
        state
        for entity_id in sorted(policy.scripts)
        if (state := hass.states.get(entity_id)) is not None
        and wanted in {_words(state.name), _words(entity_id.partition(".")[2])}
    ]
    if not wanted or len(matches) != 1:
        return Answer(DECISION_NOT_ALLOWED, REPLY_NOT_ALLOWED)
    await hass.services.async_call(
        SCRIPT_DOMAIN, SERVICE_TURN_ON, {ATTR_ENTITY_ID: matches[0].entity_id}, context=context
    )
    return Answer(DECISION_ANSWERED, f"{REPLY_SCRIPT_STARTED} {matches[0].name}")


def _words(name: str) -> str:
    return " ".join(re.sub(r"[\W_]+", " ", name.casefold()).split())


def _command_targets(hass: HomeAssistant, result: RecognizeResult) -> set[str]:
    """
    Look up the entities a recognised command is about, the way the agent's own intent handlers do.

    These are all the entities the slots of the sentence can point at (a handler may narrow them down further, never
    widen them). The result is empty, and the command is refused, when the sentence does not name anything.
    """
    entities = result.entities
    name = _slot(entities, "name")
    constraints = intent.MatchTargetsConstraints(
        name=None if name == "all" else name,
        area_name=_slot(entities, "area"),
        floor_name=_slot(entities, "floor"),
        domains=_slot_list(entities, "domain"),
        device_classes=_slot_list(entities, "device_class"),
        assistant=ASSISTANT,
    )
    if not constraints.has_constraints:
        return set()
    return {state.entity_id for state in intent.async_match_targets(hass, constraints).states}


def _slot(entities: Mapping[str, MatchEntity], name: str) -> str | None:
    return str(entities[name].value) if name in entities else None


def _slot_list(entities: Mapping[str, MatchEntity], name: str) -> set[str] | None:
    return set(cv.ensure_list(entities[name].value)) if name in entities else None


def _answered_entities(response: intent.IntentResponse) -> set[str]:
    """Return the entities an answer is about, whether they matched the question or not."""
    return {
        *(state.entity_id for state in (*response.matched_states, *response.unmatched_states)),
        *(target.id for target in response.success_results if target.type is intent.IntentResponseTargetType.ENTITY),
    }
