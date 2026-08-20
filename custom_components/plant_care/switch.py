"""Switch that arms the on/off schedule."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import CONF_SWITCH
from .coordinator import PlantCareCoordinator
from .entity import PlantCareEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the schedule switch."""
    coordinator: PlantCareCoordinator = entry.runtime_data
    async_add_entities([PlantCareScheduleSwitch(coordinator)])


class PlantCareScheduleSwitch(PlantCareEntity, SwitchEntity):
    """Whether the schedule drives the configured switch."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_translation_key = "schedule"
    _attr_icon = "mdi:calendar-clock"

    def __init__(self, coordinator: PlantCareCoordinator) -> None:
        """Initialize the entity."""
        super().__init__(coordinator, "schedule")

    @property
    def available(self) -> bool:
        """Only meaningful once a switch has been chosen."""
        return super().available and bool(
            self.coordinator.entry.options.get(CONF_SWITCH)
        )

    @property
    def is_on(self) -> bool:
        """Return whether the schedule is armed."""
        return self.coordinator.data.schedule_enabled

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Arm the schedule."""
        await self.coordinator.async_set_schedule_enabled(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disarm the schedule, leaving the switch as it is."""
        await self.coordinator.async_set_schedule_enabled(False)
