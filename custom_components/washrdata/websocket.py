"""WebSocket commands of the WashRData panel.

Any logged-in user may read and label, like the program select entity.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.util import dt as dt_util

from .const import DOMAIN, signal_update
from .device import WashRDataDevice
from .engine import CycleRecord, MatchResult
from .engine.matching import resample

# Curves go to the panel as one mean value per minute.
CURVE_STEP_S = 60.0


def _curve(cycle: CycleRecord, now: float | None = None) -> list[float]:
    return [round(w, 1) for w in resample(cycle.trace, cycle.duration(now), CURVE_STEP_S)]


def cycle_json(cycle: CycleRecord, references: set[str], now: float | None = None) -> dict[str, Any]:
    return {
        "id": cycle.id,
        "start": cycle.start,
        "end": cycle.end,
        "duration_s": round(cycle.duration(now)),
        "energy_kwh": round(cycle.energy_wh / 1000, 3),
        "peak_w": round(cycle.peak_power_w),
        "interrupted": cycle.interrupted,
        "program": cycle.program,
        "program_source": cycle.program_source,
        "recognised": cycle.recognised,
        "confidence": cycle.match_confidence,
        "known_programs": cycle.known_programs,
        "reference": cycle.id in references,
        "curve": _curve(cycle, now),
    }


def _match_json(match: MatchResult | None) -> dict[str, Any] | None:
    if match is None:
        return None
    return {
        "program": match.program,
        "confidence": match.confidence,
        "manual": match.manual,
        "recognised": match.recognised,
        "recognition_confidence": match.recognition_confidence,
        "remaining_s": match.remaining_s,
        "progress": match.progress,
        "candidates": [{"program": p, "score": s} for p, s in match.candidates],
    }


def device_json(device: WashRDataDevice) -> dict[str, Any]:
    tracker = device.tracker
    now = dt_util.utcnow().timestamp()
    refs = {c.id for cycles in tracker.references().values() for c in cycles}
    accuracy = tracker.accuracy()
    return {
        "entry_id": device.entry.entry_id,
        "title": device.entry.title,
        "device_type": device.device_type.value,
        "state": tracker.state.value,
        "programs": list(tracker.programs),
        "accuracy": {
            "cycles": accuracy.total.cycles,
            "hits": accuracy.total.hits,
            "programs": {p: {"cycles": a.cycles, "hits": a.hits} for p, a in accuracy.programs.items()},
        },
        "current": cycle_json(tracker.cycle, refs, now) if tracker.cycle else None,
        "match": _match_json(tracker.match),
        "cycles": [cycle_json(c, refs) for c in reversed(tracker.history)],
    }


def _devices(hass: HomeAssistant) -> list[WashRDataDevice]:
    return [
        entry.runtime_data
        for entry in hass.config_entries.async_entries(DOMAIN)
        if entry.state is ConfigEntryState.LOADED
    ]


def _find(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict
) -> WashRDataDevice | None:
    device = next((d for d in _devices(hass) if d.entry.entry_id == msg["entry_id"]), None)
    if device is None:
        connection.send_error(msg["id"], websocket_api.ERR_NOT_FOUND, "Unknown device")
    return device


@websocket_api.websocket_command({vol.Required("type"): "washrdata/overview"})
@callback
def ws_overview(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
    connection.send_result(msg["id"], {"devices": [device_json(d) for d in _devices(hass)]})


@websocket_api.websocket_command({vol.Required("type"): "washrdata/subscribe"})
@callback
def ws_subscribe(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
    """Sends the entry id whenever a device changed. Devices loaded later are not included."""

    def forward(entry_id: str) -> Any:
        @callback
        def send() -> None:
            connection.send_message(websocket_api.event_message(msg["id"], {"entry_id": entry_id}))

        return send

    unsubs = [
        async_dispatcher_connect(hass, signal_update(d.entry.entry_id), forward(d.entry.entry_id))
        for d in _devices(hass)
    ]

    @callback
    def unsubscribe() -> None:
        for unsub in unsubs:
            unsub()

    connection.subscriptions[msg["id"]] = unsubscribe
    connection.send_result(msg["id"])


@websocket_api.websocket_command(
    {
        vol.Required("type"): "washrdata/label",
        vol.Required("entry_id"): str,
        vol.Required("cycle_id"): str,
        vol.Required("program"): vol.Any(None, vol.All(str, vol.Strip, vol.Length(max=60))),
    }
)
@callback
def ws_label(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
    if (device := _find(hass, connection, msg)) is None:
        return
    try:
        device.tracker.label(msg["cycle_id"], msg["program"] or None)
    except KeyError:
        connection.send_error(msg["id"], websocket_api.ERR_NOT_FOUND, "Unknown cycle")
        return
    device.changed(save_now=True)
    connection.send_result(msg["id"])


@websocket_api.websocket_command(
    {
        vol.Required("type"): "washrdata/rename_program",
        vol.Required("entry_id"): str,
        vol.Required("program"): str,
        vol.Required("new_name"): vol.All(str, vol.Strip, vol.Length(min=1, max=60)),
    }
)
@callback
def ws_rename(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
    if (device := _find(hass, connection, msg)) is None:
        return
    try:
        device.tracker.rename_program(msg["program"], msg["new_name"])
    except KeyError:
        connection.send_error(msg["id"], websocket_api.ERR_NOT_FOUND, "Unknown program")
        return
    except ValueError:
        connection.send_error(msg["id"], websocket_api.ERR_INVALID_FORMAT, "Program exists")
        return
    device.changed(save_now=True)
    connection.send_result(msg["id"])


@websocket_api.websocket_command(
    {
        vol.Required("type"): "washrdata/delete_program",
        vol.Required("entry_id"): str,
        vol.Required("program"): str,
    }
)
@callback
def ws_delete(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
    if (device := _find(hass, connection, msg)) is None:
        return
    try:
        device.tracker.delete_program(msg["program"])
    except KeyError:
        connection.send_error(msg["id"], websocket_api.ERR_NOT_FOUND, "Unknown program")
        return
    device.changed(save_now=True)
    connection.send_result(msg["id"])


@callback
def async_register_websocket(hass: HomeAssistant) -> None:
    for command in (ws_overview, ws_subscribe, ws_label, ws_rename, ws_delete):
        websocket_api.async_register_command(hass, command)
