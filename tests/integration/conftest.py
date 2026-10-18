"""Fixtures for tests that run the integration inside Home Assistant."""

from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.washrdata.const import CONF_DEVICE_TYPE, CONF_POWER_SENSOR, DOMAIN

POWER = "sensor.plug_power"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    return None


@pytest.fixture
def washer_entry(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Washer",
        unique_id=POWER,
        data={"name": "Washer", CONF_DEVICE_TYPE: "washer", CONF_POWER_SENSOR: POWER},
    )
    entry.add_to_hass(hass)
    return entry
