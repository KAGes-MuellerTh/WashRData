"""Energy cost, background evaluation and thresholds in Home Assistant."""

from __future__ import annotations

from datetime import timedelta

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed
from pytest_homeassistant_custom_component.typing import WebSocketGenerator

from custom_components.washrdata.const import CONF_DEVICE_TYPE, CONF_POWER_SENSOR, DOMAIN
from tests.engine.test_matching import COTTON, QUICK, trained

from .conftest import POWER
from .test_programs import _run

PRICE = "input_number.strompreis_energie"
W = {"unit_of_measurement": "W"}


@pytest.fixture
def priced_entry(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Washer",
        unique_id=POWER,
        data={"name": "Washer", CONF_DEVICE_TYPE: "washer", CONF_POWER_SENSOR: POWER},
        options={"price_entity": PRICE},
    )
    entry.add_to_hass(hass)
    return entry


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    hass.states.async_set(POWER, "1.5", W)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def _evaluate(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    freezer.tick(timedelta(seconds=31))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


@pytest.mark.parametrize(("state", "unit", "per_kwh"), [("30", "ct/kWh", 0.30), ("0.25", "EUR/kWh", 0.25)])
async def test_cycle_cost_from_price_entity(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    priced_entry: MockConfigEntry,
    state: str,
    unit: str,
    per_kwh: float,
) -> None:
    hass.states.async_set(PRICE, state, {"unit_of_measurement": unit})
    await _setup(hass, priced_entry)
    await _run(hass, freezer, QUICK, 1)

    cycle = priced_entry.runtime_data.last_cycle
    assert cycle.cost == pytest.approx(cycle.energy_wh / 1000 * per_kwh, rel=0.02)
    sensor = hass.states.get("sensor.washer_last_cycle_cost")
    assert float(sensor.state) == pytest.approx(round(cycle.cost, 2))
    assert sensor.attributes["unit_of_measurement"] == hass.config.currency
    last = hass.states.get("sensor.washer_last_cycle_duration").attributes
    assert last["cost"] == round(cycle.cost, 2)


async def test_no_cost_sensors_without_price(hass: HomeAssistant, washer_entry: MockConfigEntry) -> None:
    await _setup(hass, washer_entry)
    assert hass.states.get("sensor.washer_last_cycle_cost") is None


async def test_evaluation_runs_in_background_and_fills_old_cycles(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    hass_ws_client: WebSocketGenerator,
    washer_entry: MockConfigEntry,
) -> None:
    await _setup(hass, washer_entry)
    device = washer_entry.runtime_data
    bench = trained(COTTON, QUICK, runs=3)
    for c in bench.tracker.history:  # as stored before 0.2.4
        c.recognised, c.known_programs = None, []
    device.tracker.programs = list(bench.tracker.programs)
    device.tracker.history = bench.tracker.history
    device.schedule_evaluation()
    await _evaluate(hass, freezer)

    assert device.evaluation is not None and len(device.evaluation.cycles) == 6
    assert all(c.recognition_retro for c in device.tracker.history)
    assert hass.states.get("sensor.washer_recognition_accuracy").state == "100"

    ws = await hass_ws_client(hass)
    await ws.send_json_auto_id({"type": "washrdata/overview"})
    overview = (await ws.receive_json())["result"]["devices"][0]
    evaluation = overview["evaluation"]
    assert evaluation["cycles"] == 6
    assert evaluation["recommended_auto"] is not None
    assert len(evaluation["remaining"]) == 3
    cycle = overview["cycles"][0]
    assert cycle["recognition_retro"] is True
    assert cycle["evaluation"]["final"] == cycle["program"]
    assert overview["thresholds"] == {"show": 0.25, "auto": 0.6}

    # The cheap live call carries the same revision until stored cycles change.
    await ws.send_json_auto_id({"type": "washrdata/live", "entry_id": washer_entry.entry_id})
    live = (await ws.receive_json())["result"]
    assert live["revision"] == overview["revision"]
    assert "cycles" not in live
    device.tracker.label(cycle["id"], QUICK if cycle["program"] == COTTON else COTTON)
    await ws.send_json_auto_id({"type": "washrdata/live", "entry_id": washer_entry.entry_id})
    assert (await ws.receive_json())["result"]["revision"] != overview["revision"]


async def test_set_thresholds_from_panel(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator, washer_entry: MockConfigEntry
) -> None:
    await _setup(hass, washer_entry)
    ws = await hass_ws_client(hass)
    entry_id = washer_entry.entry_id
    await ws.send_json_auto_id(
        {"type": "washrdata/set_thresholds", "entry_id": entry_id, "show": 0.5, "auto": 0.4}
    )
    assert (await ws.receive_json())["error"]["code"] == "invalid_format"

    await ws.send_json_auto_id(
        {"type": "washrdata/set_thresholds", "entry_id": entry_id, "show": 0.3, "auto": 0.7}
    )
    assert (await ws.receive_json())["success"]
    await hass.async_block_till_done()
    assert washer_entry.options["show_confidence"] == 30
    config = washer_entry.runtime_data.config
    assert (config.show_confidence, config.auto_label_confidence) == (0.3, 0.7)


async def test_options_flow_thresholds_and_price(hass: HomeAssistant, washer_entry: MockConfigEntry) -> None:
    await _setup(hass, washer_entry)
    result = await hass.config_entries.options.async_init(washer_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "settings"}
    )
    base = {"start_power_w": 8, "stop_power_w": 4, "end_delay_min": 5, "anti_crease": False}

    bad = {**base, "show_confidence": 70, "auto_label_confidence": 50}
    result = await hass.config_entries.options.async_configure(result["flow_id"], bad)
    assert result["errors"] == {"base": "show_above_auto"}

    good = {**base, "show_confidence": 30, "auto_label_confidence": 65, "price_entity": PRICE}
    result = await hass.config_entries.options.async_configure(result["flow_id"], good)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    device = washer_entry.runtime_data
    assert device.price_entity == PRICE
    assert device.config.auto_label_confidence == 0.65
