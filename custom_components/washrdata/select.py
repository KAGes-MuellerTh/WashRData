"""Program select: shows and sets the program of the current or last cycle."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import WashRDataConfigEntry
from .const import NO_PROGRAM
from .engine import CURRENT, LAST, CycleRecord
from .entity import WashRDataEntity

PROGRAM = SelectEntityDescription(key="program_select", translation_key="program_select")


async def async_setup_entry(
    hass: HomeAssistant,
    entry: WashRDataConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([WashRDataProgramSelect(entry.runtime_data, PROGRAM)])


class WashRDataProgramSelect(WashRDataEntity, SelectEntity):
    """While a cycle runs this labels the running cycle, otherwise the last one.

    Showing the recognised program while it runs lets you confirm or correct
    it with one tap; a choice made by hand always wins over recognition.
    """

    def _target(self) -> tuple[str, CycleRecord | None]:
        tracker = self.device.tracker
        if tracker.cycle is not None:
            return CURRENT, tracker.cycle
        return LAST, tracker.last_cycle

    @property
    def options(self) -> list[str]:
        return [NO_PROGRAM, *self.device.tracker.programs]

    @property
    def current_option(self) -> str:
        _, cycle = self._target()
        if cycle is None:
            return NO_PROGRAM
        if cycle.program:
            return cycle.program
        match = self.device.match
        if cycle is self.device.tracker.cycle and match and match.program:
            return match.program
        return NO_PROGRAM

    @property
    def available(self) -> bool:
        return self._target()[1] is not None

    async def async_select_option(self, option: str) -> None:
        target, _ = self._target()
        self.device.tracker.label(target, None if option == NO_PROGRAM else option)
        self.device.changed(save_now=True)
