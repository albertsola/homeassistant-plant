"""Tests for the scheduled switch."""

from datetime import time

from freezegun.api import FrozenDateTimeFactory
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.plant_care.const import (
    CONF_FERTILIZE_INTERVAL,
    CONF_PLANT_NAME,
    CONF_SCHEDULE_OFF,
    CONF_SCHEDULE_ON,
    CONF_SWITCH,
    CONF_WATER_INTERVAL,
    DOMAIN,
)

TARGET = "input_boolean.grow_light"


async def _setup(hass, timezone: str = "UTC", **overrides) -> MockConfigEntry:
    """Set up a plant with a grow light on a schedule.

    The schedule fires on local time, so the tests pin the zone rather than
    inherit the harness default of US/Pacific.
    """
    await hass.config.async_set_time_zone(timezone)
    await async_setup_component(hass, "homeassistant", {})
    await async_setup_component(
        hass, "input_boolean", {"input_boolean": {"grow_light": {"name": "Grow light"}}}
    )

    options = {
        CONF_SWITCH: TARGET,
        CONF_SCHEDULE_ON: "08:00:00",
        CONF_SCHEDULE_OFF: "20:00:00",
        CONF_WATER_INTERVAL: 7,
        CONF_FERTILIZE_INTERVAL: 30,
    }
    options.update(overrides)

    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Monstera",
        unique_id="monstera",
        data={CONF_PLANT_NAME: "Monstera"},
        options=options,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def _tick(hass, freezer: FrozenDateTimeFactory, moment: str) -> None:
    """Advance the clock and let the time triggers fire."""
    freezer.move_to(moment)
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()


async def test_schedule_entities_created(hass):
    """The schedule exposes its own controls."""
    await _setup(hass)

    for entity_id in (
        "time.monstera_on_time",
        "time.monstera_off_time",
        "switch.monstera_schedule",
    ):
        assert hass.states.get(entity_id) is not None, f"missing {entity_id}"

    assert hass.states.get("time.monstera_on_time").state == "08:00:00"
    assert hass.states.get("time.monstera_off_time").state == "20:00:00"
    assert hass.states.get("switch.monstera_schedule").state == "on"


async def test_switch_follows_the_schedule(hass, freezer):
    """The target is driven on at the on time and off at the off time."""
    freezer.move_to("2026-08-20T07:00:00+00:00")
    await _setup(hass)
    assert hass.states.get(TARGET).state == "off"

    await _tick(hass, freezer, "2026-08-20T08:00:00+00:00")
    assert hass.states.get(TARGET).state == "on", "on time did not fire"

    await _tick(hass, freezer, "2026-08-20T20:00:00+00:00")
    assert hass.states.get(TARGET).state == "off", "off time did not fire"


async def test_state_is_synced_on_startup(hass, freezer):
    """A restart inside the window leaves the switch on, not waiting for 20:00."""
    freezer.move_to("2026-08-20T12:00:00+00:00")
    await _setup(hass)

    assert hass.states.get(TARGET).state == "on"


async def test_state_is_synced_outside_the_window(hass, freezer):
    """A restart outside the window turns the switch off."""
    freezer.move_to("2026-08-20T23:00:00+00:00")
    await _setup(hass)

    assert hass.states.get(TARGET).state == "off"


async def test_window_may_cross_midnight(hass, freezer):
    """on 20:00 / off 06:00 means the night, not an empty window."""
    freezer.move_to("2026-08-20T22:00:00+00:00")
    entry = await _setup(
        hass, **{CONF_SCHEDULE_ON: "20:00:00", CONF_SCHEDULE_OFF: "06:00:00"}
    )
    coordinator = entry.runtime_data

    assert coordinator.is_within_schedule(time(22, 0)) is True
    assert coordinator.is_within_schedule(time(3, 0)) is True
    assert coordinator.is_within_schedule(time(12, 0)) is False
    assert hass.states.get(TARGET).state == "on"


async def test_disarming_stops_the_schedule(hass, freezer):
    """With the schedule off, the edges do nothing."""
    freezer.move_to("2026-08-20T07:00:00+00:00")
    await _setup(hass)

    await hass.services.async_call(
        "switch",
        "turn_off",
        {"entity_id": "switch.monstera_schedule"},
        blocking=True,
    )
    await hass.async_block_till_done()

    await _tick(hass, freezer, "2026-08-20T08:00:00+00:00")
    assert hass.states.get(TARGET).state == "off", "disarmed schedule still fired"


async def test_arming_applies_immediately(hass, freezer):
    """Arming mid-window should not wait for the next edge."""
    freezer.move_to("2026-08-20T12:00:00+00:00")
    await _setup(hass)

    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": "switch.monstera_schedule"}, blocking=True
    )
    await hass.services.async_call(
        "input_boolean", "turn_off", {"entity_id": TARGET}, blocking=True
    )
    await hass.async_block_till_done()
    assert hass.states.get(TARGET).state == "off"

    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": "switch.monstera_schedule"}, blocking=True
    )
    await hass.async_block_till_done()

    assert hass.states.get(TARGET).state == "on"


async def test_changing_the_time_moves_the_edge(hass, freezer):
    """Setting the time entity re-registers the trigger."""
    freezer.move_to("2026-08-20T07:00:00+00:00")
    await _setup(hass)

    await hass.services.async_call(
        "time",
        "set_value",
        {"entity_id": "time.monstera_on_time", "time": "09:30:00"},
        blocking=True,
    )
    await hass.async_block_till_done()
    assert hass.states.get("time.monstera_on_time").state == "09:30:00"

    await _tick(hass, freezer, "2026-08-20T08:00:00+00:00")
    assert hass.states.get(TARGET).state == "off", "old on time still fired"

    await _tick(hass, freezer, "2026-08-20T09:30:00+00:00")
    assert hass.states.get(TARGET).state == "on", "new on time did not fire"


async def test_schedule_survives_reload(hass, freezer):
    """Times and armed state are persisted."""
    freezer.move_to("2026-08-20T07:00:00+00:00")
    entry = await _setup(hass)

    await hass.services.async_call(
        "time",
        "set_value",
        {"entity_id": "time.monstera_off_time", "time": "21:15:00"},
        blocking=True,
    )
    await hass.async_block_till_done()

    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    assert hass.states.get("time.monstera_off_time").state == "21:15:00"


async def test_schedule_switch_unavailable_without_a_target(hass):
    """Nothing to schedule means the switch says so."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Fern",
        unique_id="fern",
        data={CONF_PLANT_NAME: "Fern"},
        options={},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert hass.states.get("switch.fern_schedule").state == "unavailable"


async def test_summary_entity_exposes_the_schedule(hass, freezer):
    """The card reads the schedule from the summary entity."""
    freezer.move_to("2026-08-20T12:00:00+00:00")
    await _setup(hass)

    attrs = hass.states.get("sensor.monstera_plant").attributes
    assert attrs["switch_entity"] == TARGET
    assert attrs["schedule_enabled"] is True
    assert attrs["schedule_on"] == "08:00:00"
    assert attrs["schedule_off"] == "20:00:00"
    assert attrs["schedule_window"] == "08:00 – 20:00"


async def test_schedule_fires_on_local_time(hass, freezer):
    """08:00 means 08:00 where the plant is, not 08:00 UTC."""
    # Madrid is UTC+2 in August, so local 08:00 is 06:00 UTC.
    freezer.move_to("2026-08-20T04:00:00+00:00")  # 06:00 local, before the edge
    await _setup(hass, timezone="Europe/Madrid")
    assert hass.states.get(TARGET).state == "off"

    await _tick(hass, freezer, "2026-08-20T06:00:00+00:00")  # 08:00 local
    assert hass.states.get(TARGET).state == "on", "did not fire at 08:00 local"


async def test_schedule_ignores_utc_offset_when_syncing(hass, freezer):
    """Startup sync also uses local time."""
    # 22:00 UTC is midnight local in Madrid — outside an 08:00-20:00 window.
    freezer.move_to("2026-08-20T22:00:00+00:00")
    await _setup(hass, timezone="Europe/Madrid")

    assert hass.states.get(TARGET).state == "off"
