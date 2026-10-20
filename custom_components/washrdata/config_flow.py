"""Config and options flow."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigEntryState,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.const import CONF_NAME
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_DEVICE_TYPE,
    CONF_POWER_SENSOR,
    DOMAIN,
    NO_PROGRAM,
    OPT_ANTI_CREASE,
    OPT_END_DELAY_MIN,
    OPT_START_POWER,
    OPT_STOP_POWER,
    build_config,
)
from .cycle_view import async_words, cycle_label, program_text, sparkline
from .engine import CycleRecord, DeviceType

CONF_CYCLE = "cycle"
CONF_PROGRAM = "program"


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
    """Detection settings, and the cycle history to check and correct programs."""

    _cycle: CycleRecord | None = None

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_show_menu(step_id="init", menu_options=["settings", "cycles"])

    async def async_step_settings(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
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
        return self.async_show_form(step_id="settings", data_schema=schema, errors=errors)

    def _history(self) -> list[CycleRecord]:
        if self.config_entry.state is not ConfigEntryState.LOADED:
            return []
        return self.config_entry.runtime_data.tracker.history

    async def async_step_cycles(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        history = self._history()
        if user_input is not None:
            self._cycle = next((c for c in history if c.id == user_input[CONF_CYCLE]), None)
            if self._cycle is not None:
                return await self.async_step_cycle()
        if not history:
            return self.async_abort(reason="no_cycles")

        words = await async_words(self.hass)
        language = self.hass.config.language
        options = [
            selector.SelectOptionDict(value=c.id, label=cycle_label(c, words, language))
            for c in reversed(history)
        ]
        schema = vol.Schema(
            {
                vol.Required(CONF_CYCLE, default=options[0]["value"]): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=options, mode=selector.SelectSelectorMode.DROPDOWN)
                )
            }
        )
        return self.async_show_form(
            step_id="cycles", data_schema=schema, description_placeholders={"count": str(len(history))}
        )

    async def async_step_cycle(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        cycle = self._cycle
        assert cycle is not None
        device = self.config_entry.runtime_data
        words = await async_words(self.hass)
        language = self.hass.config.language
        if user_input is not None:
            program = str(user_input[CONF_PROGRAM]).strip()
            device.tracker.label(cycle.id, None if program in ("", NO_PROGRAM) else program)
            device.changed(save_now=True)
            return await self.async_step_saved()

        options = [
            selector.SelectOptionDict(value=NO_PROGRAM, label=words[NO_PROGRAM]),
            *(selector.SelectOptionDict(value=p, label=p) for p in device.tracker.programs),
        ]
        schema = vol.Schema(
            {
                vol.Required(CONF_PROGRAM, default=cycle.program or NO_PROGRAM): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=options, custom_value=True, mode=selector.SelectSelectorMode.DROPDOWN
                    )
                )
            }
        )
        return self.async_show_form(
            step_id="cycle",
            data_schema=schema,
            description_placeholders={
                "cycle": cycle_label(cycle, words, language, curve=0),
                "peak": f"{round(cycle.peak_power_w)} W",
                "curve": sparkline(cycle, 40),
            },
        )

    async def async_step_saved(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        assert self._cycle is not None
        words = await async_words(self.hass)
        return self.async_show_menu(
            step_id="saved",
            menu_options=["cycles", "done"],
            description_placeholders={"program": program_text(self._cycle, words, self.hass.config.language)},
        )

    async def async_step_done(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        # Labels are saved already; unchanged options do not reload the entry.
        return self.async_create_entry(data=dict(self.config_entry.options))
