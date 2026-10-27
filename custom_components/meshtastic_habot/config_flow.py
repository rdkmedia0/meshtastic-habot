# SPDX-FileCopyrightText: 2026 Meshtastic HA Bot contributors
#
# SPDX-License-Identifier: MIT

from __future__ import annotations

from contextlib import suppress
from typing import TYPE_CHECKING, Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers import selector

from .access import domain_of
from .const import (
    CHAT_MAX_TEXT_BYTES,
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
    DEFAULT_ALLOW_SENSITIVE_DOMAINS,
    DEFAULT_ANSWER_LENGTH,
    DEFAULT_COOLDOWN,
    DEFAULT_MAX_ANSWERS_PER_HOUR,
    DEFAULT_TRIGGER,
    DOMAIN,
    MAX_CHANNEL_INDEX,
    MAX_COOLDOWN,
    MAX_MAX_ANSWERS_PER_HOUR,
    MAX_TRIGGER_LENGTH,
    MESHTASTIC_DOMAIN,
    MIN_ANSWER_LENGTH,
    MIN_COOLDOWN,
    MIN_MAX_ANSWERS_PER_HOUR,
    MIN_TRIGGER_LENGTH,
    SENSITIVE_DOMAINS,
)
from .mesh import ChannelInfo, async_get_channels, async_get_node_names, bot_name, node_user_id, parse_node_id

if TYPE_CHECKING:
    from collections.abc import Collection, Iterable

    from homeassistant.config_entries import ConfigEntry, ConfigFlowResult
    from homeassistant.core import HomeAssistant

_UPLINK_NOTE = " (MQTT uplink on)"


def _entry_selector(hass: HomeAssistant, domain: str) -> selector.SelectSelector:
    """Dropdown of the config entries of an integration (the config_entry selector cannot be used in flows)."""
    options = [
        selector.SelectOptionDict(value=entry.entry_id, label=entry.title)
        for entry in hass.config_entries.async_entries(domain)
    ]
    return selector.SelectSelector(
        selector.SelectSelectorConfig(options=options, mode=selector.SelectSelectorMode.DROPDOWN)
    )


def _channel_selector(channels: list[ChannelInfo] | None) -> selector.Selector:
    """Dropdown of the channels that may be used, or a plain number when the gateway cannot tell about them."""
    if channels is None:
        return selector.NumberSelector(
            selector.NumberSelectorConfig(min=1, max=MAX_CHANNEL_INDEX, step=1, mode=selector.NumberSelectorMode.BOX)
        )
    options = [
        selector.SelectOptionDict(
            value=str(channel.index), label=channel.label + (_UPLINK_NOTE if channel.uplink else "")
        )
        for channel in channels
        if channel.private
    ]
    return selector.SelectSelector(
        selector.SelectSelectorConfig(options=options, mode=selector.SelectSelectorMode.DROPDOWN)
    )


def _unavailable_channels(channels: list[ChannelInfo] | None) -> str:
    """Name the channels that cannot be used, and why."""
    if channels is None:
        return "the gateway cannot tell"
    reasons = [
        f"{channel.label} ({'primary channel' if channel.primary else 'default key'})"
        for channel in channels
        if not channel.private
    ]
    return ", ".join(reasons) or "none"


def _sender_selector(names: dict[int, str], selected: Iterable[str]) -> selector.SelectSelector:
    """Nodes of the gateway to pick from; a node that is not listed can be typed in."""
    options = {node_user_id(num): f"{name} ({node_user_id(num)})" for num, name in names.items()}
    options.update({sender: sender for sender in selected if sender not in options})
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=[selector.SelectOptionDict(value=value, label=label) for value, label in options.items()],
            multiple=True,
            custom_value=True,
            mode=selector.SelectSelectorMode.DROPDOWN,
        )
    )


def _domain_selector(hass: HomeAssistant, selected: Iterable[str]) -> selector.SelectSelector:
    domains = sorted({state.domain for state in hass.states.async_all()} | set(selected))
    return selector.SelectSelector(
        selector.SelectSelectorConfig(options=domains, multiple=True, mode=selector.SelectSelectorMode.DROPDOWN)
    )


def _number(minimum: int, maximum: int, unit: str) -> selector.NumberSelector:
    return selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=minimum, max=maximum, step=1, unit_of_measurement=unit, mode=selector.NumberSelectorMode.BOX
        )
    )


def normalise_senders(values: Iterable[str], errors: dict[str, str]) -> list[str]:
    """Turn what was picked or typed into node user ids (``!a1b2c3d4``), collecting an error for the field."""
    senders: set[str] = set()
    for value in values:
        try:
            senders.add(node_user_id(parse_node_id(value)))
        except ValueError:
            errors[CONF_ALLOWED_SENDERS] = "invalid_sender"
    return sorted(senders)


def _options_schema(hass: HomeAssistant, values: dict[str, Any], names: dict[int, str]) -> vol.Schema:
    def suggested(key: str) -> dict[str, Any]:
        return {"suggested_value": values.get(key, [])}

    senders = values.get(CONF_ALLOWED_SENDERS, [])
    return vol.Schema(
        {
            vol.Required(CONF_TRIGGER, default=values.get(CONF_TRIGGER, DEFAULT_TRIGGER)): selector.TextSelector(),
            vol.Optional(CONF_ALLOWED_SENDERS, description=suggested(CONF_ALLOWED_SENDERS)): _sender_selector(
                names, senders
            ),
            vol.Optional(CONF_READ_ENTITIES, description=suggested(CONF_READ_ENTITIES)): selector.EntitySelector(
                selector.EntitySelectorConfig(multiple=True)
            ),
            vol.Optional(CONF_READ_AREAS, description=suggested(CONF_READ_AREAS)): selector.AreaSelector(
                selector.AreaSelectorConfig(multiple=True)
            ),
            vol.Optional(CONF_READ_DOMAINS, description=suggested(CONF_READ_DOMAINS)): _domain_selector(
                hass, values.get(CONF_READ_DOMAINS, [])
            ),
            vol.Optional(CONF_CONTROL_ENTITIES, description=suggested(CONF_CONTROL_ENTITIES)): selector.EntitySelector(
                selector.EntitySelectorConfig(multiple=True)
            ),
            vol.Optional(CONF_CONTROL_AREAS, description=suggested(CONF_CONTROL_AREAS)): selector.AreaSelector(
                selector.AreaSelectorConfig(multiple=True)
            ),
            vol.Optional(CONF_CONTROL_DOMAINS, description=suggested(CONF_CONTROL_DOMAINS)): _domain_selector(
                hass, values.get(CONF_CONTROL_DOMAINS, [])
            ),
            vol.Optional(CONF_SCRIPTS, description=suggested(CONF_SCRIPTS)): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="script", multiple=True)
            ),
            vol.Required(
                CONF_ALLOW_SENSITIVE_DOMAINS,
                default=values.get(CONF_ALLOW_SENSITIVE_DOMAINS, DEFAULT_ALLOW_SENSITIVE_DOMAINS),
            ): selector.BooleanSelector(),
            vol.Required(CONF_COOLDOWN, default=values.get(CONF_COOLDOWN, DEFAULT_COOLDOWN)): _number(
                MIN_COOLDOWN, MAX_COOLDOWN, "s"
            ),
            vol.Required(
                CONF_MAX_ANSWERS_PER_HOUR, default=values.get(CONF_MAX_ANSWERS_PER_HOUR, DEFAULT_MAX_ANSWERS_PER_HOUR)
            ): _number(MIN_MAX_ANSWERS_PER_HOUR, MAX_MAX_ANSWERS_PER_HOUR, ""),
            vol.Required(CONF_ANSWER_LENGTH, default=values.get(CONF_ANSWER_LENGTH, DEFAULT_ANSWER_LENGTH)): _number(
                MIN_ANSWER_LENGTH, CHAT_MAX_TEXT_BYTES, "bytes"
            ),
        }
    )


def _has_sensitive(entities: Collection[str], domains: Collection[str]) -> bool:
    return any(domain_of(entity_id) in SENSITIVE_DOMAINS for entity_id in entities) or any(
        domain in SENSITIVE_DOMAINS for domain in domains
    )


def validate_options(user_input: dict[str, Any], errors: dict[str, str]) -> dict[str, Any]:
    """Normalise the input of the options form, collecting errors per field."""
    options: dict[str, Any] = {CONF_TRIGGER: str(user_input[CONF_TRIGGER]).strip()}
    trigger = options[CONF_TRIGGER]
    if (
        not MIN_TRIGGER_LENGTH <= len(trigger) <= MAX_TRIGGER_LENGTH
        or not trigger.isascii()
        or not trigger.isprintable()
        or " " in trigger
        or not bot_name(trigger)
    ):
        errors[CONF_TRIGGER] = "invalid_trigger"

    options[CONF_ALLOWED_SENDERS] = normalise_senders(user_input.get(CONF_ALLOWED_SENDERS, []), errors)
    for key in (
        CONF_READ_ENTITIES,
        CONF_READ_AREAS,
        CONF_READ_DOMAINS,
        CONF_CONTROL_ENTITIES,
        CONF_CONTROL_AREAS,
        CONF_CONTROL_DOMAINS,
        CONF_SCRIPTS,
    ):
        options[key] = list(user_input.get(key, []))
    options[CONF_ALLOW_SENSITIVE_DOMAINS] = bool(user_input[CONF_ALLOW_SENSITIVE_DOMAINS])
    for key in (CONF_COOLDOWN, CONF_MAX_ANSWERS_PER_HOUR, CONF_ANSWER_LENGTH):
        options[key] = int(user_input[key])

    can_change = any(
        options[key] for key in (CONF_CONTROL_ENTITIES, CONF_CONTROL_AREAS, CONF_CONTROL_DOMAINS, CONF_SCRIPTS)
    )
    if can_change and not options[CONF_ALLOWED_SENDERS] and CONF_ALLOWED_SENDERS not in errors:
        errors[CONF_ALLOWED_SENDERS] = "senders_required"
    if not options[CONF_ALLOW_SENSITIVE_DOMAINS] and _has_sensitive(
        options[CONF_CONTROL_ENTITIES], options[CONF_CONTROL_DOMAINS]
    ):
        errors[CONF_CONTROL_DOMAINS] = "sensitive_not_allowed"
    return options


class MeshtasticHabotConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._gateway_entry_id = ""
        # None when the gateway cannot tell about its channels
        self._channels: list[ChannelInfo] | None = None
        self._channel: ChannelInfo | None = None
        self._data: dict[str, Any] = {}
        self._options: dict[str, Any] = {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if not self.hass.config_entries.async_entries(MESHTASTIC_DOMAIN):
            return self.async_abort(reason="no_gateway")
        if user_input is not None:
            self._gateway_entry_id = user_input[CONF_GATEWAY_ENTRY_ID]
            with suppress(Exception):
                # an empty list means the gateway is not connected right now, which tells nothing either
                self._channels = await async_get_channels(self.hass, self._gateway_entry_id) or None
            if self._channels is not None and not any(channel.private for channel in self._channels):
                return self.async_abort(
                    reason="no_private_channel",
                    description_placeholders={"unavailable": _unavailable_channels(self._channels)},
                )
            return await self.async_step_channel()
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {vol.Required(CONF_GATEWAY_ENTRY_ID): _entry_selector(self.hass, MESHTASTIC_DOMAIN)}
            ),
        )

    async def async_step_channel(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        names: dict[int, str] = {}
        with suppress(Exception):
            names = await async_get_node_names(self.hass, self._gateway_entry_id)
        if user_input is not None:
            index = int(user_input[CONF_CHANNEL_INDEX])
            self._channel = next((channel for channel in self._channels or [] if channel.index == index), None)
            senders = normalise_senders(user_input.get(CONF_ALLOWED_SENDERS, []), errors)
            if not errors:
                await self.async_set_unique_id(f"{self._gateway_entry_id}|{index}")
                self._abort_if_unique_id_configured()
                self._data = {CONF_GATEWAY_ENTRY_ID: self._gateway_entry_id, CONF_CHANNEL_INDEX: index}
                self._options = {CONF_ALLOWED_SENDERS: senders}
                if self._channel is not None and self._channel.uplink:
                    return await self.async_step_uplink()
                return self._create_entry()
        values = user_input or {}
        return self.async_show_form(
            step_id="channel",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_CHANNEL_INDEX, default=values.get(CONF_CHANNEL_INDEX, vol.UNDEFINED)): (
                        _channel_selector(self._channels)
                    ),
                    vol.Optional(
                        CONF_ALLOWED_SENDERS, description={"suggested_value": values.get(CONF_ALLOWED_SENDERS, [])}
                    ): _sender_selector(names, values.get(CONF_ALLOWED_SENDERS, [])),
                }
            ),
            errors=errors,
            description_placeholders={"unavailable": _unavailable_channels(self._channels)},
        )

    async def async_step_uplink(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Make sure the person adding the bot knows that its answers can leave the house over MQTT."""
        if user_input is not None:
            return self._create_entry()
        return self.async_show_form(step_id="uplink", data_schema=vol.Schema({}))

    def _create_entry(self) -> ConfigFlowResult:
        gateway = self.hass.config_entries.async_get_entry(self._gateway_entry_id)
        label = self._channel.name if self._channel is not None else f"channel {self._data[CONF_CHANNEL_INDEX]}"
        return self.async_create_entry(
            title=f"{gateway.title if gateway else 'Meshtastic'}: {label}", data=self._data, options=self._options
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:  # noqa: ARG004
        return MeshtasticHabotOptionsFlow()


class MeshtasticHabotOptionsFlow(OptionsFlow):
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            options = validate_options(user_input, errors)
            if not errors:
                return self.async_create_entry(data=options)
        names: dict[int, str] = {}
        with suppress(Exception):
            names = await async_get_node_names(self.hass, self.config_entry.data[CONF_GATEWAY_ENTRY_ID])
        values = user_input if user_input is not None else dict(self.config_entry.options)
        return self.async_show_form(
            step_id="init", data_schema=_options_schema(self.hass, values, names), errors=errors
        )
