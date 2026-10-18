"""Detector, program library, cycle history and matcher of one appliance."""

from __future__ import annotations

from typing import Any

from .detector import CycleDetector
from .matching import MatchResult, ProgramMatcher, _Snapshot
from .model import CycleRecord, DetectorConfig, Event, EventKind, LabelSource, State

REFS_PER_PROGRAM = 5
KEEP_RECENT = 50
KEEP_LABELLED_PER_PROGRAM = 10
# Recognised programs with at least this confidence hold off the end while
# they still have this much to go.
HOLD_CONFIDENCE = 0.5
HOLD_MIN_REMAINING_S = 600.0
# Finished cycles matched at least this well are labelled automatically.
AUTO_LABEL_CONFIDENCE = 0.6

CURRENT = "current"
LAST = "last"


class Tracker:
    """Everything WashRData knows about one appliance, without Home Assistant.

    Programs are names. A program's references are its most recent labelled
    cycles (manual labels first). Labelling a finished cycle, by hand or
    automatically after a confident match, is how programs are learnt.
    """

    def __init__(
        self,
        config: DetectorConfig,
        detector: CycleDetector | None = None,
        programs: list[str] | None = None,
        history: list[CycleRecord] | None = None,
    ) -> None:
        self.detector = detector or CycleDetector(config)
        self.programs: list[str] = list(programs or [])
        self.history: list[CycleRecord] = list(history or [])
        self.match: MatchResult | None = None
        self._matcher: ProgramMatcher | None = None
        self._matcher_cycle: str | None = None
        self._checkpoint: _Snapshot | None = None

    @property
    def cycle(self) -> CycleRecord | None:
        return self.detector.cycle

    @property
    def last_cycle(self) -> CycleRecord | None:
        return self.history[-1] if self.history else None

    @property
    def state(self) -> State:
        return self.detector.state

    # -- samples ---------------------------------------------------------

    def update(self, ts: float, power: float | None) -> list[Event]:
        return self._after(ts, self.detector.update(ts, power))

    def tick(self, ts: float) -> list[Event]:
        return self._after(ts, self.detector.tick(ts))

    def _after(self, ts: float, events: list[Event]) -> list[Event]:
        out: list[Event] = []
        for event in events:
            if event.kind == EventKind.FINISHED and event.cycle is not None:
                self._on_finished(event.cycle)
            elif event.kind == EventKind.RESUMED and event.cycle is not None:
                self.history = [c for c in self.history if c.start != event.cycle.start]
            out.append(event)

        cycle = self.detector.cycle
        if cycle is None:
            self.match = None
            self.detector.hold_end = False
            return out

        matcher = self._matcher_for(cycle)
        if self.detector.state == State.PAUSED:
            if self._checkpoint is None:
                self._checkpoint = matcher.snapshot()
        else:
            self._checkpoint = None
        matcher.update(cycle, ts)
        forced = cycle.program if cycle.program_source == LabelSource.MANUAL else None
        previous = self.match.program if self.match else None
        self.match = matcher.result(cycle.duration(ts), forced)
        if self.match and self.match.program and self.match.program != previous:
            out.append(Event(EventKind.PROGRAM_DETECTED, ts, cycle))
        self.detector.hold_end = bool(
            self.match
            and self.match.program
            and self.match.confidence >= HOLD_CONFIDENCE
            and (self.match.remaining_s or 0.0) >= HOLD_MIN_REMAINING_S
        )
        return out

    def _matcher_for(self, cycle: CycleRecord) -> ProgramMatcher:
        if self._matcher is None or self._matcher_cycle != cycle.id:
            self._matcher = ProgramMatcher(self.references())
            self._matcher_cycle = cycle.id
            self._checkpoint = None
        return self._matcher

    def _on_finished(self, cycle: CycleRecord) -> None:
        if self._matcher is not None and self._matcher_cycle == cycle.id and cycle.program is None:
            final = self._matcher.final(self._checkpoint)
            if final is not None:
                program, conf = final
                cycle.match_confidence = round(conf, 3)
                if conf >= AUTO_LABEL_CONFIDENCE and not cycle.interrupted:
                    cycle.program = program
                    cycle.program_source = LabelSource.AUTO
        self.history.append(cycle)
        self._trim()
        self._invalidate()
        self.match = None

    def _invalidate(self) -> None:
        self._matcher = None
        self._matcher_cycle = None
        self._checkpoint = None

    def _trim(self) -> None:
        keep = {c.id for c in self.history[-KEEP_RECENT:]}
        for program in self.programs:
            labelled = [c for c in self.history if c.program == program]
            keep.update(c.id for c in labelled[-KEEP_LABELLED_PER_PROGRAM:])
        self.history = [c for c in self.history if c.id in keep]

    # -- programs --------------------------------------------------------

    def references(self) -> dict[str, list[CycleRecord]]:
        refs: dict[str, list[CycleRecord]] = {}
        for program in self.programs:
            labelled = [c for c in self.history if c.program == program and not c.interrupted]
            labelled.sort(key=lambda c: (c.program_source == LabelSource.MANUAL, c.start), reverse=True)
            if labelled:
                refs[program] = labelled[:REFS_PER_PROGRAM]
        return refs

    def find_cycle(self, target: str) -> CycleRecord | None:
        if target == CURRENT:
            return self.detector.cycle
        if target == LAST:
            return self.last_cycle
        return next((c for c in self.history if c.id == target), None)

    def label(self, target: str, program: str | None) -> CycleRecord:
        """Label a cycle by hand; `None` removes the label.

        `target` is "current", "last" or a cycle id. Unknown programs are created.
        """
        cycle = self.find_cycle(target)
        if cycle is None:
            raise KeyError(target)
        if program is not None:
            self.create_program(program)
        cycle.program = program
        cycle.program_source = LabelSource.MANUAL if program else None
        if cycle is not self.detector.cycle:
            self._invalidate()
        return cycle

    def create_program(self, name: str) -> None:
        name = name.strip()
        if not name:
            raise ValueError("empty program name")
        if name not in self.programs:
            self.programs.append(name)

    def rename_program(self, old: str, new: str) -> None:
        new = new.strip()
        if old not in self.programs:
            raise KeyError(old)
        if not new:
            raise ValueError("empty program name")
        if new in self.programs and new != old:
            raise ValueError(f"program {new!r} exists")
        self.programs[self.programs.index(old)] = new
        for c in self._all_cycles():
            if c.program == old:
                c.program = new
        self._invalidate()

    def delete_program(self, name: str) -> None:
        if name not in self.programs:
            raise KeyError(name)
        self.programs.remove(name)
        for c in self._all_cycles():
            if c.program == name:
                c.program = None
                c.program_source = None
        self._invalidate()

    def _all_cycles(self) -> list[CycleRecord]:
        return [*self.history, *([self.detector.cycle] if self.detector.cycle else [])]

    # -- persistence -----------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "detector": self.detector.to_dict(),
            "programs": list(self.programs),
            "cycles": [c.to_dict() for c in self.history],
        }

    @classmethod
    def from_dict(cls, config: DetectorConfig, data: dict[str, Any]) -> Tracker:
        return cls(
            config,
            detector=CycleDetector.from_dict(config, data.get("detector", {})),
            programs=data.get("programs", []),
            history=[CycleRecord.from_dict(c) for c in data.get("cycles", [])],
        )
