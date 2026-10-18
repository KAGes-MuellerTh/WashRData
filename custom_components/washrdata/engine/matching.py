"""Program recognition by comparing the running cycle with labelled cycles.

Curves are resampled to one mean value per minute and compressed with
log1p, so a 2000 W heater and a 250 W drum differ clearly while 0 W and 3 W
standby do not. The running cycle is aligned with each reference by
open-end dynamic time warping: the query (cycle so far) is matched to the
best-fitting *prefix* of the reference. That gives both a distance (which
program) and a position in the reference (how far along, how long to go).

The warping is incremental: each new minute adds one DTW row per reference,
so the cost per update is O(total reference length).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from statistics import median

from .model import CycleRecord

STEP_S = 60.0
# Below this many minutes nothing is reported.
MIN_POINTS = 5
# Cost of a non-diagonal DTW step, so time is only warped when it helps.
WARP_PENALTY = 0.05
# Mean cost per minute at which a match counts as no match at all.
MAX_SCORE = 0.8
# Reported programs need at least this confidence.
SHOW_CONFIDENCE = 0.25
# Closed-end matches must also have a plausible length.
MAX_LENGTH_RATIO = 1.4
POWER_SCALE_W = 20.0


def level(watts: float) -> float:
    return math.log1p(watts / POWER_SCALE_W)


def resample(trace: Sequence[tuple[float, float]], duration: float, step: float = STEP_S) -> list[float]:
    """Mean power per complete `step` window of a step-function trace.

    Each trace point holds its value until the next point; the last point
    holds until `duration`.
    """
    windows = int(duration // step)
    if not trace or windows <= 0:
        return []
    means: list[float] = []
    seg = 0
    for k in range(windows):
        a, b = k * step, (k + 1) * step
        energy = 0.0
        while seg + 1 < len(trace) and trace[seg + 1][0] <= a:
            seg += 1
        i = seg
        while i < len(trace):
            start = trace[i][0] if i > 0 else 0.0
            end = trace[i + 1][0] if i + 1 < len(trace) else math.inf
            lo, hi = max(a, start), min(b, end)
            if hi > lo:
                energy += trace[i][1] * (hi - lo)
            if end >= b:
                break
            i += 1
        means.append(energy / step)
    return means


def curve(cycle: CycleRecord, now: float | None = None) -> list[float]:
    return [level(w) for w in resample(cycle.trace, cycle.duration(now))]


def _next_row(prev: list[float] | None, ref: list[float], q: float) -> list[float]:
    row = [0.0] * len(ref)
    for j, r in enumerate(ref):
        cost = abs(q - r)
        if prev is None:
            row[j] = cost if j == 0 else row[j - 1] + cost + WARP_PENALTY
        else:
            best = prev[j - 1] if j else math.inf
            best = min(best, prev[j] + WARP_PENALTY)
            if j:
                best = min(best, row[j - 1] + WARP_PENALTY)
            row[j] = best + cost
    return row


@dataclass
class _Reference:
    program: str
    cycle_id: str
    curve: list[float]
    row: list[float] | None = None


@dataclass(frozen=True)
class MatchResult:
    program: str | None
    confidence: float
    remaining_s: float | None = None
    expected_duration_s: float | None = None
    manual: bool = False
    # (program, mean cost per minute), best first.
    candidates: tuple[tuple[str, float], ...] = ()

    @property
    def progress(self) -> float | None:
        if self.remaining_s is None or not self.expected_duration_s:
            return None
        return max(0.0, min(1.0, 1 - self.remaining_s / self.expected_duration_s))


def confidence(scores: Sequence[float]) -> float:
    """From per-program scores (lower is better), best first.

    Combines how good the best match is with how clearly it beats the
    runner-up: two similar programs give a low confidence until they diverge.
    """
    if not scores:
        return 0.0
    absolute = max(0.0, 1 - scores[0] / MAX_SCORE)
    if len(scores) == 1 or scores[1] <= 0:
        return absolute
    margin = (scores[1] - scores[0]) / scores[1]
    return absolute * min(1.0, 2 * margin)


@dataclass
class _Snapshot:
    points: int
    rows: list[list[float] | None] = field(default_factory=list)


class ProgramMatcher:
    """Tracks one running cycle against a fixed set of reference cycles."""

    def __init__(self, references: dict[str, list[CycleRecord]]) -> None:
        self._refs = [
            _Reference(program, c.id, vec)
            for program, cycles in references.items()
            for c in cycles
            if len(vec := curve(c)) >= MIN_POINTS
        ]
        self._points = 0

    @property
    def programs(self) -> set[str]:
        return {r.program for r in self._refs}

    def update(self, cycle: CycleRecord, now: float) -> None:
        """Feed the windows of `cycle` completed since the last call."""
        query = curve(cycle, now)
        for q in query[self._points :]:
            for ref in self._refs:
                ref.row = _next_row(ref.row, ref.curve, q)
        self._points = max(self._points, len(query))

    def snapshot(self) -> _Snapshot:
        return _Snapshot(self._points, [list(r.row) if r.row else None for r in self._refs])

    def result(self, elapsed_s: float, forced_program: str | None = None) -> MatchResult | None:
        """Open-end match of the cycle so far."""
        n = self._points
        if n < MIN_POINTS or not self._refs:
            return None
        per_program: dict[str, list[tuple[float, int, int]]] = {}
        for ref in self._refs:
            assert ref.row is not None
            j = min(range(len(ref.row)), key=ref.row.__getitem__)
            per_program.setdefault(ref.program, []).append((ref.row[j] / n, j, len(ref.curve)))
        ranked = sorted((min(s for s, _, _ in v), p) for p, v in per_program.items())
        candidates = tuple((p, round(s, 3)) for s, p in ranked)

        if forced_program is not None:
            program, conf, manual = forced_program, 1.0, True
        else:
            conf = confidence([s for s, _ in ranked])
            program = ranked[0][1] if conf >= SHOW_CONFIDENCE else None
            manual = False
        if program is None or program not in per_program:
            return MatchResult(program, conf, manual=manual, candidates=candidates)

        refs = per_program[program]
        best = min(s for s, _, _ in refs)
        # Remaining time from the references that fit, robust to one bad label.
        steps = [m - 1 - j for s, j, m in refs if s <= best * 1.5 + 1e-9]
        partial = elapsed_s - n * STEP_S
        remaining = max(0.0, median(steps) * STEP_S - partial)
        return MatchResult(
            program,
            conf,
            remaining_s=remaining,
            expected_duration_s=elapsed_s + remaining,
            manual=manual,
            candidates=candidates,
        )

    def final(self, snapshot: _Snapshot | None = None) -> tuple[str, float] | None:
        """Closed-end match of a finished cycle: program and confidence.

        `snapshot` is the state when the final quiet spell began, so the quiet
        minutes after the real end do not count against the match.
        """
        snap = snapshot or self.snapshot()
        n = snap.points
        if n < MIN_POINTS:
            return None
        per_program: dict[str, float] = {}
        for ref, row in zip(self._refs, snap.rows, strict=True):
            m = len(ref.curve)
            if row is None or max(n, m) / min(n, m) > MAX_LENGTH_RATIO:
                continue
            score = row[m - 1] / max(n, m)
            per_program[ref.program] = min(score, per_program.get(ref.program, math.inf))
        if not per_program:
            return None
        ranked = sorted((s, p) for p, s in per_program.items())
        return ranked[0][1], confidence([s for s, _ in ranked])
