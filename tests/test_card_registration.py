"""Tests for how the bundled card reaches the frontend."""

from homeassistant.components.frontend import DATA_EXTRA_MODULE_URL
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.plant_care.const import CONF_PLANT_NAME, DOMAIN

CARD_URL = "/plant_care/plant-card.js"


async def test_card_url_registered_after_setup(hass):
    """Setting up a plant registers the card as a frontend module."""
    entry = MockConfigEntry(
        domain=DOMAIN, title="Monstera", data={CONF_PLANT_NAME: "Monstera"}, options={}
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    urls = hass.data[DATA_EXTRA_MODULE_URL].urls
    assert any(CARD_URL in url for url in urls), f"card not registered, urls={set(urls)}"


async def test_card_not_registered_without_a_plant(hass):
    """With no config entry the component never sets up, so no card.

    This is the trap: the card cannot appear in the picker until at least one
    plant has been added.
    """
    await async_setup_component(hass, "frontend", {})
    await hass.async_block_till_done()

    urls = hass.data[DATA_EXTRA_MODULE_URL].urls
    assert not any(CARD_URL in url for url in urls)


async def test_card_file_is_served(hass, hass_client):
    """The card is actually downloadable at its URL."""
    entry = MockConfigEntry(
        domain=DOMAIN, title="Monstera", data={CONF_PLANT_NAME: "Monstera"}, options={}
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    client = await hass_client()
    response = await client.get(CARD_URL)
    assert response.status == 200, f"card URL returned {response.status}"

    body = await response.text()
    assert 'window.customCards' in body
    assert '"plant-card"' in body or "'plant-card'" in body
    assert "getConfigElement" in body


async def test_card_survives_a_second_plant(hass):
    """Registering the card twice must not break the second entry."""
    for name in ("Monstera", "Ficus"):
        entry = MockConfigEntry(
            domain=DOMAIN,
            title=name,
            unique_id=name.lower(),
            data={CONF_PLANT_NAME: name},
            options={},
        )
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    urls = [u for u in hass.data[DATA_EXTRA_MODULE_URL].urls if CARD_URL in u]
    assert len(urls) == 1, f"card registered {len(urls)} times: {urls}"
