"""Config and options flow."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlowWithReload
from homeassistant.const import CONF_NAME
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_DEVICE_TYPE,
    CONF_POWER_SENSOR,
    DOMAIN,
    OPT_ANTI_CREASE,
    OPT_END_DELAY_MIN,
    OPT_START_POWER,
    OPT_STOP_POWER,
    build_config,
)
from .engine import DeviceType


def _watts() -> selector.NumberSelector:
    return selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=0, max=500, step=0.5, unit_of_measurement="W", mode=selector.NumberSelectorMode.BOX
        )
    )


class WashRDataConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_POWER_SENSOR])
            self._abort_if_unique_id_configured()
            return self.async_create_entry(title=user_input[CONF_NAME], data=user_input)

        schema = vol.Schema(
            {
                vol.Required(CONF_NAME): selector.TextSelector(),
                vol.Required(CONF_DEVICE_TYPE, default=DeviceType.WASHER.value): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[t.value for t in DeviceType],
                        translation_key=CONF_DEVICE_TYPE,
                        mode=selector.SelectSelectorMode.LIST,
                    )
                ),
                vol.Required(CONF_POWER_SENSOR): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor", device_class=SensorDeviceClass.POWER)
                ),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> WashRDataOptionsFlow:
        return WashRDataOptionsFlow()


class WashRDataOptionsFlow(OptionsFlowWithReload):
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            if user_input[OPT_STOP_POWER] > user_input[OPT_START_POWER]:
                errors["base"] = "stop_above_start"
            else:
                return self.async_create_entry(data=user_input)

        config = build_config(
            DeviceType(self.config_entry.data[CONF_DEVICE_TYPE]), dict(self.config_entry.options)
        )
        schema = vol.Schema(
            {
                vol.Required(OPT_START_POWER, default=config.start_power_w): _watts(),
                vol.Required(OPT_STOP_POWER, default=config.stop_power_w): _watts(),
                vol.Required(OPT_END_DELAY_MIN, default=config.end_delay_s / 60): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=1,
                        max=120,
                        step=0.5,
                        unit_of_measurement="min",
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
                vol.Required(OPT_ANTI_CREASE, default=config.anti_crease): selector.BooleanSelector(),
            }
        )
        if user_input is not None:
            schema = self.add_suggested_values_to_schema(schema, user_input)
        return self.async_show_form(step_id="init", data_schema=schema, errors=errors)
