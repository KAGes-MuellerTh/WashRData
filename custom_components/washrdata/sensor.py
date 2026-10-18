"""Sensors: state, current and last cycle, lifetime totals."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import EntityCategory, UnitOfEnergy, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.util import dt as dt_util

from . import WashRDataConfigEntry
from .device import WashRDataDevice, cycle_summary
from .engine import CycleRecord, State
from .entity import WashRDataEntity


def _minutes(cycle: CycleRecord | None) -> float | None:
    if cycle is None:
        return None
    return round(cycle.duration(dt_util.utcnow().timestamp()) / 60, 1)


def _kwh(wh: float | None) -> float | None:
    return None if wh is None else round(wh / 1000, 3)


@dataclass(frozen=True, kw_only=True)
class WashRDataSensorDescription(SensorEntityDescription):
    value_fn: Callable[[WashRDataDevice], StateType]
    attrs_fn: Callable[[WashRDataDevice], dict[str, Any] | None] = lambda _: None


SENSORS: tuple[WashRDataSensorDescription, ...] = (
    WashRDataSensorDescription(
        key="state",
        translation_key="state",
        device_class=SensorDeviceClass.ENUM,
        options=[s.value for s in State],
        value_fn=lambda d: d.detector.state.value,
    ),
    WashRDataSensorDescription(
        key="cycle_duration",
        translation_key="cycle_duration",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        value_fn=lambda d: _minutes(d.detector.cycle),
    ),
    WashRDataSensorDescription(
        key="cycle_energy",
        translation_key="cycle_energy",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=2,
        value_fn=lambda d: _kwh(d.detector.cycle.energy_wh) if d.detector.cycle else None,
    ),
    WashRDataSensorDescription(
        key="last_cycle_duration",
        translation_key="last_cycle_duration",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        value_fn=lambda d: _minutes(d.last_cycle),
        attrs_fn=lambda d: cycle_summary(d.last_cycle) if d.last_cycle else None,
    ),
    WashRDataSensorDescription(
        key="last_cycle_energy",
        translation_key="last_cycle_energy",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=2,
        value_fn=lambda d: _kwh(d.last_cycle.energy_wh) if d.last_cycle else None,
    ),
    WashRDataSensorDescription(
        key="cycle_count",
        translation_key="cycle_count",
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda d: d.detector.cycle_count,
    ),
    WashRDataSensorDescription(
        key="energy_total",
        translation_key="energy_total",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=2,
        value_fn=lambda d: _kwh(d.detector.total_energy_wh),
    ),
    WashRDataSensorDescription(
        key="end_delay",
        translation_key="end_delay",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: round(d.detector.end_delay / 60, 1),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: WashRDataConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities(WashRDataSensor(entry.runtime_data, d) for d in SENSORS)


class WashRDataSensor(WashRDataEntity, SensorEntity):
    entity_description: WashRDataSensorDescription

    @property
    def native_value(self) -> StateType:
        return self.entity_description.value_fn(self.device)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        return self.entity_description.attrs_fn(self.device)
