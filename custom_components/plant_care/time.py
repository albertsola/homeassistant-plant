"""The schedule's on and off times."""

from __future__ import annotations

from datetime import time

from homeassistant.components.time import TimeEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import KEY_OFF_TIME, KEY_ON_TIME
from .coordinator import PlantCareCoordinator
from .entity import PlantCareEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the schedule times."""
    coordinator: PlantCareCoordinator = entry.runtime_data
    async_add_entities(
        [
            PlantCareScheduleTime(coordinator, KEY_ON_TIME, "mdi:weather-sunny"),
            PlantCareScheduleTime(coordinator, KEY_OFF_TIME, "mdi:weather-night"),
        ]
    )


class PlantCareScheduleTime(PlantCareEntity, TimeEntity):
    """One edge of the switch schedule."""

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self, coordinator: PlantCareCoordinator, key: str, icon: str
    ) -> None:
        """Initialize the entity."""
        super().__init__(coordinator, key)
        self._key = key
        self._attr_translation_key = key
        self._attr_icon = icon

    @property
    def native_value(self) -> time | None:
        """Return the configured time."""
        data = self.coordinator.data
        return data.on_time if self._key == KEY_ON_TIME else data.off_time

    async def async_set_value(self, value: time) -> None:
        """Move this edge of the schedule."""
        await self.coordinator.async_set_schedule_time(self._key, value)
