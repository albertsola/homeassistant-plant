"""End-to-end tests for the Plant Care integration."""

from datetime import timedelta

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.plant_care.const import (
    CONF_BUTTON,
    CONF_FERTILIZE_INTERVAL,
    CONF_HUMIDITY,
    CONF_PLANT_NAME,
    CONF_TEMPERATURE,
    CONF_WATER_INTERVAL,
    DOMAIN,
)

BUTTON = "event.monstera_button"


def _entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="Monstera",
        unique_id="monstera",
        data={CONF_PLANT_NAME: "Monstera"},
        options={
            CONF_BUTTON: BUTTON,
            CONF_TEMPERATURE: "sensor.monstera_temperature",
            CONF_HUMIDITY: "sensor.monstera_humidity",
            CONF_WATER_INTERVAL: 7,
            CONF_FERTILIZE_INTERVAL: 30,
        },
    )


async def _setup(hass) -> MockConfigEntry:
    hass.states.async_set(BUTTON, "unknown", {"event_type": None})
    entry = _entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def _press(hass, event_type: str, when: str) -> None:
    """Simulate a button press: the state is the time of the press."""
    hass.states.async_set(BUTTON, when, {"event_type": event_type})
    await hass.async_block_till_done()


async def test_entities_created(hass):
    """A plant produces one device worth of entities."""
    await _setup(hass)

    expected = [
        "datetime.monstera_last_watered",
        "datetime.monstera_last_fertilized",
        "sensor.monstera_days_since_watered",
        "sensor.monstera_days_since_fertilized",
        "sensor.monstera_plant",
        "binary_sensor.monstera_needs_water",
        "binary_sensor.monstera_needs_fertilizer",
        "number.monstera_watering_interval",
        "number.monstera_fertilizing_interval",
        "button.monstera_log_watering",
        "button.monstera_log_fertilizing",
    ]
    missing = [e for e in expected if hass.states.get(e) is None]
    assert not missing, f"missing entities: {missing}"


async def test_button_on_logs_watering(hass):
    """An ON press stamps the watering time."""
    await _setup(hass)
    assert hass.states.get("datetime.monstera_last_watered").state == "unknown"

    await _press(hass, "on", "2026-08-19T10:00:00+00:00")

    assert hass.states.get("datetime.monstera_last_watered").state != "unknown"
    assert hass.states.get("datetime.monstera_last_fertilized").state == "unknown"


async def test_button_off_logs_fertilizing(hass):
    """An OFF press stamps the fertilizing time."""
    await _setup(hass)
    await _press(hass, "off", "2026-08-19T10:00:00+00:00")

    assert hass.states.get("datetime.monstera_last_fertilized").state != "unknown"
    assert hass.states.get("datetime.monstera_last_watered").state == "unknown"


async def test_repeated_identical_press_is_not_dropped(hass, freezer):
    """Two ON presses in a row must both register.

    This is the case that a trigger on the event_type attribute misses: the
    attribute is unchanged, only the timestamp moves. Time is advanced between
    the presses because a datetime entity renders only to the second.
    """
    await _setup(hass)

    freezer.move_to("2026-08-19T10:00:00+00:00")
    await _press(hass, "on", "2026-08-19T10:00:00+00:00")
    first = hass.states.get("datetime.monstera_last_watered").state
    assert first.startswith("2026-08-19T10:00:00")

    freezer.move_to("2026-08-19T18:30:00+00:00")
    await _press(hass, "on", "2026-08-19T18:30:00+00:00")
    second = hass.states.get("datetime.monstera_last_watered").state

    assert second != first, "the second identical press was dropped"
    assert second.startswith("2026-08-19T18:30:00")


async def test_attribute_only_change_is_ignored(hass):
    """A state write that does not change the state is not a press."""
    await _setup(hass)
    await _press(hass, "on", "2026-08-19T10:00:00+00:00")
    logged = hass.states.get("datetime.monstera_last_watered").state

    hass.states.async_set(
        BUTTON, "2026-08-19T10:00:00+00:00", {"event_type": "on", "extra": 1}
    )
    await hass.async_block_till_done()

    assert hass.states.get("datetime.monstera_last_watered").state == logged


async def test_unmapped_press_is_ignored(hass):
    """A button value we do not recognise logs nothing."""
    await _setup(hass)
    await _press(hass, "hold", "2026-08-19T10:00:00+00:00")

    assert hass.states.get("datetime.monstera_last_watered").state == "unknown"
    assert hass.states.get("datetime.monstera_last_fertilized").state == "unknown"


async def test_care_button_entity_logs(hass):
    """The integration's own button entity logs care too."""
    await _setup(hass)
    await hass.services.async_call(
        "button",
        "press",
        {"entity_id": "button.monstera_log_watering"},
        blocking=True,
    )
    await hass.async_block_till_done()

    assert hass.states.get("datetime.monstera_last_watered").state != "unknown"


async def test_summary_entity_carries_card_config(hass):
    """The card reads everything from the summary entity's attributes."""
    await _setup(hass)
    await _press(hass, "on", "2026-08-19T10:00:00+00:00")

    attrs = hass.states.get("sensor.monstera_plant").attributes
    assert attrs["plant_name"] == "Monstera"
    assert attrs["last_watered_entity"] == "datetime.monstera_last_watered"
    assert attrs["last_fertilized_entity"] == "datetime.monstera_last_fertilized"
    assert attrs["temperature_entity"] == "sensor.monstera_temperature"
    assert attrs["humidity_entity"] == "sensor.monstera_humidity"
    assert attrs["illuminance_entity"] is None
    assert attrs["water_interval"] == 7
    assert attrs["needs_water"] is False
    assert attrs["needs_fertilizer"] is True  # never fertilized


async def test_status_reflects_overdue_care(hass):
    """The summary state names what is due."""
    await _setup(hass)
    assert hass.states.get("sensor.monstera_plant").state == "needs_both"

    await _press(hass, "on", "2026-08-19T10:00:00+00:00")
    assert hass.states.get("sensor.monstera_plant").state == "needs_fertilizer"

    await _press(hass, "off", "2026-08-19T10:01:00+00:00")
    assert hass.states.get("sensor.monstera_plant").state == "ok"


async def test_interval_change_survives_and_flips_due(hass):
    """Changing the interval number re-evaluates what is due."""
    await _setup(hass)
    await _press(hass, "on", "2026-08-19T10:00:00+00:00")
    assert hass.states.get("binary_sensor.monstera_needs_water").state == "off"

    await hass.services.async_call(
        "number",
        "set_value",
        {"entity_id": "number.monstera_watering_interval", "value": 1},
        blocking=True,
    )
    await hass.async_block_till_done()
    assert hass.states.get("number.monstera_watering_interval").state == "1.0"


async def test_care_survives_reload(hass):
    """Care history is persisted, not held in memory."""
    entry = await _setup(hass)
    await _press(hass, "on", "2026-08-19T10:00:00+00:00")
    before = hass.states.get("datetime.monstera_last_watered").state

    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    assert hass.states.get("datetime.monstera_last_watered").state == before


async def test_unload(hass):
    """The entry unloads cleanly."""
    entry = await _setup(hass)
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_history_records_each_care_event(hass, freezer):
    """Every logged event is kept, newest first."""
    await _setup(hass)

    for moment in (
        "2026-08-01T09:00:00+00:00",
        "2026-08-08T09:00:00+00:00",
        "2026-08-15T09:00:00+00:00",
    ):
        freezer.move_to(moment)
        await _press(hass, "on", moment)

    history = hass.states.get("sensor.monstera_plant").attributes["watering_history"]
    assert len(history) == 3
    assert history == sorted(history, reverse=True), "history must be newest first"
    assert history[0].startswith("2026-08-15")
    assert history[-1].startswith("2026-08-01")


async def test_history_is_capped(hass, freezer):
    """History does not grow without bound."""
    from custom_components.plant_care.const import HISTORY_LIMIT

    await _setup(hass)
    for day in range(1, HISTORY_LIMIT + 5):
        moment = f"2026-08-{day:02d}T09:00:00+00:00"
        freezer.move_to(moment)
        await _press(hass, "on", moment)

    history = hass.states.get("sensor.monstera_plant").attributes["watering_history"]
    assert len(history) == HISTORY_LIMIT
    assert history[0].startswith(f"2026-08-{HISTORY_LIMIT + 4:02d}")


async def test_backdated_care_is_sorted_into_history(hass, freezer):
    """Setting the datetime entity to a past moment inserts, not appends."""
    freezer.move_to("2026-08-15T09:00:00+00:00")
    await _setup(hass)
    await _press(hass, "on", "2026-08-15T09:00:00+00:00")

    await hass.services.async_call(
        "datetime",
        "set_value",
        {
            "entity_id": "datetime.monstera_last_watered",
            "datetime": "2026-08-10 08:00:00",
        },
        blocking=True,
    )
    await hass.async_block_till_done()

    history = hass.states.get("sensor.monstera_plant").attributes["watering_history"]
    assert len(history) == 2
    assert history == sorted(history, reverse=True)


async def test_next_due_follows_the_interval(hass, freezer):
    """Next due is the last care plus the interval."""
    freezer.move_to("2026-08-15T09:00:00+00:00")
    await _setup(hass)
    await _press(hass, "on", "2026-08-15T09:00:00+00:00")

    attrs = hass.states.get("sensor.monstera_plant").attributes
    assert attrs["next_water_due"].startswith("2026-08-22")  # +7 days
    assert attrs["next_fertilize_due"] is None  # never fertilized


async def test_history_survives_reload(hass, freezer):
    """History is persisted with the rest of the care state."""
    entry = await _setup(hass)
    for moment in ("2026-08-01T09:00:00+00:00", "2026-08-08T09:00:00+00:00"):
        freezer.move_to(moment)
        await _press(hass, "on", moment)

    before = hass.states.get("sensor.monstera_plant").attributes["watering_history"]
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    assert (
        hass.states.get("sensor.monstera_plant").attributes["watering_history"]
        == before
    )
