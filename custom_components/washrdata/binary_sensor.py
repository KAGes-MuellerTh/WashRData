"""Binary sensor: on for the whole cycle, including pauses."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import WashRDataConfigEntry
from .engine import ACTIVE_STATES
from .entity import WashRDataEntity

RUNNING = BinarySensorEntityDescription(
    key="running",
    translation_key="running",
    device_class=BinarySensorDeviceClass.RUNNING,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: WashRDataConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([WashRDataRunning(entry.runtime_data, RUNNING)])


class WashRDataRunning(WashRDataEntity, BinarySensorEntity):
    @property
    def is_on(self) -> bool:
        return self.device.detector.state in ACTIVE_STATES
