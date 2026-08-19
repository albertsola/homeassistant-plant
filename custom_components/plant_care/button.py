"""Buttons to log care from the UI or an automation."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import CARE_FERTILIZE, CARE_WATER
from .coordinator import PlantCareCoordinator
from .entity import PlantCareEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the care buttons."""
    coordinator: PlantCareCoordinator = entry.runtime_data
    async_add_entities(
        [
            PlantCareButton(coordinator, CARE_WATER, "log_watering", "mdi:watering-can"),
            PlantCareButton(coordinator, CARE_FERTILIZE, "log_fertilizing", "mdi:leaf"),
        ]
    )


class PlantCareButton(PlantCareEntity, ButtonEntity):
    """Press to record care as happening now."""

    def __init__(
        self, coordinator: PlantCareCoordinator, care: str, key: str, icon: str
    ) -> None:
        """Initialize the entity."""
        super().__init__(coordinator, key)
        self._care = care
        self._attr_translation_key = key
        self._attr_icon = icon

    async def async_press(self) -> None:
        """Log the care event."""
        await self.coordinator.async_log_care(self._care)
