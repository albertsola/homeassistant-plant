"""Binary sensors flagging care that is due."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
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
    """Set up the needs-care sensors."""
    coordinator: PlantCareCoordinator = entry.runtime_data
    async_add_entities(
        [
            PlantCareDue(coordinator, CARE_WATER, "needs_water", "mdi:water-alert"),
            PlantCareDue(
                coordinator, CARE_FERTILIZE, "needs_fertilizer", "mdi:leaf-off"
            ),
        ]
    )


class PlantCareDue(PlantCareEntity, BinarySensorEntity):
    """On when this care is overdue."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(
        self, coordinator: PlantCareCoordinator, care: str, key: str, icon: str
    ) -> None:
        """Initialize the entity."""
        super().__init__(coordinator, key)
        self._care = care
        self._attr_translation_key = key
        self._attr_icon = icon

    @property
    def is_on(self) -> bool:
        """Return whether the care is due."""
        data = self.coordinator.data
        if self._care == CARE_WATER:
            return data.needs_water
        return data.needs_fertilizer
