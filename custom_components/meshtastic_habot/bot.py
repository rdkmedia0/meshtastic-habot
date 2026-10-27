# SPDX-FileCopyrightText: 2026 Meshtastic HA Bot contributors
#
# SPDX-License-Identifier: MIT

from __future__ import annotations

import logging
from collections import deque
from time import monotonic
from typing import TYPE_CHECKING, Any

from homeassistant.core import Context, callback
from homeassistant.exceptions import ConfigEntryError, ConfigEntryNotReady

from .access import AccessPolicy
from .assist import Answer, async_ask, async_run_script, run_target
from .const import (
    CONF_ALLOWED_SENDERS,
    CONF_ANSWER_LENGTH,
    CONF_CHANNEL_INDEX,
    CONF_COOLDOWN,
    CONF_GATEWAY_ENTRY_ID,
    CONF_MAX_ANSWERS_PER_HOUR,
    CONF_TRIGGER,
    DECISION_DENIED,
    DECISION_ERROR,
    DECISION_NOT_ALLOWED,
    DECISION_NOT_UNDERSTOOD,
    DECISION_RATE_LIMITED,
    DEDUPLICATE_WINDOW,
    DEFAULT_ANSWER_LENGTH,
    DEFAULT_COOLDOWN,
    DEFAULT_MAX_ANSWERS_PER_HOUR,
    DEFAULT_TRIGGER,
    EVENT_COMMAND,
    EVENT_MESHTASTIC_TEXT_MESSAGE,
    MAX_COMMAND_LENGTH,
    MAX_PENDING_COMMANDS,
    REPLY_ERROR,
    REPLY_NOT_UNDERSTOOD,
)
from .limits import CommandLimiter
from .mesh import (
    MeshSender,
    async_get_channels,
    bot_name,
    channel_message,
    fit_reply,
    node_label,
    parse_node_id,
    strip_trigger,
)

if TYPE_CHECKING:
    import asyncio
    from collections.abc import Callable

    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import Event, HomeAssistant

_LOGGER = logging.getLogger(__name__)


class HaBot:
    """Answers the commands that start with the trigger word on one private channel of a Meshtastic gateway."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        options = entry.options
        self.gateway_entry_id: str = entry.data[CONF_GATEWAY_ENTRY_ID]
        self.channel_index = int(entry.data[CONF_CHANNEL_INDEX])
        self.trigger: str = options.get(CONF_TRIGGER, DEFAULT_TRIGGER)
        self.name = bot_name(self.trigger)
        self.answer_length: int = options.get(CONF_ANSWER_LENGTH, DEFAULT_ANSWER_LENGTH)
        self.allowed_senders = frozenset(parse_node_id(sender) for sender in options.get(CONF_ALLOWED_SENDERS, ()))
        self.policy = AccessPolicy.from_options(options)
        self.limiter = CommandLimiter(
            options.get(CONF_COOLDOWN, DEFAULT_COOLDOWN),
            options.get(CONF_MAX_ANSWERS_PER_HOUR, DEFAULT_MAX_ANSWERS_PER_HOUR),
        )
        self.sender = MeshSender(hass, self.gateway_entry_id, self.channel_index)
        self._unsubscribe: Callable[[], None] | None = None
        self._seen_packets: deque[tuple[int, Any]] = deque(maxlen=DEDUPLICATE_WINDOW)
        # commands are answered one after the other, in the order they arrived
        self._outbox: deque[tuple[int, str, str]] = deque()
        self._drain_task: asyncio.Task[None] | None = None

    async def async_setup(self) -> None:
        if self.policy.needs_allowed_senders and not self.allowed_senders:
            msg = "Changing things needs a list of allowed senders"
            raise ConfigEntryError(msg)
        await self.sender.async_setup()
        await self._async_check_channel()
        self._unsubscribe = self.hass.bus.async_listen(EVENT_MESHTASTIC_TEXT_MESSAGE, self._on_mesh_text)

    async def async_unload(self) -> None:
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None
        self._outbox.clear()
        if self._drain_task is not None and not self._drain_task.done():
            self._drain_task.cancel()
        self._drain_task = None

    async def _async_check_channel(self) -> None:
        """Refuse to run on a channel that is not private; the gateway can change its channels at any time."""
        channels = await async_get_channels(self.hass, self.gateway_entry_id)
        if channels is None:
            _LOGGER.info("The Meshtastic integration cannot tell whether channel %s is private", self.channel_index)
            return
        if not channels:
            msg = "The Meshtastic gateway has not reported its channels yet"
            raise ConfigEntryNotReady(msg)
        channel = next((channel for channel in channels if channel.index == self.channel_index), None)
        if channel is None or not channel.private:
            msg = f"Channel {self.channel_index} is not a private channel of the gateway"
            raise ConfigEntryError(msg)
        if channel.uplink:
            _LOGGER.warning(
                "Channel %s has MQTT uplink on: answers can leave the house over the internet", self.channel_index
            )

    @callback
    def _on_mesh_text(self, event: Event) -> None:
        if self.sender.gateway_num is None:
            return
        match = channel_message(
            event.data,
            gateway_entry_id=self.gateway_entry_id,
            gateway_num=self.sender.gateway_num,
            channel_index=self.channel_index,
        )
        if match is None:
            return
        sender, text = match
        command = strip_trigger(text, self.trigger)
        if command is None:
            return
        packet_id = event.data.get("message_id")
        if packet_id is not None:
            if (sender, packet_id) in self._seen_packets:
                return
            self._seen_packets.append((sender, packet_id))

        if (self.allowed_senders and sender not in self.allowed_senders) or len(command) > MAX_COMMAND_LENGTH:
            self._audit(sender, text, DECISION_DENIED)
        elif (dropped := self.limiter.admit(sender, monotonic())) is not None:
            self._audit(sender, text, dropped)
        elif len(self._outbox) >= MAX_PENDING_COMMANDS:
            self._audit(sender, text, DECISION_RATE_LIMITED)
        else:
            self._outbox.append((sender, text, command))
            if self._drain_task is None or self._drain_task.done():
                self._drain_task = self.hass.async_create_task(self._async_drain(), name=f"{self.entry.title} answers")

    async def _async_drain(self) -> None:
        while self._outbox:
            try:
                await self._async_answer(*self._outbox.popleft())
            except Exception:
                _LOGGER.exception("Unexpected error while answering a command")

    async def _async_answer(self, sender: int, text: str, command: str) -> None:
        context = Context()
        try:
            answer = await self._async_decide(command, context)
        except Exception:
            _LOGGER.exception("Unexpected error while running a command")
            answer = Answer(DECISION_ERROR, REPLY_ERROR)
        if answer.decision == DECISION_NOT_ALLOWED:
            self.limiter.record_refusal(sender, monotonic())
        reply = fit_reply(answer.text, self.name, self.answer_length)
        await self.sender.async_send(reply, sent_by=self.name)
        self._audit(sender, text, answer.decision, reply, context)

    async def _async_decide(self, command: str, context: Context) -> Answer:
        if not command:
            return Answer(DECISION_NOT_UNDERSTOOD, REPLY_NOT_UNDERSTOOD)
        if (script := run_target(command)) is not None:
            return await async_run_script(self.hass, self.policy, script, context)
        return await async_ask(self.hass, self.policy, command, context)

    def _audit(
        self, sender: int, text: str, decision: str, answer: str | None = None, context: Context | None = None
    ) -> None:
        """Record a command as the event ``meshtastic_habot_command``, which the logbook shows."""
        self.hass.bus.async_fire(
            EVENT_COMMAND,
            {
                "config_entry_id": self.entry.entry_id,
                "channel": self.channel_index,
                "sender": sender,
                "sender_name": node_label(self.hass, sender),
                "text": text,
                "decision": decision,
                "answer": answer,
            },
            context=context,
        )
