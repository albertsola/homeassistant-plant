"""Datetime entities holding when each care last happened."""

from __future__ import annotations

from datetime import datetime

from homeassistant.components.datetime import DateTimeEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import CARE_FERTILIZE, CARE_WATER, KEY_LAST_FERTILIZED, KEY_LAST_WATERED
from .coordinator import PlantCareCoordinator
from .entity import PlantCareEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the care timestamps."""
    coordinator: PlantCareCoordinator = entry.runtime_data
    async_add_entities(
        [
            PlantCareDateTime(
                coordinator, CARE_WATER, KEY_LAST_WATERED, "mdi:watering-can"
            ),
            PlantCareDateTime(
                coordinator, CARE_FERTILIZE, KEY_LAST_FERTILIZED, "mdi:leaf"
            ),
        ]
    )


class PlantCareDateTime(PlantCareEntity, DateTimeEntity):
    """When a care last happened. Settable, so past care can be backdated."""

    def __init__(
        self, coordinator: PlantCareCoordinator, care: str, key: str, icon: str
    ) -> None:
        """Initialize the entity."""
        super().__init__(coordinator, key)
        self._care = care
        self._attr_translation_key = key
        self._attr_icon = icon

    @property
    def native_value(self) -> datetime | None:
        """Return the stored timestamp."""
        data = self.coordinator.data
        if self._care == CARE_WATER:
            return data.last_watered
        return data.last_fertilized

    async def async_set_value(self, value: datetime) -> None:
        """Record care at the given moment."""
        await self.coordinator.async_log_care(self._care, value)
