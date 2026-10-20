"""Recognition and remaining time measured on the stored cycles, leave-one-out.

Each labelled, complete cycle is replayed minute by minute against the
references the other cycles give; a cycle never serves as its own reference.
That shows how recognition does on the user's own runs: which program it
shows when and how sure it is, what it says at the end, and how far off the
remaining time is. Thresholds can then be chosen from that instead of guessed.

The replay costs a few seconds for a full history, so callers run it outside
the event loop and on a copy of the cycles.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from statistics import mean, median

from .matching import MIN_POINTS, STEP_S, ProgramMatcher
from .model import CycleRecord, LabelSource

REFS_PER_PROGRAM = 5
# Thresholds the evaluation compares, as confidences.
THRESHOLDS = tuple(round(0.15 + 0.05 * i, 2) for i in range(14))
# Remaining time is judged at these shares of the cycle.
PROGRESS_POINTS = (0.25, 0.5, 0.75)
# Recommendations need this many evaluated cycles.
MIN_CYCLES = 5
# Share of cycles that may show a wrong program at some point.
MAX_WRONG_SHOWN = 0.1
# Recommended thresholds stay within these bounds.
MIN_SHOW, MIN_AUTO = 0.15, 0.4


def select_references(
    cycles: list[CycleRecord], programs: list[str], exclude: str | None = None
) -> dict[str, list[CycleRecord]]:
    """The most recent labelled, complete cycles of each program, manual labels first."""
    refs: dict[str, list[CycleRecord]] = {}
    for program in programs:
        labelled = [c for c in cycles if c.program == program and not c.interrupted and c.id != exclude]
        labelled.sort(key=lambda c: (c.program_source == LabelSource.MANUAL, c.start), reverse=True)
        if labelled:
            refs[program] = labelled[:REFS_PER_PROGRAM]
    return refs


@dataclass(frozen=True)
class Minute:
    minute: int
    # What recognition says on its own.
    recognised: str | None
    confidence: float
    # Remaining time from the references of the cycle's real program.
    remaining_s: float | None


@dataclass(frozen=True)
class CycleEvaluation:
    cycle_id: str
    program: str
    duration_s: float
    known_programs: list[str]
    final: str | None
    final_confidence: float
    minutes: list[Minute]

    def first_shown(self, threshold: float) -> int | None:
        """First minute the right program was shown."""
        return next(
            (m.minute for m in self.minutes if m.recognised == self.program and m.confidence >= threshold),
            None,
        )

    def wrong_shown(self, threshold: float) -> bool:
        return any(m.recognised != self.program and m.confidence >= threshold for m in self.minutes)

    def remaining_error(self, progress: float) -> float | None:
        """Predicted minus real remaining time at `progress`; positive means too long."""
        minute = round(progress * self.duration_s / STEP_S)
        point = next((m for m in self.minutes if m.minute == minute), None)
        if point is None or point.remaining_s is None:
            return None
        return point.remaining_s - (self.duration_s - minute * STEP_S)


@dataclass(frozen=True)
class ThresholdRow:
    threshold: float
    # Display: cycles that showed a wrong program at some point, cycles that
    # never showed the right one, median minute the right one appeared.
    wrong_shown: int
    never_shown: int
    first_shown_min: float | None
    # Automatic label at the end.
    auto_correct: int
    auto_wrong: int
    auto_missed: int


@dataclass(frozen=True)
class RemainingRow:
    progress: float
    cycles: int
    mean_abs_error_s: float | None
    bias_s: float | None


@dataclass(frozen=True)
class Evaluation:
    cycles: list[CycleEvaluation] = field(default_factory=list)
    thresholds: list[ThresholdRow] = field(default_factory=list)
    remaining: list[RemainingRow] = field(default_factory=list)
    recommended_show: float | None = None
    recommended_auto: float | None = None


def evaluate_cycle(cycle: CycleRecord, references: dict[str, list[CycleRecord]]) -> CycleEvaluation | None:
    """Replay one finished cycle; None when its program has no usable reference."""
    if not cycle.program or cycle.end is None:
        return None
    matcher = ProgramMatcher(references)
    if cycle.program not in matcher.programs:
        return None
    # An open copy, so the curve grows minute by minute as it did live.
    running = replace(cycle, end=None)
    duration = cycle.duration()
    minutes: list[Minute] = []
    for k in range(MIN_POINTS, int(duration // STEP_S) + 1):
        elapsed = k * STEP_S
        matcher.update(running, cycle.start + elapsed)
        free = matcher.result(elapsed)
        forced = matcher.result(elapsed, cycle.program)
        minutes.append(
            Minute(
                k,
                free.recognised if free else None,
                round(free.recognition_confidence, 3) if free else 0.0,
                forced.remaining_s if forced else None,
            )
        )
    final = matcher.final()
    return CycleEvaluation(
        cycle_id=cycle.id,
        program=cycle.program,
        duration_s=duration,
        known_programs=sorted(matcher.programs),
        final=final[0] if final else None,
        final_confidence=round(final[1], 3) if final else 0.0,
        minutes=minutes,
    )


def _threshold_row(evals: list[CycleEvaluation], t: float) -> ThresholdRow:
    first = [m for e in evals if (m := e.first_shown(t)) is not None]
    auto = [(e.final == e.program, e.final_confidence >= t) for e in evals]
    return ThresholdRow(
        threshold=t,
        wrong_shown=sum(e.wrong_shown(t) for e in evals),
        never_shown=len(evals) - len(first),
        first_shown_min=median(first) if first else None,
        auto_correct=sum(right and sure for right, sure in auto),
        auto_wrong=sum(not right and sure for right, sure in auto),
        auto_missed=sum(not sure for _, sure in auto),
    )


def _remaining_row(evals: list[CycleEvaluation], progress: float) -> RemainingRow:
    errors = [err for e in evals if (err := e.remaining_error(progress)) is not None]
    return RemainingRow(
        progress=progress,
        cycles=len(errors),
        mean_abs_error_s=mean(abs(e) for e in errors) if errors else None,
        bias_s=mean(errors) if errors else None,
    )


def _recommend(rows: list[ThresholdRow], cycles: int) -> tuple[float | None, float | None]:
    """Lowest thresholds that keep wrong displays rare and wrong automatic labels out."""
    if cycles < MIN_CYCLES:
        return None, None
    show = next(
        (r.threshold for r in rows if r.threshold >= MIN_SHOW and r.wrong_shown <= MAX_WRONG_SHOWN * cycles),
        None,
    )
    auto = next((r.threshold for r in rows if r.threshold >= MIN_AUTO and r.auto_wrong == 0), None)
    if show is not None and auto is not None:
        show = min(show, auto)
    return show, auto


def evaluate(cycles: list[CycleRecord], programs: list[str]) -> Evaluation:
    evals = [
        e
        for c in cycles
        if c.program and not c.interrupted
        if (e := evaluate_cycle(c, select_references(cycles, programs, exclude=c.id))) is not None
    ]
    rows = [_threshold_row(evals, t) for t in THRESHOLDS]
    show, auto = _recommend(rows, len(evals))
    return Evaluation(
        cycles=evals,
        thresholds=rows,
        remaining=[_remaining_row(evals, p) for p in PROGRESS_POINTS],
        recommended_show=show,
        recommended_auto=auto,
    )


def fill_missing(cycles: list[CycleRecord], evaluation: Evaluation) -> int:
    """Give cycles without recorded recognition (from before 0.2.4) the evaluated one."""
    by_id = {e.cycle_id: e for e in evaluation.cycles}
    filled = 0
    for c in cycles:
        e = by_id.get(c.id)
        if e is None or c.known_programs or c.recognised is not None:
            continue
        c.recognised = e.final
        c.match_confidence = e.final_confidence
        c.known_programs = list(e.known_programs)
        c.recognition_retro = True
        filled += 1
    return filled
