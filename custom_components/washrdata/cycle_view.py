"""Human readable cycle summaries for the options flow."""

from __future__ import annotations

import math

from homeassistant.core import HomeAssistant
from homeassistant.helpers.translation import async_get_translations
from homeassistant.util import dt as dt_util

from .const import DOMAIN, NO_PROGRAM
from .engine import CycleRecord, LabelSource

BARS = "▁▂▃▄▅▆▇█"
# Words the cycle labels need, from the "cycle_view" selector translations.
WORDS = (NO_PROGRAM, "manual", "auto", "interrupted")


def sparkline(cycle: CycleRecord, width: int) -> str:
    """Power curve as block characters, one per time slice, scaled to the peak.

    Each slice shows the highest power in it, so short spikes such as spinning
    stay visible. The square root scale keeps the motor visible next to the heater.
    """
    trace = cycle.trace
    if not trace:
        return ""
    duration = max(cycle.duration(), trace[-1][0], 1.0)
    peak = max(w for _, w in trace)
    if peak <= 0:
        return BARS[0] * width
    slices = [0.0] * width
    for i, (t, w) in enumerate(trace):
        # A trace point holds its power until the next point.
        until = trace[i + 1][0] if i + 1 < len(trace) else duration
        first = min(width - 1, int(t / duration * width))
        last = min(width - 1, max(first, int(max(t, until - 1e-9) / duration * width)))
        for s in range(first, last + 1):
            slices[s] = max(slices[s], w)
    return "".join(BARS[min(len(BARS) - 1, int(math.sqrt(w / peak) * len(BARS)))] for w in slices)


async def async_words(hass: HomeAssistant) -> dict[str, str]:
    """The label words in the user's language, falling back to the key."""
    prefix = f"component.{DOMAIN}.selector.cycle_view.options."
    texts = await async_get_translations(hass, hass.config.language, "selector", [DOMAIN])
    return {word: texts.get(prefix + word, word) for word in WORDS}


def _number(value: float, digits: int, language: str) -> str:
    text = f"{value:.{digits}f}"
    return text.replace(".", ",") if language.startswith("de") else text


def _when(ts: float, language: str) -> str:
    local = dt_util.as_local(dt_util.utc_from_timestamp(ts))
    return local.strftime("%d.%m.%Y %H:%M" if language.startswith("de") else "%Y-%m-%d %H:%M")


def program_text(cycle: CycleRecord, words: dict[str, str], language: str) -> str:
    """Program with where it came from, e.g. "Cotton 40 (auto, 82 %)"."""
    if not cycle.program:
        return words[NO_PROGRAM]
    if cycle.program_source == LabelSource.MANUAL:
        return f"{cycle.program} ({words['manual']})"
    if cycle.match_confidence is not None:
        percent = _number(cycle.match_confidence * 100, 0, language)
        return f"{cycle.program} ({words['auto']}, {percent} %)"
    return f"{cycle.program} ({words['auto']})"


def cycle_label(cycle: CycleRecord, words: dict[str, str], language: str, curve: int = 16) -> str:
    """One line per cycle: start, duration, energy, program, and a curve `curve` characters wide."""
    minutes = round(cycle.duration() / 60)
    parts = [
        _when(cycle.start, language),
        f"{minutes // 60}:{minutes % 60:02d} h",
        f"{_number(cycle.energy_wh / 1000, 2, language)} kWh",
        program_text(cycle, words, language),
    ]
    if cycle.interrupted:
        parts.append(words["interrupted"])
    if curve:
        parts.append(sparkline(cycle, curve))
    return " · ".join(parts)
