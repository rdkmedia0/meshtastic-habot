# SPDX-FileCopyrightText: 2026 Meshtastic HA Bot contributors
#
# SPDX-License-Identifier: MIT

"""Helpers for talking to the Meshtastic integration through its public actions and events."""

from __future__ import annotations

import base64
import binascii
import logging
import re
from contextlib import suppress
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntryState
from homeassistant.exceptions import ConfigEntryNotReady, HomeAssistantError
from homeassistant.helpers import device_registry as dr

from .const import (
    BROADCAST_NODE_NUM,
    CHANNEL_ROLE_DISABLED,
    CHANNEL_ROLE_PRIMARY,
    CHAT_MAX_TEXT_BYTES,
    MESHTASTIC_DOMAIN,
    MESHTASTIC_SERVICE_SEND_TEXT,
    REPLY_DONE,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

_ELLIPSIS = "…"
_MARKDOWN = re.compile(r"[*_`~#>|\[\]]")
_EMOJI = re.compile("[\U0001f000-\U0001faff☀-➿⬀-⯿︀-️‍⃣]")


@dataclass(frozen=True)
class ChannelInfo:
    """What the gateway says about one of its channels."""

    index: int
    name: str
    primary: bool
    # no key, or a one byte "well known" key (e.g. the default AQ==): anyone can read the channel
    default_key: bool
    # the gateway passes the channel's messages on to an MQTT server
    uplink: bool

    @property
    def private(self) -> bool:
        return not (self.primary or self.default_key)

    @property
    def label(self) -> str:
        return f"{self.index}: {self.name}"


def parse_node_id(value: str) -> int:
    """Accept a Meshtastic user id (``!a1b2c3d4``) or a node number."""
    value = value.strip()
    node_num = int(value[1:], 16) if value.startswith("!") else int(value)
    if not 0 < node_num < BROADCAST_NODE_NUM:
        msg = "A node number is between 1 and 4294967294"
        raise ValueError(msg)
    return node_num


def node_user_id(node_num: int) -> str:
    return f"!{node_num:08x}"


def node_label(hass: HomeAssistant, node_num: int) -> str:
    """Return the name of a node as the device registry knows it, falling back to its user id."""
    device = dr.async_get(hass).async_get_device(identifiers={(MESHTASTIC_DOMAIN, str(node_num))})
    if device is not None and (device.name_by_user or device.name):
        return device.name_by_user or device.name
    return node_user_id(node_num)


def gateway_node_num(hass: HomeAssistant, gateway_entry_id: str) -> int | None:
    """Find the node number of the gateway behind a Meshtastic config entry."""
    entry = hass.config_entries.async_get_entry(gateway_entry_id)
    if entry is None:
        return None
    gateway_node = getattr(getattr(entry, "runtime_data", None), "gateway_node", None)
    if gateway_node is not None:
        with suppress(AttributeError, TypeError, ValueError):
            if (num := gateway_node.get("num")) is not None:
                return int(num)

    registry = dr.async_get(hass)
    for device in dr.async_entries_for_config_entry(registry, gateway_entry_id):
        if device.via_device_id is not None:
            continue
        for domain, identifier in device.identifiers:
            if domain == MESHTASTIC_DOMAIN and str(identifier).isdigit():
                return int(identifier)
    return None


def _gateway_client(hass: HomeAssistant, gateway_entry_id: str) -> Any:
    entry = hass.config_entries.async_get_entry(gateway_entry_id)
    return getattr(getattr(entry, "runtime_data", None), "client", None)


async def async_get_channels(hass: HomeAssistant, gateway_entry_id: str) -> list[ChannelInfo] | None:
    """
    List the channels the gateway has in use, or None when the Meshtastic integration cannot say.

    The list is empty while the gateway is not connected.
    """
    get_channels = getattr(_gateway_client(hass, gateway_entry_id), "async_get_channels", None)
    if get_channels is None:
        return None
    channels: list[ChannelInfo] = []
    for channel in await get_channels():
        role = channel.get("role")
        settings = channel.get("settings", {})
        if role == CHANNEL_ROLE_DISABLED:
            continue
        index = int(channel.get("index", 0))
        channels.append(
            ChannelInfo(
                index=index,
                name=settings.get("name") or ("Primary" if role == CHANNEL_ROLE_PRIMARY else f"Channel {index}"),
                primary=role == CHANNEL_ROLE_PRIMARY,
                default_key=_key_is_public(settings.get("psk")),
                uplink=bool(settings.get("uplinkEnabled", False)),
            )
        )
    return channels


async def async_get_node_names(hass: HomeAssistant, gateway_entry_id: str) -> dict[int, str]:
    """Return the names of the nodes the gateway knows, by node number; empty when the gateway cannot say."""
    get_nodes = getattr(_gateway_client(hass, gateway_entry_id), "async_get_all_nodes", None)
    if get_nodes is None:
        return {}
    names: dict[int, str] = {}
    for node_num, node in (await get_nodes()).items():
        user = node.get("user", {})
        names[int(node_num)] = user.get("longName") or user.get("shortName") or node_user_id(int(node_num))
    return names


def _key_is_public(psk: str | None) -> bool:
    if not psk:
        return True
    try:
        return len(base64.b64decode(psk)) <= 1
    except (binascii.Error, ValueError):
        return False


def channel_message(
    event_data: Mapping[str, Any], *, gateway_entry_id: str, gateway_num: int, channel_index: int
) -> tuple[int, str] | None:
    """Return (sender node, text) when a Meshtastic text event is a message of someone else on the channel."""
    if event_data.get("config_entry_id") != gateway_entry_id:
        return None
    data = event_data.get("data") or {}
    to = data.get("to") or {}
    sender = data.get("from")
    text = data.get("message")
    if not isinstance(sender, int) or not isinstance(text, str) or sender == gateway_num:
        return None
    # direct messages are never read
    if to.get("node") is not None or to.get("channel") != channel_index:
        return None
    return sender, text


def strip_trigger(text: str, trigger: str) -> str | None:
    """Return what follows the trigger word, or None when the message does not start with it as a word of its own."""
    text = text.strip()
    if text[: len(trigger)].casefold() != trigger.casefold():
        return None
    rest = text[len(trigger) :]
    if rest and not rest[0].isspace():
        return None
    return rest.strip()


def bot_name(trigger: str) -> str:
    """Return the name the bot answers under: the trigger word without its @."""
    return trigger.lstrip("@")


def fit_reply(text: str, name: str, limit: int) -> str:
    """
    Turn an answer into one short message of at most ``limit`` bytes, the name of the bot in front included.

    Markdown, emoji and line breaks are removed. An answer that is still too long is cut at the end of a word and
    finished with an ellipsis; it is never split. ``limit`` can never exceed the Mesh Chat limit.
    """
    prefix = f"{name}: "
    budget = min(limit, CHAT_MAX_TEXT_BYTES) - _byte_len(prefix)
    text = _EMOJI.sub("", _MARKDOWN.sub("", text))
    text = " ".join("".join(char for char in text if char.isprintable() or char.isspace()).split()) or REPLY_DONE
    if _byte_len(text) <= budget:
        return prefix + text
    kept = text.encode("utf-8")[: budget - _byte_len(_ELLIPSIS)].decode("utf-8", errors="ignore")
    if text[len(kept)] != " " and (space := kept.rfind(" ")) > 0:
        kept = kept[:space]
    return prefix + kept.rstrip(" ,;:") + _ELLIPSIS


def _byte_len(text: str) -> int:
    return len(text.encode("utf-8"))


class MeshSender:
    """Sends text to one channel through the Meshtastic integration's ``send_text`` action."""

    def __init__(self, hass: HomeAssistant, gateway_entry_id: str, channel_index: int) -> None:
        self._hass = hass
        self._gateway_entry_id = gateway_entry_id
        self._channel_index = channel_index
        self.gateway_num: int | None = None
        self.supports_sent_by = False

    async def async_setup(self) -> None:
        gateway = self._hass.config_entries.async_get_entry(self._gateway_entry_id)
        if gateway is None:
            msg = "The selected Meshtastic gateway no longer exists"
            raise ConfigEntryNotReady(msg)
        if gateway.state is not ConfigEntryState.LOADED:
            msg = "The Meshtastic gateway is not loaded yet"
            raise ConfigEntryNotReady(msg)
        self.gateway_num = gateway_node_num(self._hass, self._gateway_entry_id)
        if self.gateway_num is None:
            msg = "The Meshtastic gateway has not reported its node yet"
            raise ConfigEntryNotReady(msg)
        service = self._hass.services.async_services_for_domain(MESHTASTIC_DOMAIN).get(MESHTASTIC_SERVICE_SEND_TEXT)
        if service is None:
            msg = "The meshtastic.send_text action is not available yet"
            raise ConfigEntryNotReady(msg)
        self.supports_sent_by = _schema_accepts(service.schema, {"text": "probe", "sent_by": "probe"})
        if not self.supports_sent_by:
            _LOGGER.info(
                "The installed Meshtastic integration does not record messages in Mesh Chat (no sent_by support)"
            )

    async def async_send(self, text: str, *, sent_by: str) -> None:
        data: dict[str, Any] = {
            "from": str(self.gateway_num),
            "text": text,
            "channel": str(self._channel_index),
            "ack": False,
        }
        if self.supports_sent_by:
            data["sent_by"] = sent_by
        try:
            await self._hass.services.async_call(MESHTASTIC_DOMAIN, MESHTASTIC_SERVICE_SEND_TEXT, data, blocking=True)
        except HomeAssistantError:
            _LOGGER.warning("Failed to send an answer to channel %s", self._channel_index, exc_info=True)


def _schema_accepts(schema: Any, data: dict[str, Any]) -> bool:
    if schema is None:
        return False
    try:
        schema(data)
    except vol.Invalid:
        return False
    return True
