# SPDX-FileCopyrightText: 2026 Meshtastic HA Bot contributors
#
# SPDX-License-Identifier: MIT

"""Guard against braces in translations: the frontend treats every ``{name}`` as a required placeholder."""

from __future__ import annotations

import json
import re
from pathlib import Path

TRANSLATIONS = Path(__file__).parent.parent / "custom_components" / "meshtastic_habot" / "translations"
# the only placeholders the config flow and options flow actually provide
ALLOWED: dict[str, set[str]] = {
    "config.step.channel.description": {"unavailable"},
    "config.abort.no_private_channel": {"unavailable"},
}


def _strings(value: object, path: str = "") -> list[tuple[str, str]]:
    if isinstance(value, dict):
        return [item for key, child in value.items() for item in _strings(child, f"{path}.{key}" if path else key)]
    if isinstance(value, str):
        return [(path, value)]
    return []


def test_placeholders_are_provided() -> None:
    for file in TRANSLATIONS.glob("*.json"):
        data = json.loads(file.read_text(encoding="utf-8"))
        for path, text in _strings(data):
            placeholders = set(re.findall(r"\{([^}]*)\}", text))
            assert placeholders <= ALLOWED.get(path, set()), f"{file.name}: {path} uses {placeholders}"
            # "<name>" is parsed as a tag by the frontend and breaks the whole string
            assert "<" not in text, f"{file.name}: {path} contains an angle bracket"
