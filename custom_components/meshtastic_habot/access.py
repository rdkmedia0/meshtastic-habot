# SPDX-FileCopyrightText: 2026 Meshtastic HA Bot contributors
#
# SPDX-License-Identifier: MIT

"""What the bot may read and do: the two lists and the scripts, and the checks against them."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from .const import (
    CONF_ALLOW_SENSITIVE_DOMAINS,
    CONF_CONTROL_AREAS,
    CONF_CONTROL_DOMAINS,
    CONF_CONTROL_ENTITIES,
    CONF_READ_AREAS,
    CONF_READ_DOMAINS,
    CONF_READ_ENTITIES,
    CONF_SCRIPTS,
    DEFAULT_ALLOW_SENSITIVE_DOMAINS,
    SENSITIVE_DOMAINS,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from homeassistant.core import HomeAssistant


def domain_of(entity_id: str) -> str:
    return entity_id.partition(".")[0]


@dataclass(frozen=True)
class AccessList:
    """Entities, areas and domains one permission is given for."""

    entities: frozenset[str] = frozenset()
    areas: frozenset[str] = frozenset()
    domains: frozenset[str] = frozenset()

    def __bool__(self) -> bool:
        return bool(self.entities or self.areas or self.domains)

    def names(self, entity_id: str) -> bool:
        """Say whether the entity itself or its whole domain is on the list."""
        return entity_id in self.entities or domain_of(entity_id) in self.domains

    def covers(self, hass: HomeAssistant, entity_id: str) -> bool:
        """Say whether the entity is on the list, by itself, by its domain or by the area it is in."""
        return self.names(entity_id) or (bool(self.areas) and _area_id(hass, entity_id) in self.areas)


@dataclass(frozen=True)
class AccessPolicy:
    """The lists of one bot. Everything that is not on them is refused."""

    read: AccessList
    control: AccessList
    scripts: frozenset[str]
    allow_sensitive_domains: bool

    @classmethod
    def from_options(cls, options: Mapping[str, Any]) -> AccessPolicy:
        return cls(
            read=AccessList(
                frozenset(options.get(CONF_READ_ENTITIES, ())),
                frozenset(options.get(CONF_READ_AREAS, ())),
                frozenset(options.get(CONF_READ_DOMAINS, ())),
            ),
            control=AccessList(
                frozenset(options.get(CONF_CONTROL_ENTITIES, ())),
                frozenset(options.get(CONF_CONTROL_AREAS, ())),
                frozenset(options.get(CONF_CONTROL_DOMAINS, ())),
            ),
            scripts=frozenset(options.get(CONF_SCRIPTS, ())),
            allow_sensitive_domains=options.get(CONF_ALLOW_SENSITIVE_DOMAINS, DEFAULT_ALLOW_SENSITIVE_DOMAINS),
        )

    @property
    def needs_allowed_senders(self) -> bool:
        """Say whether the bot can change something, which only people on the sender list may ask for."""
        return bool(self.control or self.scripts)

    def can_read(self, hass: HomeAssistant, entity_ids: Iterable[str]) -> bool:
        """Say whether every one of the entities may be read. Nothing at all is not enough."""
        entity_ids = set(entity_ids)
        return bool(entity_ids) and all(self.read.covers(hass, entity_id) for entity_id in entity_ids)

    def can_control(self, hass: HomeAssistant, entity_ids: Iterable[str]) -> bool:
        """
        Say whether every one of the entities may be changed. Nothing at all is not enough.

        A sensitive entity (a lock, a garage door, an alarm...) needs the option and has to be named on the list
        itself: an area on the list never covers it.
        """
        entity_ids = set(entity_ids)
        return bool(entity_ids) and all(self._may_control(hass, entity_id) for entity_id in entity_ids)

    def _may_control(self, hass: HomeAssistant, entity_id: str) -> bool:
        if domain_of(entity_id) in SENSITIVE_DOMAINS:
            return self.allow_sensitive_domains and self.control.names(entity_id)
        return self.control.covers(hass, entity_id)


def _area_id(hass: HomeAssistant, entity_id: str) -> str | None:
    entry = er.async_get(hass).async_get(entity_id)
    if entry is None:
        return None
    if entry.area_id is not None or entry.device_id is None:
        return entry.area_id
    device = dr.async_get(hass).async_get(entry.device_id)
    return device.area_id if device is not None else None
