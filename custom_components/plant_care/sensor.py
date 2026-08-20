"""Sensors: days since each care, plus the summary the card reads."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import (
    CARE_FERTILIZE,
    CARE_WATER,
    CONF_HUMIDITY,
    CONF_ILLUMINANCE,
    CONF_MOISTURE,
    CONF_TEMPERATURE,
    DOMAIN,
    KEY_LAST_FERTILIZED,
    KEY_LAST_WATERED,
    STATUS_NEEDS_BOTH,
    STATUS_NEEDS_FERTILIZER,
    STATUS_NEEDS_WATER,
    STATUS_OK,
    STATUSES,
)
from .coordinator import PlantCareCoordinator
from .entity import PlantCareEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the plant sensors."""
    coordinator: PlantCareCoordinator = entry.runtime_data
    async_add_entities(
        [
            PlantCareDaysSince(
                coordinator, CARE_WATER, "days_since_watered", "mdi:watering-can"
            ),
            PlantCareDaysSince(
                coordinator, CARE_FERTILIZE, "days_since_fertilized", "mdi:leaf"
            ),
            PlantCareSummary(coordinator),
        ]
    )


class PlantCareDaysSince(PlantCareEntity, SensorEntity):
    """Days elapsed since a care event — useful for history and automations."""

    _attr_native_unit_of_measurement = UnitOfTime.DAYS
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 1

    def __init__(
        self, coordinator: PlantCareCoordinator, care: str, key: str, icon: str
    ) -> None:
        """Initialize the entity."""
        super().__init__(coordinator, key)
        self._care = care
        self._attr_translation_key = key
        self._attr_icon = icon

    @property
    def native_value(self) -> float | None:
        """Return the elapsed days, or None if the care was never logged."""
        data = self.coordinator.data
        elapsed = (
            data.days_since_watered
            if self._care == CARE_WATER
            else data.days_since_fertilized
        )
        return None if elapsed is None else round(elapsed, 2)


class PlantCareSummary(PlantCareEntity, SensorEntity):
    """One entity carrying everything the card needs.

    This is what lets a card be configured with a single `entity:` line
    instead of restating every helper and sensor.
    """

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = STATUSES
    _attr_translation_key = "plant"
    _attr_icon = "mdi:flower"

    def __init__(self, coordinator: PlantCareCoordinator) -> None:
        """Initialize the entity."""
        super().__init__(coordinator, "plant")

    @property
    def native_value(self) -> str:
        """Return the overall care status."""
        data = self.coordinator.data
        if data.needs_water and data.needs_fertilizer:
            return STATUS_NEEDS_BOTH
        if data.needs_water:
            return STATUS_NEEDS_WATER
        if data.needs_fertilizer:
            return STATUS_NEEDS_FERTILIZER
        return STATUS_OK

    def _care_entity_id(self, key: str) -> str | None:
        """Look up one of our own datetime entities."""
        return er.async_get(self.hass).async_get_entity_id(
            "datetime", DOMAIN, f"{self.coordinator.entry.entry_id}_{key}"
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Everything the card renders, in one place."""
        data = self.coordinator.data
        options = self.coordinator.entry.options

        def _round(value: float | None) -> float | None:
            return None if value is None else round(value, 2)

        return {
            "plant_name": self.coordinator.plant_name,
            "last_watered": (
                data.last_watered.isoformat() if data.last_watered else None
            ),
            "last_fertilized": (
                data.last_fertilized.isoformat() if data.last_fertilized else None
            ),
            "days_since_watered": _round(data.days_since_watered),
            "days_since_fertilized": _round(data.days_since_fertilized),
            "water_interval": data.water_interval,
            "fertilize_interval": data.fertilize_interval,
            "next_water_due": (
                data.next_water_due.isoformat() if data.next_water_due else None
            ),
            "next_fertilize_due": (
                data.next_fertilize_due.isoformat()
                if data.next_fertilize_due
                else None
            ),
            # Newest first. The card's detail panel reads these.
            "watering_history": [m.isoformat() for m in data.water_history],
            "fertilizing_history": [
                m.isoformat() for m in data.fertilize_history
            ],
            "needs_water": data.needs_water,
            "needs_fertilizer": data.needs_fertilizer,
            "last_watered_entity": self._care_entity_id(KEY_LAST_WATERED),
            "last_fertilized_entity": self._care_entity_id(KEY_LAST_FERTILIZED),
            "temperature_entity": options.get(CONF_TEMPERATURE),
            "humidity_entity": options.get(CONF_HUMIDITY),
            "illuminance_entity": options.get(CONF_ILLUMINANCE),
            "moisture_entity": options.get(CONF_MOISTURE),
        }
