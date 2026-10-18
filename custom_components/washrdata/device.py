"""Connects one power sensor to a cycle detector and keeps its state."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_UNIT_OF_MEASUREMENT, STATE_UNAVAILABLE, STATE_UNKNOWN, UnitOfPower
from homeassistant.core import Event as HassEvent
from homeassistant.core import EventStateChangedData, HomeAssistant, State, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_state_report_event,
    async_track_time_interval,
)
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    CONF_DEVICE_TYPE,
    CONF_POWER_SENSOR,
    DOMAIN,
    MAX_STORED_CYCLES,
    SAVE_DELAY_S,
    STORAGE_VERSION,
    TICK_INTERVAL,
    build_config,
    signal_update,
)
from .engine import CycleDetector, CycleRecord, DeviceType, Event, EventKind

_LOGGER = logging.getLogger(__name__)

_TO_WATTS = {UnitOfPower.WATT: 1.0, UnitOfPower.KILO_WATT: 1000.0, UnitOfPower.MILLIWATT: 0.001}


def parse_power(state: State | None) -> float | None:
    """Watts from a power sensor state, None when unavailable or invalid."""
    if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
        return None
    try:
        value = float(state.state)
    except ValueError:
        return None
    unit = state.attributes.get(ATTR_UNIT_OF_MEASUREMENT, UnitOfPower.WATT)
    return value * _TO_WATTS.get(unit, 1.0)


def cycle_summary(cycle: CycleRecord) -> dict[str, Any]:
    """Event payload for a cycle, without the trace."""

    def iso(ts: float | None) -> str | None:
        return dt_util.utc_from_timestamp(ts).isoformat() if ts is not None else None

    return {
        "start": iso(cycle.start),
        "end": iso(cycle.end),
        "duration_min": round(cycle.duration(dt_util.utcnow().timestamp()) / 60, 1),
        "energy_kwh": round(cycle.energy_wh / 1000, 3),
        "peak_power_w": round(cycle.peak_power_w, 1),
        "interrupted": cycle.interrupted,
        "resumed": cycle.resumed,
        "anti_crease_bursts": cycle.anti_crease_bursts,
    }


class WashRDataDevice:
    """Runtime of one config entry."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.device_type = DeviceType(entry.data[CONF_DEVICE_TYPE])
        self.power_entity: str = entry.data[CONF_POWER_SENSOR]
        self.config = build_config(self.device_type, dict(entry.options))
        self.detector = CycleDetector(self.config)
        self.cycles: list[CycleRecord] = []
        self._store: Store[dict[str, Any]] = Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}")
        self._unsubs: list[Any] = []

    @property
    def last_cycle(self) -> CycleRecord | None:
        return self.cycles[-1] if self.cycles else None

    async def async_start(self) -> None:
        if data := await self._store.async_load():
            self.detector = CycleDetector.from_dict(self.config, data.get("detector", {}))
            self.cycles = [CycleRecord.from_dict(c) for c in data.get("cycles", [])]
        self._unsubs = [
            async_track_state_change_event(self.hass, self.power_entity, self._on_state),
            async_track_state_report_event(self.hass, self.power_entity, self._on_state),
            async_track_time_interval(self.hass, self._on_tick, TICK_INTERVAL),
        ]
        state = self.hass.states.get(self.power_entity)
        self._handle(self.detector.update(dt_util.utcnow().timestamp(), parse_power(state)))

    async def async_stop(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        await self._store.async_save(self._data())

    @callback
    def _on_state(self, event: HassEvent[EventStateChangedData]) -> None:
        state = event.data["new_state"]
        if state is None:
            return
        # A tick may have run between the state write and this callback; the
        # sample is still the newest reading, so it must not be dropped as stale.
        ts = max(state.last_reported_timestamp, self.detector.last_ts or 0.0)
        self._handle(self.detector.update(ts, parse_power(state)))

    @callback
    def _on_tick(self, now: datetime) -> None:
        self._handle(self.detector.tick(now.timestamp()))

    @callback
    def _handle(self, events: list[Event]) -> None:
        for event in events:
            self._on_event(event)
        if any(e.kind == EventKind.FINISHED for e in events):
            self.hass.async_create_task(self._store.async_save(self._data()))
        else:
            self._store.async_delay_save(self._data, SAVE_DELAY_S)
        async_dispatcher_send(self.hass, signal_update(self.entry.entry_id))

    @callback
    def _on_event(self, event: Event) -> None:
        cycle = event.cycle
        if event.kind == EventKind.FINISHED and cycle is not None:
            self.cycles = [*self.cycles, cycle][-MAX_STORED_CYCLES:]
        elif event.kind == EventKind.RESUMED and cycle is not None:
            # The resumed cycle was stored as finished; it is open again.
            self.cycles = [c for c in self.cycles if c.start != cycle.start]
        _LOGGER.debug("%s: %s", self.entry.title, event.kind)
        self.hass.bus.async_fire(
            f"{DOMAIN}_{event.kind}",
            {
                "entry_id": self.entry.entry_id,
                "name": self.entry.title,
                "device_type": self.device_type.value,
                "cycle": cycle_summary(cycle) if cycle else None,
            },
        )

    def _data(self) -> dict[str, Any]:
        return {
            "detector": self.detector.to_dict(),
            "cycles": [c.to_dict() for c in self.cycles],
        }
