"""Config and options flow."""

from __future__ import annotations

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.washrdata.const import DOMAIN

from .conftest import POWER


async def test_user_flow_creates_entry(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"name": "Dryer", "device_type": "dryer", "power_sensor": POWER}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Dryer"
    assert result["data"]["device_type"] == "dryer"


async def test_same_sensor_twice_aborts(hass: HomeAssistant, washer_entry: MockConfigEntry) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"name": "Again", "device_type": "washer", "power_sensor": POWER}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_options_flow_validates_and_reloads(hass: HomeAssistant, washer_entry: MockConfigEntry) -> None:
    hass.states.async_set(POWER, "0", {"unit_of_measurement": "W"})
    assert await hass.config_entries.async_setup(washer_entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(washer_entry.entry_id)
    assert result["type"] is FlowResultType.FORM

    bad = {"start_power_w": 5, "stop_power_w": 10, "end_delay_min": 5, "anti_crease": False}
    result = await hass.config_entries.options.async_configure(result["flow_id"], bad)
    assert result["errors"] == {"base": "stop_above_start"}

    good = {"start_power_w": 12, "stop_power_w": 6, "end_delay_min": 8, "anti_crease": True}
    result = await hass.config_entries.options.async_configure(result["flow_id"], good)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()

    config = washer_entry.runtime_data.config
    assert config.start_power_w == 12
    assert config.end_delay_s == 480
    assert config.anti_crease
