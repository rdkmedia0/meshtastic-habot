# SPDX-FileCopyrightText: 2026 Meshtastic HA Bot contributors
#
# SPDX-License-Identifier: MIT

from typing import Final

DOMAIN: Final = "meshtastic_habot"

MESHTASTIC_DOMAIN: Final = "meshtastic"
MESHTASTIC_SERVICE_SEND_TEXT: Final = "send_text"
EVENT_MESHTASTIC_TEXT_MESSAGE: Final = "meshtastic_api_text_message"
# fired for every command, see the Audit section of the README
EVENT_COMMAND: Final = "meshtastic_habot_command"

CONF_GATEWAY_ENTRY_ID: Final = "gateway_entry_id"
CONF_CHANNEL_INDEX: Final = "channel_index"
CONF_TRIGGER: Final = "trigger"
CONF_ALLOWED_SENDERS: Final = "allowed_senders"
CONF_READ_ENTITIES: Final = "read_entities"
CONF_READ_AREAS: Final = "read_areas"
CONF_READ_DOMAINS: Final = "read_domains"
CONF_CONTROL_ENTITIES: Final = "control_entities"
CONF_CONTROL_AREAS: Final = "control_areas"
CONF_CONTROL_DOMAINS: Final = "control_domains"
CONF_SCRIPTS: Final = "scripts"
CONF_ALLOW_SENSITIVE_DOMAINS: Final = "allow_sensitive_domains"
CONF_COOLDOWN: Final = "cooldown"
CONF_MAX_ANSWERS_PER_HOUR: Final = "max_answers_per_hour"
CONF_ANSWER_LENGTH: Final = "answer_length"

DEFAULT_TRIGGER: Final = "@habot"
DEFAULT_ALLOW_SENSITIVE_DOMAINS: Final = False
DEFAULT_COOLDOWN: Final = 30
DEFAULT_MAX_ANSWERS_PER_HOUR: Final = 30
DEFAULT_ANSWER_LENGTH: Final = 160

# the trigger word is typed on a phone and its name (without the @) opens every answer, so keep it short
MIN_TRIGGER_LENGTH: Final = 2
MAX_TRIGGER_LENGTH: Final = 20
MIN_COOLDOWN: Final = 5
MAX_COOLDOWN: Final = 600
MIN_MAX_ANSWERS_PER_HOUR: Final = 1
MAX_MAX_ANSWERS_PER_HOUR: Final = 120
MIN_ANSWER_LENGTH: Final = 60

# a gateway has eight channel slots, 0 to 7
MAX_CHANNEL_INDEX: Final = 7
# node numbers are 32 bit and the highest one is the broadcast address
BROADCAST_NODE_NUM: Final = 0xFFFFFFFF
CHANNEL_ROLE_PRIMARY: Final = "PRIMARY"
CHANNEL_ROLE_DISABLED: Final = "DISABLED"

# Meshtastic text messages are limited to 200 bytes, prefix included (the limit Mesh Chat enforces)
CHAT_MAX_TEXT_BYTES: Final = 200
# the gateway can report the same packet more than once
DEDUPLICATE_WINDOW: Final = 50
# longer commands are dropped; a Meshtastic message cannot be much longer anyway
MAX_COMMAND_LENGTH: Final = 120

# what the bot is willing to run, see the "What the bot may read and do" section of the README
RUN_WORD: Final = "run"
# the built-in agent understands "turn off" on a lock as unlock and "turn on" on a cover as open
SENSITIVE_DOMAINS: Final = frozenset({"alarm_control_panel", "climate", "cover", "lock", "siren", "valve"})
INTENT_GET_CURRENT_DATE: Final = "HassGetCurrentDate"
INTENT_GET_CURRENT_TIME: Final = "HassGetCurrentTime"
# questions: they change nothing, so what they answered with is checked against the read list afterwards
READ_INTENTS: Final = frozenset(
    {"HassGetState", "HassGetWeather", "HassClimateGetTemperature", INTENT_GET_CURRENT_DATE, INTENT_GET_CURRENT_TIME}
)
# questions that involve no entity at all; they cannot reveal anything about the home
TARGETLESS_READ_INTENTS: Final = frozenset({INTENT_GET_CURRENT_DATE, INTENT_GET_CURRENT_TIME})
# the intents of the built-in agent are matched against what is exposed to this assistant
ASSISTANT: Final = "conversation"

# abuse limits
HOUR: Final = 3600
LOCKOUT_REFUSALS: Final = 5
LOCKOUT_WINDOW: Final = 600
LOCKOUT_DURATION: Final = 900
# senders the limits keep track of; more than this are dropped until old ones expire
MAX_TRACKED_SENDERS: Final = 64
# commands that may wait for the one before them; more are dropped
MAX_PENDING_COMMANDS: Final = 3

# what the audit records as the outcome of a command
DECISION_ANSWERED: Final = "answered"
DECISION_DENIED: Final = "denied"
DECISION_NOT_ALLOWED: Final = "not_allowed"
DECISION_NOT_UNDERSTOOD: Final = "not_understood"
DECISION_RATE_LIMITED: Final = "rate_limited"
DECISION_LOCKED_OUT: Final = "locked_out"
DECISION_ERROR: Final = "error"

# answers the bot gives itself, they go over the air in front of the bot's name
REPLY_NOT_ALLOWED: Final = "not allowed"
REPLY_NOT_UNDERSTOOD: Final = "I did not understand"
REPLY_ERROR: Final = "that did not work"
REPLY_DONE: Final = "done"
REPLY_SCRIPT_STARTED: Final = "started"
