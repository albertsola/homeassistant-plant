"""The Plant Care integration."""

from __future__ import annotations

from pathlib import Path

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.start import async_at_start
from homeassistant.helpers.storage import Store
from homeassistant.helpers.typing import ConfigType

from .const import (
    CARD_FILENAME,
    CARD_URL_BASE,
    CARD_VERSION,
    DOMAIN,
    PLATFORMS,
    STORAGE_VERSION,
)
from .coordinator import PlantCareCoordinator

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

PlantCareConfigEntry = ConfigEntry[PlantCareCoordinator]

_CARD_REGISTERED = f"{DOMAIN}_card_registered"


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Serve the bundled card and register it with the frontend."""
    await _async_register_card(hass)
    return True


async def _async_register_card(hass: HomeAssistant) -> None:
    """Expose www/ and add the card as a frontend module.

    This is what removes the manual "add a Lovelace resource" step.
    """
    if hass.data.get(_CARD_REGISTERED):
        return
    hass.data[_CARD_REGISTERED] = True

    await hass.http.async_register_static_paths(
        [
            StaticPathConfig(
                CARD_URL_BASE, str(Path(__file__).parent / "www"), cache_headers=False
            )
        ]
    )
    # The version query busts the browser cache when the card is updated.
    add_extra_js_url(hass, f"{CARD_URL_BASE}/{CARD_FILENAME}?v={CARD_VERSION}")


async def async_setup_entry(hass: HomeAssistant, entry: PlantCareConfigEntry) -> bool:
    """Set up a plant from a config entry."""
    coordinator = PlantCareCoordinator(hass, entry)
    await coordinator.async_initialize()
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    coordinator.async_watch_button()
    coordinator.async_schedule_switch()
    entry.async_on_unload(coordinator.async_stop_schedule)
    # Bring the switch in line with the schedule once HA is up, so a restart
    # mid-window does not leave it in the wrong state.
    entry.async_on_unload(async_at_start(hass, coordinator.async_sync_switch))
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: PlantCareConfigEntry) -> bool:
    """Unload a plant."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_reload_entry(hass: HomeAssistant, entry: PlantCareConfigEntry) -> None:
    """Reload when the options change, so a new button is picked up."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Delete the plant's stored care history when it is removed."""
    await Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}").async_remove()
