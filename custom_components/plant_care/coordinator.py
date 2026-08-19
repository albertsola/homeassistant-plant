"""Care state for a single plant."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .const import (
    CARE_FERTILIZE,
    CARE_WATER,
    CONF_BUTTON,
    CONF_FERTILIZE_EVENT,
    CONF_FERTILIZE_INTERVAL,
    CONF_PLANT_NAME,
    CONF_WATER_EVENT,
    CONF_WATER_INTERVAL,
    DEFAULT_FERTILIZE_EVENT,
    DEFAULT_FERTILIZE_INTERVAL,
    DEFAULT_WATER_EVENT,
    DEFAULT_WATER_INTERVAL,
    DOMAIN,
    EVENT_ALIASES,
    KEY_LAST_FERTILIZED,
    KEY_LAST_WATERED,
    LOGGER,
    STORAGE_VERSION,
)


@dataclass(slots=True)
class PlantCareData:
    """A snapshot of the plant's care state."""

    last_watered: datetime | None
    last_fertilized: datetime | None
    water_interval: float
    fertilize_interval: float

    @staticmethod
    def _elapsed(moment: datetime | None) -> float | None:
        if moment is None:
            return None
        return (dt_util.utcnow() - moment).total_seconds() / 86400

    @property
    def days_since_watered(self) -> float | None:
        """Days since the plant was last watered."""
        return self._elapsed(self.last_watered)

    @property
    def days_since_fertilized(self) -> float | None:
        """Days since the plant was last fertilized."""
        return self._elapsed(self.last_fertilized)

    @property
    def needs_water(self) -> bool:
        """Whether watering is due."""
        elapsed = self.days_since_watered
        return True if elapsed is None else elapsed >= self.water_interval

    @property
    def needs_fertilizer(self) -> bool:
        """Whether fertilizing is due."""
        elapsed = self.days_since_fertilized
        return True if elapsed is None else elapsed >= self.fertilize_interval


class PlantCareCoordinator(DataUpdateCoordinator[PlantCareData]):
    """Owns a plant's care timestamps and watches its button."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            LOGGER,
            name=entry.title,
            # Nothing is polled; the tick keeps "days since" fresh.
            update_interval=timedelta(minutes=1),
            config_entry=entry,
        )
        self.entry = entry
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}"
        )
        self._last_watered: datetime | None = None
        self._last_fertilized: datetime | None = None
        self._water_interval = DEFAULT_WATER_INTERVAL
        self._fertilize_interval = DEFAULT_FERTILIZE_INTERVAL

    @property
    def plant_name(self) -> str:
        """The user-facing plant name."""
        return self.entry.data.get(CONF_PLANT_NAME, self.entry.title)

    async def async_initialize(self) -> None:
        """Load persisted care state, seeding it from the config entry."""
        stored = await self._store.async_load()
        options = self.entry.options

        if stored is None:
            # First run: the intervals chosen during setup become the starting
            # point, and are adjustable from the number entities afterwards.
            self._water_interval = float(
                options.get(CONF_WATER_INTERVAL, DEFAULT_WATER_INTERVAL)
            )
            self._fertilize_interval = float(
                options.get(CONF_FERTILIZE_INTERVAL, DEFAULT_FERTILIZE_INTERVAL)
            )
            await self._async_save()
            return

        self._last_watered = _parse(stored.get(KEY_LAST_WATERED))
        self._last_fertilized = _parse(stored.get(KEY_LAST_FERTILIZED))
        self._water_interval = float(
            stored.get(CONF_WATER_INTERVAL, DEFAULT_WATER_INTERVAL)
        )
        self._fertilize_interval = float(
            stored.get(CONF_FERTILIZE_INTERVAL, DEFAULT_FERTILIZE_INTERVAL)
        )

    async def _async_update_data(self) -> PlantCareData:
        """Return the current snapshot; the tick only refreshes elapsed time."""
        return self._snapshot()

    def _snapshot(self) -> PlantCareData:
        return PlantCareData(
            last_watered=self._last_watered,
            last_fertilized=self._last_fertilized,
            water_interval=self._water_interval,
            fertilize_interval=self._fertilize_interval,
        )

    async def _async_save(self) -> None:
        await self._store.async_save(
            {
                KEY_LAST_WATERED: _dump(self._last_watered),
                KEY_LAST_FERTILIZED: _dump(self._last_fertilized),
                CONF_WATER_INTERVAL: self._water_interval,
                CONF_FERTILIZE_INTERVAL: self._fertilize_interval,
            }
        )

    async def async_log_care(self, care: str, when: datetime | None = None) -> None:
        """Record a care event, defaulting to now."""
        moment = dt_util.as_utc(when) if when else dt_util.utcnow()
        if care == CARE_WATER:
            self._last_watered = moment
        else:
            self._last_fertilized = moment
        await self._async_save()
        self.async_set_updated_data(self._snapshot())

    async def async_set_interval(self, care: str, days: float) -> None:
        """Change a care interval."""
        if care == CARE_WATER:
            self._water_interval = days
        else:
            self._fertilize_interval = days
        await self._async_save()
        self.async_set_updated_data(self._snapshot())

    @callback
    def async_watch_button(self) -> None:
        """Subscribe to the configured button, if there is one."""
        button = self.entry.options.get(CONF_BUTTON)
        if not button:
            return
        self.entry.async_on_unload(
            async_track_state_change_event(
                self.hass, [button], self._handle_button_event
            )
        )

    @callback
    def _handle_button_event(self, event: Event) -> None:
        """Log care when the button reports a press."""
        new_state = event.data["new_state"]
        old_state = event.data["old_state"]

        # old_state is None when the entity first appears (including on every
        # restart) — that is not a press.
        if new_state is None or old_state is None:
            return
        if new_state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
            return
        # An `event` entity's state is the timestamp of the last press, so it
        # changes even when the same button is pressed twice. Attribute-only
        # updates are not presses.
        if new_state.state == old_state.state:
            return

        if new_state.domain == "event":
            token = new_state.attributes.get("event_type")
        else:
            token = new_state.state

        care = self._match_care(token)
        if care is None:
            LOGGER.debug(
                "%s: ignoring unmapped button value %r from %s",
                self.plant_name,
                token,
                new_state.entity_id,
            )
            return

        self.entry.async_create_task(
            self.hass, self.async_log_care(care), eager_start=False
        )

    def _match_care(self, token: Any) -> str | None:
        """Map a button value onto a care type."""
        if token is None:
            return None
        value = str(token).lower()
        options = self.entry.options
        wanted = {
            CARE_WATER: str(
                options.get(CONF_WATER_EVENT, DEFAULT_WATER_EVENT)
            ).lower(),
            CARE_FERTILIZE: str(
                options.get(CONF_FERTILIZE_EVENT, DEFAULT_FERTILIZE_EVENT)
            ).lower(),
        }
        for care, configured in wanted.items():
            if value == configured:
                return care
        for care, configured in wanted.items():
            if value in EVENT_ALIASES.get(configured, frozenset()):
                return care
        return None


def _parse(raw: Any) -> datetime | None:
    """Read a stored ISO timestamp."""
    if not raw:
        return None
    return dt_util.parse_datetime(raw)


def _dump(moment: datetime | None) -> str | None:
    """Write a timestamp for storage."""
    return moment.isoformat() if moment else None
