# SPDX-FileCopyrightText: 2026 Meshtastic HA Bot contributors
#
# SPDX-License-Identifier: MIT

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from custom_components.meshtastic_habot.const import CHAT_MAX_TEXT_BYTES
from custom_components.meshtastic_habot.mesh import (
    async_get_channels,
    async_get_node_names,
    bot_name,
    channel_message,
    fit_reply,
    node_label,
    parse_node_id,
    strip_trigger,
)

from .conftest import ANNA, BOB, GATEWAY

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

ELLIPSIS = "…"


def test_a_short_answer_gets_the_name_of_the_bot() -> None:
    assert fit_reply("Yes", "habot", 160) == "habot: Yes"


def test_markdown_emoji_and_line_breaks_are_removed() -> None:
    answer = "**Living room**:\n- 21.5 °C \U0001f321️\n- _humid_ `55`%\r\n☀️ ok"

    assert fit_reply(answer, "habot", 160) == "habot: Living room: - 21.5 °C - humid 55% ok"


def test_an_empty_answer_still_says_something() -> None:
    assert fit_reply("\U0001f44d \n", "habot", 160) == "habot: done"


def test_a_long_answer_is_cut_at_the_end_of_a_word() -> None:
    reply = fit_reply("the quick brown fox jumps over the lazy dog " * 10, "habot", 60)

    assert reply == f"habot: the quick brown fox jumps over the lazy dog the{ELLIPSIS}"
    assert len(reply.encode()) <= 60


def test_a_word_that_ends_exactly_at_the_limit_is_kept() -> None:
    # 7 bytes of name, 3 of ellipsis: the cut falls right after "brown"
    reply = fit_reply("quick brown fox", "habot", 7 + 11 + 3)

    assert reply == f"habot: quick brown{ELLIPSIS}"


def test_one_long_word_is_cut_hard() -> None:
    reply = fit_reply("x" * 500, "habot", 60)

    assert reply == "habot: " + "x" * 50 + ELLIPSIS
    assert len(reply.encode()) == 60


def test_multi_byte_characters_are_counted_in_bytes_and_never_split() -> None:
    answer = "über äöü " * 40 + "你好" * 40
    for limit in range(60, CHAT_MAX_TEXT_BYTES + 1):
        reply = fit_reply(answer, "habot", limit)
        assert len(reply.encode()) <= limit
        assert reply.endswith(ELLIPSIS)


def test_a_cjk_answer_is_cut_between_characters() -> None:
    reply = fit_reply("你好" * 100, "habot", 60)

    # 7 bytes of name and 3 of ellipsis leave 50 bytes, which hold 16 characters of 3 bytes
    assert reply == "habot: " + "你好" * 8 + ELLIPSIS
    assert len(reply.encode()) == 7 + 48 + 3


def test_the_limit_never_exceeds_the_mesh_chat_limit() -> None:
    assert len(fit_reply("x" * 1000, "habot", 1000).encode()) == CHAT_MAX_TEXT_BYTES


def test_the_name_of_the_bot_counts() -> None:
    reply = fit_reply("x" * 1000, "casa", 100)

    assert reply.startswith("casa: ")
    assert len(reply.encode()) == 100


@pytest.mark.parametrize(
    ("text", "command"),
    [
        ("@habot what time is it", "what time is it"),
        ("@HaBot   what time is it  ", "what time is it"),
        ("@habot", ""),
        ("  @habot\nhi", "hi"),
        ("@habotx hi", None),
        ("@habot: hi", None),
        ("hello @habot", None),
        ("habot hi", None),
        ("", None),
    ],
)
def test_the_trigger_word_has_to_be_a_word_of_its_own(text: str, command: str | None) -> None:
    assert strip_trigger(text, "@habot") == command


def test_the_name_of_the_bot_is_the_trigger_without_the_at() -> None:
    assert bot_name("@habot") == "habot"
    assert bot_name("casa") == "casa"


def test_node_ids() -> None:
    assert parse_node_id("!a1b2c3d4") == ANNA
    assert parse_node_id(" 2712847316 ") == ANNA
    for bad in ("", "!", "!xyz", "0", "-5", "!ffffffff", "4294967295", "1.5"):
        with pytest.raises(ValueError, match=r"."):
            parse_node_id(bad)


def event(**data: object) -> dict:
    message = {"from": ANNA, "to": {"node": None, "channel": 1}, "message": "hi"}
    return {"config_entry_id": "gateway", "data": {**message, **data}}


def test_channel_messages() -> None:
    kwargs = {"gateway_entry_id": "gateway", "gateway_num": GATEWAY, "channel_index": 1}

    assert channel_message(event(), **kwargs) == (ANNA, "hi")
    # direct messages, other channels, the gateway itself, other gateways and broken events are not channel messages
    assert channel_message(event(to={"node": GATEWAY, "channel": None}), **kwargs) is None
    assert channel_message(event(to={"node": None, "channel": 2}), **kwargs) is None
    assert channel_message(event(**{"from": GATEWAY}), **kwargs) is None
    assert channel_message({**event(), "config_entry_id": "other"}, **kwargs) is None
    assert channel_message(event(message=None), **kwargs) is None
    assert channel_message(event(**{"from": None}), **kwargs) is None
    assert channel_message({"config_entry_id": "gateway"}, **kwargs) is None


async def test_channels_of_the_gateway(hass: HomeAssistant, mesh) -> None:
    channels = await async_get_channels(hass, mesh.gateway.entry_id)

    assert [(c.index, c.name, c.private, c.uplink) for c in channels] == [
        (0, "Primary", False, False),
        (1, "Family", True, False),
        (2, "Public", False, False),
        (3, "Mqtt", True, True),
    ]


async def test_a_key_without_bytes_or_with_garbage(hass: HomeAssistant, mesh) -> None:
    mesh.client.channels = [
        {"index": 1, "role": "SECONDARY", "settings": {"psk": ""}},
        {"index": 2, "role": "SECONDARY", "settings": {"psk": "not base64!"}},
        {"index": 3, "role": "SECONDARY", "settings": {}},
    ]

    channels = await async_get_channels(hass, mesh.gateway.entry_id)

    assert [(c.index, c.private) for c in channels] == [(1, False), (2, True), (3, False)]


async def test_a_gateway_that_cannot_tell(hass: HomeAssistant, mesh) -> None:
    mesh.gateway.runtime_data.client = object()

    assert await async_get_channels(hass, mesh.gateway.entry_id) is None
    assert await async_get_node_names(hass, mesh.gateway.entry_id) == {}
    assert await async_get_channels(hass, "missing") is None


async def test_node_names(hass: HomeAssistant, mesh) -> None:
    assert await async_get_node_names(hass, mesh.gateway.entry_id) == {ANNA: "Anna", BOB: "BO"}
    assert node_label(hass, ANNA) == "!a1b2c3d4"
