"""Care state for a single plant."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from functools import partial
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_change,
)
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
    CONF_SCHEDULE_OFF,
    CONF_SCHEDULE_ON,
    CONF_SWITCH,
    CONF_WATER_EVENT,
    CONF_WATER_INTERVAL,
    DEFAULT_FERTILIZE_EVENT,
    DEFAULT_FERTILIZE_INTERVAL,
    DEFAULT_SCHEDULE_OFF,
    DEFAULT_SCHEDULE_ON,
    DEFAULT_WATER_EVENT,
    DEFAULT_WATER_INTERVAL,
    DOMAIN,
    EVENT_ALIASES,
    HISTORY_LIMIT,
    KEY_FERTILIZE_HISTORY,
    KEY_LAST_FERTILIZED,
    KEY_LAST_WATERED,
    KEY_OFF_TIME,
    KEY_ON_TIME,
    KEY_SCHEDULE_ENABLED,
    KEY_WATER_HISTORY,
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
    water_history: list[datetime] = field(default_factory=list)
    fertilize_history: list[datetime] = field(default_factory=list)
    on_time: time | None = None
    off_time: time | None = None
    schedule_enabled: bool = False

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
    def next_water_due(self) -> datetime | None:
        """When watering falls due, or None if it never happened."""
        if self.last_watered is None:
            return None
        return self.last_watered + timedelta(days=self.water_interval)

    @property
    def next_fertilize_due(self) -> datetime | None:
        """When fertilizing falls due, or None if it never happened."""
        if self.last_fertilized is None:
            return None
        return self.last_fertilized + timedelta(days=self.fertilize_interval)

    @property
    def schedule_window(self) -> str | None:
        """The schedule as "08:00 – 20:00", for display."""
        if self.on_time is None or self.off_time is None:
            return None
        return (
            f"{self.on_time.strftime('%H:%M')} – {self.off_time.strftime('%H:%M')}"
        )

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
        self._water_history: list[datetime] = []
        self._fertilize_history: list[datetime] = []
        self._water_interval = DEFAULT_WATER_INTERVAL
        self._fertilize_interval = DEFAULT_FERTILIZE_INTERVAL
        self._on_time = _parse_time(DEFAULT_SCHEDULE_ON)
        self._off_time = _parse_time(DEFAULT_SCHEDULE_OFF)
        self._schedule_enabled = False
        self._schedule_unsubs: list[CALLBACK_TYPE] = []

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
            self._on_time = _parse_time(
                options.get(CONF_SCHEDULE_ON, DEFAULT_SCHEDULE_ON)
            )
            self._off_time = _parse_time(
                options.get(CONF_SCHEDULE_OFF, DEFAULT_SCHEDULE_OFF)
            )
            # Armed only once a switch has actually been chosen.
            self._schedule_enabled = bool(options.get(CONF_SWITCH))
            await self._async_save()
            return

        self._last_watered = _parse(stored.get(KEY_LAST_WATERED))
        self._last_fertilized = _parse(stored.get(KEY_LAST_FERTILIZED))
        # History was added after the first release: seed it from the single
        # timestamp those installs already have, so the panel is not empty.
        self._water_history = _parse_history(
            stored.get(KEY_WATER_HISTORY), self._last_watered
        )
        self._fertilize_history = _parse_history(
            stored.get(KEY_FERTILIZE_HISTORY), self._last_fertilized
        )
        self._water_interval = float(
            stored.get(CONF_WATER_INTERVAL, DEFAULT_WATER_INTERVAL)
        )
        self._fertilize_interval = float(
            stored.get(CONF_FERTILIZE_INTERVAL, DEFAULT_FERTILIZE_INTERVAL)
        )
        self._on_time = _parse_time(stored.get(KEY_ON_TIME, DEFAULT_SCHEDULE_ON))
        self._off_time = _parse_time(stored.get(KEY_OFF_TIME, DEFAULT_SCHEDULE_OFF))
        self._schedule_enabled = bool(
            stored.get(KEY_SCHEDULE_ENABLED, bool(options.get(CONF_SWITCH)))
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
            water_history=list(self._water_history),
            fertilize_history=list(self._fertilize_history),
            on_time=self._on_time,
            off_time=self._off_time,
            schedule_enabled=self._schedule_enabled,
        )

    async def _async_save(self) -> None:
        await self._store.async_save(
            {
                KEY_LAST_WATERED: _dump(self._last_watered),
                KEY_LAST_FERTILIZED: _dump(self._last_fertilized),
                KEY_WATER_HISTORY: [_dump(m) for m in self._water_history],
                KEY_FERTILIZE_HISTORY: [_dump(m) for m in self._fertilize_history],
                CONF_WATER_INTERVAL: self._water_interval,
                CONF_FERTILIZE_INTERVAL: self._fertilize_interval,
                KEY_ON_TIME: _dump_time(self._on_time),
                KEY_OFF_TIME: _dump_time(self._off_time),
                KEY_SCHEDULE_ENABLED: self._schedule_enabled,
            }
        )

    async def async_log_care(self, care: str, when: datetime | None = None) -> None:
        """Record a care event, defaulting to now."""
        moment = dt_util.as_utc(when) if when else dt_util.utcnow()
        if care == CARE_WATER:
            self._last_watered = moment
            self._water_history = _add_to_history(self._water_history, moment)
        else:
            self._last_fertilized = moment
            self._fertilize_history = _add_to_history(
                self._fertilize_history, moment
            )
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

    async def async_set_schedule_time(self, key: str, value: time) -> None:
        """Move one edge of the schedule."""
        if key == KEY_ON_TIME:
            self._on_time = value
        else:
            self._off_time = value
        await self._async_save()
        self.async_set_updated_data(self._snapshot())
        self.async_schedule_switch()

    async def async_set_schedule_enabled(self, enabled: bool) -> None:
        """Arm or disarm the schedule."""
        self._schedule_enabled = enabled
        await self._async_save()
        self.async_set_updated_data(self._snapshot())
        self.async_schedule_switch()
        if enabled:
            # Arming should take effect now, not at the next edge.
            await self.async_sync_switch()

    @callback
    def async_schedule_switch(self) -> None:
        """(Re)register the on and off triggers."""
        self.async_stop_schedule()

        target = self.entry.options.get(CONF_SWITCH)
        if not (
            self._schedule_enabled
            and target
            and self._on_time is not None
            and self._off_time is not None
        ):
            return

        for moment, turn_on in ((self._on_time, True), (self._off_time, False)):
            self._schedule_unsubs.append(
                async_track_time_change(
                    self.hass,
                    partial(self._handle_schedule_tick, turn_on),
                    hour=moment.hour,
                    minute=moment.minute,
                    second=moment.second,
                )
            )

    @callback
    def async_stop_schedule(self) -> None:
        """Drop the schedule triggers."""
        for unsub in self._schedule_unsubs:
            unsub()
        self._schedule_unsubs.clear()

    @callback
    def _handle_schedule_tick(self, turn_on: bool, now: datetime) -> None:
        """A scheduled edge was reached."""
        self.entry.async_create_task(
            self.hass, self._async_set_switch(turn_on), eager_start=False
        )

    async def _async_set_switch(self, turn_on: bool) -> None:
        """Drive the configured switch.

        homeassistant.turn_on/turn_off rather than switch.* so the same code
        works for a light, an input_boolean or a fan.
        """
        target = self.entry.options.get(CONF_SWITCH)
        if not target:
            return
        LOGGER.debug(
            "%s: turning %s %s", self.plant_name, "on" if turn_on else "off", target
        )
        await self.hass.services.async_call(
            "homeassistant",
            "turn_on" if turn_on else "turn_off",
            {"entity_id": target},
            blocking=False,
        )

    async def async_sync_switch(self, *_: Any) -> None:
        """Put the switch into the state the schedule implies right now.

        Without this a restart at midday would leave a grow light off until
        the next evening edge.
        """
        target = self.entry.options.get(CONF_SWITCH)
        if not (self._schedule_enabled and target):
            return
        await self._async_set_switch(self.is_within_schedule())

    @callback
    def is_within_schedule(self, moment: time | None = None) -> bool:
        """Whether the switch should currently be on.

        Handles a window that crosses midnight, e.g. on 20:00, off 06:00.
        """
        if self._on_time is None or self._off_time is None:
            return False
        current = moment or dt_util.now().time()
        if self._on_time <= self._off_time:
            return self._on_time <= current < self._off_time
        return current >= self._on_time or current < self._off_time

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


def _parse_time(raw: Any) -> time | None:
    """Read a stored "HH:MM:SS"."""
    if isinstance(raw, time):
        return raw
    if not raw:
        return None
    return dt_util.parse_time(str(raw))


def _dump_time(moment: time | None) -> str | None:
    """Write a time for storage."""
    return moment.isoformat() if moment else None


def _add_to_history(
    history: list[datetime], moment: datetime
) -> list[datetime]:
    """Record an event, newest first, without duplicates.

    Sorted rather than prepended because care can be backdated by setting the
    datetime entity to a past moment.
    """
    moments = {moment, *history}
    return sorted(moments, reverse=True)[:HISTORY_LIMIT]


def _parse_history(raw: Any, fallback: datetime | None) -> list[datetime]:
    """Read a stored history, falling back to a single known timestamp."""
    if raw:
        parsed = [m for m in (_parse(item) for item in raw) if m is not None]
        if parsed:
            return sorted(set(parsed), reverse=True)[:HISTORY_LIMIT]
    return [fallback] if fallback else []


def _parse(raw: Any) -> datetime | None:
    """Read a stored ISO timestamp."""
    if not raw:
        return None
    return dt_util.parse_datetime(raw)


def _dump(moment: datetime | None) -> str | None:
    """Write a timestamp for storage."""
    return moment.isoformat() if moment else None
