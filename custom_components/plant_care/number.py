"""Adjustable care intervals."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import (
    CARE_FERTILIZE,
    CARE_WATER,
    CONF_FERTILIZE_INTERVAL,
    CONF_WATER_INTERVAL,
)
from .coordinator import PlantCareCoordinator
from .entity import PlantCareEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the interval numbers."""
    coordinator: PlantCareCoordinator = entry.runtime_data
    async_add_entities(
        [
            PlantCareInterval(coordinator, CARE_WATER, CONF_WATER_INTERVAL),
            PlantCareInterval(coordinator, CARE_FERTILIZE, CONF_FERTILIZE_INTERVAL),
        ]
    )


class PlantCareInterval(PlantCareEntity, NumberEntity):
    """How many days may pass before this care is due."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_mode = NumberMode.BOX
    _attr_native_min_value = 1
    _attr_native_max_value = 365
    _attr_native_step = 1
    _attr_native_unit_of_measurement = UnitOfTime.DAYS
    _attr_icon = "mdi:calendar-clock"

    def __init__(
        self, coordinator: PlantCareCoordinator, care: str, key: str
    ) -> None:
        """Initialize the entity."""
        super().__init__(coordinator, key)
        self._care = care
        self._attr_translation_key = key

    @property
    def native_value(self) -> float:
        """Return the interval in days."""
        data = self.coordinator.data
        if self._care == CARE_WATER:
            return data.water_interval
        return data.fertilize_interval

    async def async_set_native_value(self, value: float) -> None:
        """Change the interval."""
        await self.coordinator.async_set_interval(self._care, value)
