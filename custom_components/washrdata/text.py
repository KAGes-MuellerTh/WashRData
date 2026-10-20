"""Text entity to create a program and label the running or last cycle with it."""

from __future__ import annotations

from homeassistant.components.text import TextEntity, TextEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import WashRDataConfigEntry
from .engine import CURRENT, LAST
from .entity import WashRDataEntity

NEW_PROGRAM = TextEntityDescription(key="new_program", translation_key="new_program", native_max=60)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: WashRDataConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([WashRDataNewProgram(entry.runtime_data, NEW_PROGRAM)])


class WashRDataNewProgram(WashRDataEntity, TextEntity):
    """Typing a name creates the program and assigns it like the program select
    does: to the running cycle, otherwise the last one. The field then clears."""

    _attr_native_value = ""

    async def async_set_value(self, value: str) -> None:
        name = value.strip()
        if name:
            tracker = self.device.tracker
            target = CURRENT if tracker.cycle is not None else LAST
            if tracker.find_cycle(target) is not None:
                tracker.label(target, name)
            else:
                tracker.create_program(name)
            self.device.changed(save_now=True)
        self.async_write_ha_state()
