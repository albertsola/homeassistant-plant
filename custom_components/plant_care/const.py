"""Constants for the Plant Care integration."""

from __future__ import annotations

import logging

from homeassistant.const import Platform

DOMAIN = "plant_care"
LOGGER = logging.getLogger(__package__)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.DATETIME,
    Platform.NUMBER,
    Platform.SENSOR,
]

CONF_PLANT_NAME = "plant_name"
CONF_BUTTON = "button_entity"
CONF_WATER_EVENT = "water_event"
CONF_FERTILIZE_EVENT = "fertilize_event"
CONF_TEMPERATURE = "temperature_entity"
CONF_HUMIDITY = "humidity_entity"
CONF_ILLUMINANCE = "illuminance_entity"
CONF_MOISTURE = "moisture_entity"
CONF_WATER_INTERVAL = "water_interval"
CONF_FERTILIZE_INTERVAL = "fertilize_interval"

SENSOR_CONF_KEYS = (
    CONF_TEMPERATURE,
    CONF_HUMIDITY,
    CONF_ILLUMINANCE,
    CONF_MOISTURE,
)

DEFAULT_WATER_INTERVAL = 7.0
DEFAULT_FERTILIZE_INTERVAL = 30.0
DEFAULT_WATER_EVENT = "on"
DEFAULT_FERTILIZE_EVENT = "off"

CARE_WATER = "water"
CARE_FERTILIZE = "fertilize"

KEY_LAST_WATERED = "last_watered"
KEY_LAST_FERTILIZED = "last_fertilized"
KEY_WATER_HISTORY = "water_history"
KEY_FERTILIZE_HISTORY = "fertilize_history"

# How many past care events to keep per plant. Enough for the card's detail
# panel and a sense of rhythm, small enough to stay out of the way in state
# attributes.
HISTORY_LIMIT = 10

# Buttons disagree on what they call a press. Treat these as equivalent so the
# integration works out of the box with most remotes.
EVENT_ALIASES: dict[str, frozenset[str]] = {
    "on": frozenset({"on", "turn_on", "on_press", "press_on", "single", "press"}),
    "off": frozenset({"off", "turn_off", "off_press", "press_off", "double"}),
}

STORAGE_VERSION = 1

CARD_URL_BASE = "/plant_care"
CARD_FILENAME = "plant-card.js"
CARD_VERSION = "1.3.0"

STATUS_OK = "ok"
STATUS_NEEDS_WATER = "needs_water"
STATUS_NEEDS_FERTILIZER = "needs_fertilizer"
STATUS_NEEDS_BOTH = "needs_both"
STATUSES = [STATUS_OK, STATUS_NEEDS_WATER, STATUS_NEEDS_FERTILIZER, STATUS_NEEDS_BOTH]
