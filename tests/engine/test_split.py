"""Two washes merged into one cycle: split it, and keep it from happening again.

The curve is a real report (tests/fixtures/washer_two_washes.json): the second
wash started 12 minutes after the first ended, inside the 15 minute resume
window, so the detector took it for the same run.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from engine import PRESETS, CycleDetector, CycleRecord, DeviceType, EventKind, LabelSource, Tracker
from engine.learning import LearnedStats
from engine.split import quiet_stretches, split_cycle

FIXTURE = Path(__file__).parent.parent / "fixtures" / "washer_two_washes.json"
MERGED = CycleRecord.from_dict(json.loads(FIXTURE.read_text())["cycle"])
WASHER = PRESETS[DeviceType.WASHER]
MIN = 60.0


def replay(config, trace=MERGED.trace, start=1_000_000.0):
    """Feed the trace as plug reports, with a tick every 30 s like Home Assistant."""
    detector = CycleDetector(config)
    events = detector.update(start - 600, 1.0)
    points = [*trace, (trace[-1][0] + 7200, 1.0)]
    for (t, w), (t_next, _) in zip(points, [*points[1:], (points[-1][0] + 30, 0)], strict=True):
        events += detector.update(start + t, w)
        tick = t + 30
        while tick < t_next:
            events += detector.tick(start + tick)
            tick += 30
    return detector, events


def test_resume_window_merges_the_two_washes() -> None:
    detector, events = replay(WASHER)
    kinds = [e.kind for e in events]
    assert kinds.count(EventKind.FINISHED) == 2
    assert kinds.count(EventKind.RESUMED) == 1
    assert detector.last_cycle.duration() > 300 * MIN


def test_shorter_resume_window_keeps_them_apart() -> None:
    detector, events = replay(replace(WASHER, resume_window_s=10 * MIN))
    finished = [e.cycle for e in events if e.kind == EventKind.FINISHED]
    assert [e.kind for e in events].count(EventKind.RESUMED) == 0
    assert len(finished) == 2
    assert 145 * MIN < finished[0].duration() < 155 * MIN
    assert 145 * MIN < finished[1].duration() < 160 * MIN
    # The gap between the washes does not become a pause to learn from.
    assert max(detector.learned.longest_pauses) < 5 * MIN


def test_the_gap_is_offered_as_split_point() -> None:
    longest = quiet_stretches(MERGED, WASHER)[0]
    assert 150 * MIN < longest[0] < 154 * MIN
    assert 11 * MIN < longest[1] - longest[0] < 13 * MIN


def test_split_inside_the_gap() -> None:
    cycle = replace(MERGED, start=1_000_000.0, end=1_000_000.0 + MERGED.duration(), cost=0.62)
    cycle.program, cycle.program_source = "Pflegeleicht 60°C", LabelSource.MANUAL
    gap = quiet_stretches(cycle, WASHER)[0]
    first, second = split_cycle(cycle, (gap[0] + gap[1]) / 2, WASHER)

    assert first.duration() == pytest.approx(gap[0])
    assert second.start == pytest.approx(cycle.start + gap[1])
    assert second.end == cycle.end
    assert first.energy_wh + second.energy_wh == pytest.approx(cycle.energy_wh)
    assert first.cost + second.cost == pytest.approx(0.62)
    # The second wash heats for 60 degrees and takes the larger share.
    assert second.energy_wh > first.energy_wh
    assert second.peak_power_w > 2000
    assert second.trace[0][0] == 0.0
    assert all(p.program is None and p.program_source is None for p in (first, second))
    assert max(first.pauses + second.pauses, default=0.0) < 5 * MIN


def test_split_outside_a_quiet_stretch_cuts_there() -> None:
    first, second = split_cycle(MERGED, 30 * MIN, WASHER)
    assert first.duration() == pytest.approx(30 * MIN)
    assert second.start == pytest.approx(MERGED.start + 30 * MIN)


@pytest.mark.parametrize("at", [0.0, 30.0, MERGED.duration() - 30.0, MERGED.duration() + 60])
def test_split_needs_two_parts(at: float) -> None:
    with pytest.raises(ValueError):
        split_cycle(MERGED, at, WASHER)


def test_tracker_split_fixes_history_and_learning() -> None:
    detector, _ = replay(WASHER)
    merged = detector.last_cycle
    tracker = Tracker(WASHER, detector=detector, history=[merged])
    assert max(detector.learned.longest_pauses) > 10 * MIN
    end_delay_before = detector.end_delay
    count = detector.cycle_count

    gap = quiet_stretches(merged, WASHER)[0]
    first, second = tracker.split(merged.id, (gap[0] + gap[1]) / 2)
    assert tracker.history == [first, second]
    assert detector.last_cycle is second
    assert detector.cycle_count == count + 1
    assert max(detector.learned.longest_pauses) < 5 * MIN
    assert detector.end_delay < end_delay_before
    with pytest.raises(KeyError):
        tracker.split("nope", 60)

    restored = Tracker.from_dict(WASHER, json.loads(json.dumps(tracker.to_dict())))
    assert [c.id for c in restored.history] == [first.id, second.id]


def test_learned_replace() -> None:
    stats = LearnedStats()
    stats.longest_pauses.extend([1.0, 749.0, 2.0])
    assert stats.replace(749.0, [3.0, 4.0])
    assert list(stats.longest_pauses) == [1.0, 3.0, 4.0, 2.0]
    assert not stats.replace(999.0, [])
