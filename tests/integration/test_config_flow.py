"""Config and options flow."""

from __future__ import annotations

from unittest.mock import patch

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.washrdata.const import DOMAIN
from custom_components.washrdata.cycle_view import sparkline
from custom_components.washrdata.engine import CycleRecord, LabelSource

from .conftest import POWER


async def _step(hass: HomeAssistant, result: dict, user_input: dict) -> dict:
    return await hass.config_entries.options.async_configure(result["flow_id"], user_input)


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
    assert result["type"] is FlowResultType.MENU
    result = await _step(hass, result, {"next_step_id": "settings"})
    assert result["type"] is FlowResultType.FORM

    bad = {"start_power_w": 5, "stop_power_w": 10, "end_delay_min": 5, "anti_crease": False}
    result = await _step(hass, result, bad)
    assert result["errors"] == {"base": "stop_above_start"}

    good = {"start_power_w": 12, "stop_power_w": 6, "end_delay_min": 8, "anti_crease": True}
    result = await _step(hass, result, good)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()

    config = washer_entry.runtime_data.config
    assert config.start_power_w == 12
    assert config.end_delay_s == 480
    assert config.anti_crease


def _cycle(start: float, minutes: float, program: str | None = None, **kw) -> CycleRecord:
    trace = [(0.0, 2000.0), (minutes * 20, 50.0), (minutes * 50, 400.0), (minutes * 60 - 60, 5.0)]
    return CycleRecord(
        start=start,
        end=start + minutes * 60,
        energy_wh=900,
        peak_power_w=2000,
        program=program,
        trace=trace,
        **kw,
    )


def test_sparkline_keeps_short_spikes_and_scales_to_peak() -> None:
    cycle = CycleRecord(start=0, end=1000, trace=[(0.0, 10.0), (500.0, 1000.0), (510.0, 10.0)])
    line = sparkline(cycle, 10)
    assert line == "▁▁▁▁▁█▁▁▁▁"
    assert sparkline(CycleRecord(start=0, end=10), 5) == ""


async def test_options_flow_lists_and_corrects_cycles(
    hass: HomeAssistant, washer_entry: MockConfigEntry
) -> None:
    hass.states.async_set(POWER, "0", {"unit_of_measurement": "W"})
    assert await hass.config_entries.async_setup(washer_entry.entry_id)
    await hass.async_block_till_done()
    tracker = washer_entry.runtime_data.tracker
    tracker.programs = ["Cotton 40", "Quick"]
    old = _cycle(1_700_000_000, 112, "Cotton 40", program_source=LabelSource.AUTO, match_confidence=0.82)
    new = _cycle(1_700_100_000, 30)
    tracker.history = [old, new]

    result = await hass.config_entries.options.async_init(washer_entry.entry_id)
    result = await _step(hass, result, {"next_step_id": "cycles"})
    assert result["type"] is FlowResultType.FORM
    options = result["data_schema"].schema["cycle"].config["options"]
    assert [o["value"] for o in options] == [new.id, old.id]
    assert "1:52 h" in options[1]["label"]
    assert "0.90 kWh" in options[1]["label"]
    assert "Cotton 40 (recognised, 82 %)" in options[1]["label"]
    assert "No program" in options[0]["label"]

    result = await _step(hass, result, {"cycle": old.id})
    assert result["step_id"] == "cycle"
    assert result["description_placeholders"]["peak"] == "2000 W"
    assert len(result["description_placeholders"]["curve"]) == 40

    with patch("homeassistant.config_entries.ConfigEntries.async_reload") as reload:
        result = await _step(hass, result, {"program": "Quick"})
        assert result["type"] is FlowResultType.MENU
        assert result["description_placeholders"]["program"] == "Quick (set by hand)"
        assert old.program == "Quick" and old.program_source == LabelSource.MANUAL

        result = await _step(hass, result, {"next_step_id": "cycles"})
        result = await _step(hass, result, {"cycle": new.id})
        result = await _step(hass, result, {"program": "Delicates"})
        assert new.program == "Delicates"
        assert "Delicates" in tracker.programs

        result = await _step(hass, result, {"next_step_id": "cycles"})
        result = await _step(hass, result, {"cycle": new.id})
        result = await _step(hass, result, {"program": "none"})
        assert new.program is None

        result = await _step(hass, result, {"next_step_id": "done"})
        assert result["type"] is FlowResultType.CREATE_ENTRY
        await hass.async_block_till_done()
        reload.assert_not_called()


async def test_options_flow_without_cycles_aborts(hass: HomeAssistant, washer_entry: MockConfigEntry) -> None:
    hass.states.async_set(POWER, "0", {"unit_of_measurement": "W"})
    assert await hass.config_entries.async_setup(washer_entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(washer_entry.entry_id)
    result = await _step(hass, result, {"next_step_id": "cycles"})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "no_cycles"
