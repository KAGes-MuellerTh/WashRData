"""Diagnostics download: everything needed to reproduce a detection problem.

Contains the configuration, the full engine state (including the running
cycle), all stored cycles with their power traces, programs and the current
match. Nothing in it is secret; entity ids are kept so the trace can be
related to the plug.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.core import HomeAssistant

from . import WashRDataConfigEntry


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: WashRDataConfigEntry
) -> dict[str, Any]:
    device = entry.runtime_data
    match = device.match
    return {
        "entry": {"title": entry.title, "data": dict(entry.data), "options": dict(entry.options)},
        "config": asdict(device.config),
        "end_delay_s": device.detector.end_delay,
        "match": asdict(match) | {"progress": match.progress} if match else None,
        "references": {p: [c.id for c in cs] for p, cs in device.tracker.references().items()},
        "tracker": device.tracker.to_dict(),
    }
