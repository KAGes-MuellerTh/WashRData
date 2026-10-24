"""Thresholds learned from the appliance's own completed cycles."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any

from .model import CycleRecord, DetectorConfig

HISTORY = 20
# Safety margin on top of the longest quiet spell seen inside a cycle.
END_DELAY_FACTOR = 1.25
END_DELAY_MARGIN_S = 60.0


@dataclass
class LearnedStats:
    """Longest in-cycle pause of recent cycles, used to size the end delay.

    A program that soaks for 12 minutes teaches the detector not to end a
    cycle after 5 quiet minutes. A cycle that was ended too early and then
    resumed contributes its gap as a pause, so the mistake is not repeated.
    """

    longest_pauses: deque[float] = field(default_factory=lambda: deque(maxlen=HISTORY))

    def learn(self, cycle: CycleRecord) -> bool:
        """Record a finished cycle. Returns whether it was used."""
        if cycle.interrupted:
            return False
        self.longest_pauses.append(cycle.longest_pause)
        return True

    def forget_last(self) -> None:
        """Undo the last `learn`, for a cycle that turned out not to be over."""
        if self.longest_pauses:
            self.longest_pauses.pop()

    def replace(self, old: float, new: list[float]) -> bool:
        """Swap one cycle's entry for others, e.g. after splitting it in two."""
        for i, value in enumerate(self.longest_pauses):
            if abs(value - old) < 1e-6:
                entries = list(self.longest_pauses)
                entries[i : i + 1] = new
                self.longest_pauses = deque(entries[-HISTORY:], maxlen=HISTORY)
                return True
        return False

    def end_delay(self, config: DetectorConfig) -> float:
        learned = max(self.longest_pauses, default=0.0) * END_DELAY_FACTOR
        if learned > 0:
            learned += END_DELAY_MARGIN_S
        return min(config.max_end_delay_s, max(config.end_delay_s, learned))

    def to_dict(self) -> dict[str, Any]:
        return {"longest_pauses": list(self.longest_pauses)}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LearnedStats:
        stats = cls()
        stats.longest_pauses.extend(float(v) for v in data.get("longest_pauses", []))
        return stats
