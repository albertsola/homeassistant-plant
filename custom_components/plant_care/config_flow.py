"""Config and options flow for Plant Care."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.util import slugify

from .const import (
    CONF_BUTTON,
    CONF_FERTILIZE_EVENT,
    CONF_FERTILIZE_INTERVAL,
    CONF_HUMIDITY,
    CONF_ILLUMINANCE,
    CONF_MOISTURE,
    CONF_PLANT_NAME,
    CONF_TEMPERATURE,
    CONF_WATER_EVENT,
    CONF_WATER_INTERVAL,
    DEFAULT_FERTILIZE_EVENT,
    DEFAULT_FERTILIZE_INTERVAL,
    DEFAULT_WATER_EVENT,
    DEFAULT_WATER_INTERVAL,
    DOMAIN,
)

BUTTON_DOMAINS = ["event", "switch", "input_boolean", "binary_sensor"]


def _entity(domain: str | list[str], device_class: str | None = None):
    """Build an entity picker."""
    config = selector.EntitySelectorConfig(domain=domain)
    if device_class:
        config["device_class"] = device_class
    return selector.EntitySelector(config)


def _days(default: float):
    """Build a day-count picker."""
    return selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=1, max=365, step=1, mode=selector.NumberSelectorMode.BOX
        )
    )


def _optional(key: str, defaults: Mapping[str, Any]) -> vol.Optional:
    """An optional key that prefills with the current value."""
    if (current := defaults.get(key)) is not None:
        return vol.Optional(key, description={"suggested_value": current})
    return vol.Optional(key)


def _schema(
    defaults: Mapping[str, Any], *, include_name: bool, include_intervals: bool
) -> vol.Schema:
    """Build the setup form.

    Intervals appear only during setup: afterwards they live on the number
    entities, so that adjusting one does not reload the integration.
    """
    fields: dict[Any, Any] = {}

    if include_name:
        fields[vol.Required(CONF_PLANT_NAME)] = selector.TextSelector()

    fields[_optional(CONF_BUTTON, defaults)] = _entity(BUTTON_DOMAINS)
    fields[
        vol.Optional(
            CONF_WATER_EVENT,
            default=defaults.get(CONF_WATER_EVENT, DEFAULT_WATER_EVENT),
        )
    ] = selector.TextSelector()
    fields[
        vol.Optional(
            CONF_FERTILIZE_EVENT,
            default=defaults.get(CONF_FERTILIZE_EVENT, DEFAULT_FERTILIZE_EVENT),
        )
    ] = selector.TextSelector()

    fields[_optional(CONF_TEMPERATURE, defaults)] = _entity("sensor", "temperature")
    fields[_optional(CONF_HUMIDITY, defaults)] = _entity("sensor", "humidity")
    fields[_optional(CONF_ILLUMINANCE, defaults)] = _entity("sensor", "illuminance")
    # Soil moisture sensors report inconsistent device classes, so this one is
    # deliberately unfiltered.
    fields[_optional(CONF_MOISTURE, defaults)] = _entity("sensor")

    if include_intervals:
        fields[
            vol.Required(
                CONF_WATER_INTERVAL,
                default=defaults.get(CONF_WATER_INTERVAL, DEFAULT_WATER_INTERVAL),
            )
        ] = _days(DEFAULT_WATER_INTERVAL)
        fields[
            vol.Required(
                CONF_FERTILIZE_INTERVAL,
                default=defaults.get(
                    CONF_FERTILIZE_INTERVAL, DEFAULT_FERTILIZE_INTERVAL
                ),
            )
        ] = _days(DEFAULT_FERTILIZE_INTERVAL)

    return vol.Schema(fields)


class PlantCareConfigFlow(ConfigFlow, domain=DOMAIN):
    """Add a plant."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Collect the plant's name, button and sensors."""
        if user_input is not None:
            name = user_input.pop(CONF_PLANT_NAME)
            await self.async_set_unique_id(slugify(name))
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=name,
                data={CONF_PLANT_NAME: name},
                options=user_input,
            )

        return self.async_show_form(
            step_id="user",
            data_schema=_schema({}, include_name=True, include_intervals=True),
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> PlantCareOptionsFlow:
        """Return the options flow."""
        return PlantCareOptionsFlow()


class PlantCareOptionsFlow(OptionsFlow):
    """Change a plant's button or sensors."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show and save the options."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=_schema(
                self.config_entry.options,
                include_name=False,
                include_intervals=False,
            ),
        )
