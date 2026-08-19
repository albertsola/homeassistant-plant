"""Shared entity base for Plant Care."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import PlantCareCoordinator


class PlantCareEntity(CoordinatorEntity[PlantCareCoordinator]):
    """Base entity: every plant is one device."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: PlantCareCoordinator, key: str) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.entry.entry_id)},
            name=coordinator.plant_name,
            manufacturer="Plant Care",
            model="Plant",
        )
