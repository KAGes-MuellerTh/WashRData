"""WashRData: appliance cycle detection from a smart plug's power sensor."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import PLATFORMS
from .device import WashRDataDevice

type WashRDataConfigEntry = ConfigEntry[WashRDataDevice]


async def async_setup_entry(hass: HomeAssistant, entry: WashRDataConfigEntry) -> bool:
    device = WashRDataDevice(hass, entry)
    await device.async_start()
    entry.runtime_data = device
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: WashRDataConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.async_stop()
    return unloaded
