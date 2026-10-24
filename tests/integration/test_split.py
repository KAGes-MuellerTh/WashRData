"""Splitting a merged cycle from the panel, and the resume window option."""

from __future__ import annotations

from dataclasses import replace

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.typing import WebSocketGenerator

from tests.engine.test_split import MERGED

from .conftest import POWER


async def test_split_from_panel(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator, washer_entry: MockConfigEntry
) -> None:
    hass.states.async_set(POWER, "0", {"unit_of_measurement": "W"})
    assert await hass.config_entries.async_setup(washer_entry.entry_id)
    await hass.async_block_till_done()
    tracker = washer_entry.runtime_data.tracker
    merged = replace(MERGED, start=1_700_000_000.0, end=1_700_000_000.0 + MERGED.duration())
    tracker.history = [merged]
    ws = await hass_ws_client(hass)

    await ws.send_json_auto_id({"type": "washrdata/overview"})
    cycle = (await ws.receive_json())["result"]["devices"][0]["cycles"][0]
    gap_start, gap_end = cycle["split_points"][0]
    assert 150 * 60 < gap_start < gap_end < 166 * 60

    entry_id = washer_entry.entry_id
    at = (gap_start + gap_end) / 2
    await ws.send_json_auto_id(
        {"type": "washrdata/split_cycle", "entry_id": entry_id, "cycle_id": merged.id, "at_s": at}
    )
    result = (await ws.receive_json())["result"]
    assert result["cycles"] == [c.id for c in tracker.history]
    assert len(tracker.history) == 2
    assert hass.states.get("sensor.washer_last_cycle_duration").state != "unknown"

    await ws.send_json_auto_id(
        {"type": "washrdata/split_cycle", "entry_id": entry_id, "cycle_id": "nope", "at_s": 60}
    )
    assert (await ws.receive_json())["error"]["code"] == "not_found"
    second = tracker.history[1]
    await ws.send_json_auto_id(
        {"type": "washrdata/split_cycle", "entry_id": entry_id, "cycle_id": second.id, "at_s": 5}
    )
    assert (await ws.receive_json())["error"]["code"] == "invalid_format"


async def test_resume_window_and_max_end_delay_options(
    hass: HomeAssistant, washer_entry: MockConfigEntry
) -> None:
    hass.states.async_set(POWER, "0", {"unit_of_measurement": "W"})
    assert await hass.config_entries.async_setup(washer_entry.entry_id)
    await hass.async_block_till_done()
    config = washer_entry.runtime_data.config
    assert (config.resume_window_s, config.max_end_delay_s) == (900, 3600)

    result = await hass.config_entries.options.async_init(washer_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "settings"}
    )
    settings = {
        "start_power_w": 8,
        "stop_power_w": 4,
        "end_delay_min": 5,
        "max_end_delay_min": 20,
        "resume_window_min": 5,
        "anti_crease": False,
        "show_confidence": 25,
        "auto_label_confidence": 60,
    }
    await hass.config_entries.options.async_configure(result["flow_id"], settings)
    await hass.async_block_till_done()
    config = washer_entry.runtime_data.config
    assert (config.resume_window_s, config.max_end_delay_s) == (300, 1200)
