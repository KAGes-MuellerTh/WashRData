"""The notification blueprints run in a real Home Assistant.

The mobile app notification is swapped for an event, so the test needs no
phone; triggers, conditions and message templates are the shipped ones.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_capture_events

from custom_components.washrdata.const import DOMAIN

from .conftest import POWER

SOURCE = Path(__file__).parents[2] / "blueprints" / "automation" / "washrdata"
NOTIFY = """  - domain: mobile_app
    type: notify
    device_id: !input notify_device
    title: !input title
    message: !input message
"""
STAND_IN = """  - event: test_notify
    event_data:
      title: !input title
      message: !input message
"""


def _install(hass: HomeAssistant, name: str) -> None:
    text = (SOURCE / name).read_text()
    assert NOTIFY in text
    target = Path(hass.config.path("blueprints", "automation", "washrdata", name))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text.replace(NOTIFY, STAND_IN))


async def _automation(hass: HomeAssistant, name: str, inputs: dict) -> None:
    _install(hass, name)
    config = {"automation": {"use_blueprint": {"path": f"washrdata/{name}", "input": inputs}}}
    assert await async_setup_component(hass, "automation", config)
    await hass.async_block_till_done()


@pytest.mark.parametrize(
    ("cycle", "message"),
    [
        (
            {
                "program": "Baumwolle 60",
                "duration_min": 112.4,
                "energy_kwh": 1.234,
                "cost": 0.37,
                "interrupted": False,
            },
            "Baumwolle 60 nach 112 min, 1.23 kWh, 0.37 €.",
        ),
        (
            {"program": None, "duration_min": 30, "energy_kwh": 0.4, "cost": None, "interrupted": False},
            "Lauf nach 30 min, 0.4 kWh.",
        ),
    ],
)
async def test_notify_finished(
    hass: HomeAssistant, washer_entry: MockConfigEntry, cycle: dict, message: str
) -> None:
    hass.states.async_set(POWER, "0", {"unit_of_measurement": "W"})
    assert await hass.config_entries.async_setup(washer_entry.entry_id)
    await hass.async_block_till_done()
    device = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, washer_entry.entry_id)})
    await _automation(hass, "notify_finished.yaml", {"appliance": device.id, "notify_device": "phone"})
    sent = async_capture_events(hass, "test_notify")

    data = {"entry_id": washer_entry.entry_id, "name": "Washer", "cycle": cycle}
    hass.bus.async_fire("washrdata_cycle_finished", data)
    await hass.async_block_till_done()
    assert [e.data for e in sent] == [{"title": "Washer fertig", "message": message}]

    # Other appliances and interrupted runs stay quiet.
    hass.bus.async_fire("washrdata_cycle_finished", {**data, "entry_id": "other"})
    hass.bus.async_fire("washrdata_cycle_finished", {**data, "cycle": {**cycle, "interrupted": True}})
    await hass.async_block_till_done()
    assert len(sent) == 1


async def test_notify_ending_soon(hass: HomeAssistant) -> None:
    remaining = "sensor.washer_time_remaining"
    hass.states.async_set(remaining, "unknown")
    await _automation(
        hass,
        "notify_ending_soon.yaml",
        {"remaining_sensor": remaining, "minutes": 10, "notify_device": "phone"},
    )
    sent = async_capture_events(hass, "test_notify")

    for value in ("25", "12", "9", "8"):
        hass.states.async_set(remaining, value)
        await hass.async_block_till_done()
    assert len(sent) == 1
    assert sent[0].data["title"] == "Gleich fertig"
    assert sent[0].data["message"].startswith("Noch 9 min, fertig gegen ")

    # Coming from unknown (a restart, or a late recognition) does not warn.
    hass.states.async_set(remaining, "unknown")
    hass.states.async_set(remaining, "5")
    await hass.async_block_till_done()
    assert len(sent) == 1
