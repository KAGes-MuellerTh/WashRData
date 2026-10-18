"""Synthetic power curves and a driver that plays them into a detector."""

from __future__ import annotations

import random
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from engine import CycleDetector, Event, EventKind

# A curve is a list of (duration in seconds, watts or None for unavailable).
Curve = Sequence[tuple[float, float | None]]


def bursts(count: int, on_s: float, off_s: float, watts: float) -> list[tuple[float, float]]:
    """Anti-crease pattern: `count` drum turns separated by quiet spells."""
    out: list[tuple[float, float]] = []
    for _ in range(count):
        out += [(on_s, watts), (off_s, 0.0)]
    return out


@dataclass
class Run:
    events: list[Event]
    end_ts: float

    def kinds(self) -> list[EventKind]:
        return [e.kind for e in self.events]

    def of(self, kind: EventKind) -> list[Event]:
        return [e for e in self.events if e.kind == kind]


def play(
    det: CycleDetector,
    curve: Curve,
    *,
    start_ts: float = 0.0,
    sample_s: float = 10.0,
    on_change_only: bool = False,
    tick_s: float = 30.0,
) -> Run:
    """Play a curve into the detector.

    Dense mode reports every `sample_s`. `on_change_only` mimics plugs that
    only report when the value changes; the detector then gets a `tick`
    every `tick_s`, as the Home Assistant adapter does.
    """
    events: list[Event] = []
    ts = start_ts
    for duration, watts in curve:
        end = ts + duration
        events += det.update(ts, watts)
        step = tick_s if on_change_only else sample_s
        t = ts + step
        while t < end:
            events += det.tick(t) if on_change_only else det.update(t, watts)
            t += step
        ts = end
    return Run(events, ts)


def segments(*parts: Iterable[tuple[float, float | None]]) -> list[tuple[float, float | None]]:
    out: list[tuple[float, float | None]] = []
    for part in parts:
        out += list(part)
    return out


MIN = 60.0
HOUR = 3600.0


def vary(
    program: Sequence[tuple[float, float]], seed: int, chunk_s: float = 30.0
) -> list[tuple[float, float]]:
    """A realistic run of `program`: long phases vary ±10 % in length,
    loads vary ±15 % in power, in `chunk_s` steps. Deterministic per seed."""
    rng = random.Random(seed)
    out: list[tuple[float, float]] = []
    for duration, watts in program:
        if duration >= 10 * MIN:
            duration *= rng.uniform(0.9, 1.1)
        t = 0.0
        while t < duration:
            step = min(chunk_s, duration - t)
            jitter = rng.uniform(0.85, 1.15) if watts > 20 else 1.0
            out.append((step, watts * jitter))
            t += step
    return out


def duration_of(curve: Curve) -> float:
    return sum(d for d, _ in curve)
