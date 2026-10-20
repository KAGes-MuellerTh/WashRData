"""Recognition on a real washing machine run (tests/fixtures/washer_real_1.json).

The run is the only labelled reference. Variants of it must be recognised;
different programs must not be, even though no second program exists to
compete with (the case that was reported with one labelled run).
"""

from __future__ import annotations

import json
import random
from pathlib import Path

import pytest

from engine import PRESETS, CycleRecord, DeviceType, LabelSource, Tracker

from .sim import HOUR, MIN

FIXTURE = Path(__file__).parent.parent / "fixtures" / "washer_real_1.json"
PROGRAM = "Mein Programm"
REF = CycleRecord.from_dict(json.loads(FIXTURE.read_text())["cycle"])


def _steps(trace, duration):
    pts = [*trace, (duration, None)]
    return [(pts[i + 1][0] - pts[i][0], pts[i][1]) for i in range(len(pts) - 1)]


def same_program(seed: int, heat_scale: float) -> list[tuple[float, float]]:
    """The reference run again, heating phase stretched, loads jittered ±10 %."""
    rng = random.Random(seed)
    out: list[tuple[float, float]] = []
    t = 0.0
    for d, w in _steps(REF.trace, REF.duration()):
        if 5 * MIN < t < 34 * MIN and w > 1000:
            d *= heat_scale
        t += d
        out.append((d, w * rng.uniform(0.9, 1.1) if w > 20 else w))
    return out


COLD_SHORT = [(5 * MIN, 20.0), (30 * MIN, 60.0), (10 * MIN, 250.0), (2 * MIN, 2.0)]
HOT_LONG = [(5 * MIN, 20.0), (45 * MIN, 2100.0), (60 * MIN, 60.0), (15 * MIN, 300.0), (2 * MIN, 2.0)]


def run(curve, marks=(5, 10, 20, 40, 60, 80)):
    tracker = Tracker(PRESETS[DeviceType.WASHER])
    tracker.history.append(CycleRecord.from_dict(REF.to_dict()))
    tracker.label(REF.id, PROGRAM)
    seen: dict[int, tuple] = {}
    ts = 10_000_000.0
    for duration, watts in [(10 * MIN, 1.0), *curve, (HOUR, 1.0)]:
        end = ts + duration
        while ts < end:
            tracker.update(ts, watts)
            cycle = tracker.cycle
            if cycle is not None:
                elapsed = (ts - cycle.start) / MIN
                for mark in marks:
                    if mark not in seen and elapsed >= mark:
                        seen[mark] = tracker.match
            ts += min(10.0, end - ts)
    return seen, tracker.last_cycle


@pytest.mark.parametrize(("seed", "heat_scale"), [(1, 0.85), (2, 1.0), (3, 1.2)])
def test_same_program_is_recognised(seed: int, heat_scale: float) -> None:
    curve = same_program(seed, heat_scale)
    seen, cycle = run(curve)
    total = sum(d for d, _ in curve[:-1]) / MIN  # trailing standby is not part of the cycle
    for mark in (10, 20, 40, 60, 80):
        assert seen[mark] is not None and seen[mark].program == PROGRAM, mark
        assert seen[mark].confidence >= 0.8, mark
    assert seen[80].remaining_s / MIN == pytest.approx(total - 80, abs=3)
    assert cycle.program == PROGRAM
    assert cycle.program_source == LabelSource.AUTO


def test_cold_short_program_is_not_taken_for_the_reference() -> None:
    seen, cycle = run(COLD_SHORT)
    for mark in (20, 40):
        assert seen[mark] is None or seen[mark].program is None, mark
    assert cycle.program is None


def test_hot_long_program_is_not_labelled_as_the_reference() -> None:
    """With one reference a longer, hotter run cannot be told apart from the
    same program with cold inlet water while it runs; it may be shown as the
    reference. It must not be labelled as it, which would spoil the reference."""
    _, cycle = run(HOT_LONG)
    assert cycle.program is None


def test_second_labelled_program_separates_both() -> None:
    tracker = Tracker(PRESETS[DeviceType.WASHER])
    tracker.history.append(CycleRecord.from_dict(REF.to_dict()))
    tracker.label(REF.id, PROGRAM)
    ts = 10_000_000.0

    def play(curve):
        nonlocal ts
        seen = {}
        for duration, watts in [(10 * MIN, 1.0), *curve, (HOUR, 1.0)]:
            end = ts + duration
            while ts < end:
                tracker.update(ts, watts)
                if tracker.cycle is not None and (ts - tracker.cycle.start) >= 60 * MIN and 60 not in seen:
                    seen[60] = tracker.match
                ts += min(10.0, end - ts)
        return seen

    play(HOT_LONG)
    tracker.label("last", "Heiß lang")

    seen = play(HOT_LONG)
    assert seen[60].program == "Heiß lang"
    assert tracker.last_cycle.program == "Heiß lang"

    seen = play(same_program(5, 1.1))
    assert seen[60].program == PROGRAM
    assert tracker.last_cycle.program == PROGRAM
