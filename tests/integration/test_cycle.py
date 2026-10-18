"""A washer cycle end to end: plug states in, entities, events and storage out."""

from __future__ import annotations

from datetime import timedelta

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import Event, HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from .conftest import POWER

KW = {"unit_of_measurement": "kW"}
W = {"unit_of_measurement": "W"}


async def _advance(hass: HomeAssistant, freezer: FrozenDateTimeFactory, minutes: float) -> None:
    """Let time pass in 30 s steps so the tick timer fires as in real life."""
    for _ in range(int(minutes * 2)):
        freezer.tick(timedelta(seconds=30))
        async_fire_time_changed(hass)
        await hass.async_block_till_done()


async def test_washer_cycle(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, washer_entry: MockConfigEntry
) -> None:
    events: list[Event] = []
    for kind in ("cycle_started", "cycle_finished"):
        hass.bus.async_listen(f"washrdata_{kind}", events.append)

    hass.states.async_set(POWER, "1.5", W)
    assert await hass.config_entries.async_setup(washer_entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get("sensor.washer_state").state == "idle"
    assert hass.states.get("binary_sensor.washer_running").state == "off"

    # The plug reports in kW and only on change; ticks carry the cycle.
    hass.states.async_set(POWER, "2.0", KW)
    await _advance(hass, freezer, 20)
    assert hass.states.get("sensor.washer_state").state == "running"
    assert hass.states.get("binary_sensor.washer_running").state == "on"
    assert float(hass.states.get("sensor.washer_cycle_duration").state) == pytest.approx(20, abs=0.6)
    assert float(hass.states.get("sensor.washer_cycle_energy").state) == pytest.approx(0.667, abs=0.02)

    hass.states.async_set(POWER, "1.0", W)
    await _advance(hass, freezer, 10)
    assert hass.states.get("sensor.washer_state").state == "finished"
    assert hass.states.get("binary_sensor.washer_running").state == "off"
    assert hass.states.get("sensor.washer_cycle_count").state == "1"
    assert float(hass.states.get("sensor.washer_last_cycle_duration").state) == pytest.approx(20, abs=0.6)
    assert hass.states.get("sensor.washer_last_cycle_duration").attributes["interrupted"] is False

    assert [e.event_type for e in events] == ["washrdata_cycle_started", "washrdata_cycle_finished"]
    assert events[1].data["name"] == "Washer"
    assert events[1].data["cycle"]["energy_kwh"] == pytest.approx(0.667, abs=0.02)


async def test_state_survives_reload(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, washer_entry: MockConfigEntry
) -> None:
    hass.states.async_set(POWER, "300", W)
    assert await hass.config_entries.async_setup(washer_entry.entry_id)
    await hass.async_block_till_done()
    await _advance(hass, freezer, 15)
    assert hass.states.get("sensor.washer_state").state == "running"

    assert await hass.config_entries.async_reload(washer_entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get("sensor.washer_state").state == "running"
    assert float(hass.states.get("sensor.washer_cycle_duration").state) == pytest.approx(15, abs=0.6)

    hass.states.async_set(POWER, "0", W)
    await _advance(hass, freezer, 10)
    assert hass.states.get("sensor.washer_cycle_count").state == "1"


async def test_unavailable_plug_is_tolerated(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, washer_entry: MockConfigEntry
) -> None:
    hass.states.async_set(POWER, "unavailable")
    assert await hass.config_entries.async_setup(washer_entry.entry_id)
    await hass.async_block_till_done()
    await _advance(hass, freezer, 2)
    assert hass.states.get("sensor.washer_state").state == "idle"
    assert hass.states.get("sensor.washer_total_energy").state == "0.0"
