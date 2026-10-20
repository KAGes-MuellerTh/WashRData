"""Leave-one-out evaluation of recognition and remaining time on stored cycles."""

from __future__ import annotations

import time

import pytest

from engine.evaluation import THRESHOLDS, evaluate, fill_missing, select_references

from .sim import MIN
from .test_matching import COTTON, QUICK, trained


def test_a_cycle_is_never_its_own_reference() -> None:
    bench = trained(COTTON, QUICK)
    tracker = bench.tracker
    cycle = tracker.history[-1]
    refs = select_references(tracker.history, tracker.programs, exclude=cycle.id)
    assert all(c.id != cycle.id for cs in refs.values() for c in cs)
    assert len(refs[cycle.program]) == 1


def test_evaluation_replays_each_labelled_cycle() -> None:
    bench = trained(COTTON, QUICK, runs=3)
    evaluation = evaluate(bench.tracker.history, bench.tracker.programs)

    assert len(evaluation.cycles) == 6
    for e in evaluation.cycles:
        assert e.final == e.program
        assert e.final_confidence >= 0.6
        first = e.first_shown(0.25)
        assert first is not None and first <= 30
    # Thresholds rise, so fewer cycles are labelled automatically.
    autos = [r.auto_correct for r in evaluation.thresholds]
    assert autos == sorted(autos, reverse=True)
    assert [r.threshold for r in evaluation.thresholds] == list(THRESHOLDS)


def test_remaining_time_error_is_measured() -> None:
    bench = trained(COTTON, QUICK, runs=3)
    evaluation = evaluate(bench.tracker.history, bench.tracker.programs)
    half = next(r for r in evaluation.remaining if r.progress == 0.5)
    assert half.cycles == 6
    assert half.mean_abs_error_s < 8 * MIN
    assert abs(half.bias_s) <= half.mean_abs_error_s


def test_recommendation_needs_enough_cycles() -> None:
    few = trained(COTTON, QUICK, runs=2)
    evaluation = evaluate(few.tracker.history, few.tracker.programs)
    assert len(evaluation.cycles) == 4
    assert evaluation.recommended_show is None and evaluation.recommended_auto is None

    many = trained(COTTON, QUICK, runs=3)
    evaluation = evaluate(many.tracker.history, many.tracker.programs)
    assert 0.15 <= evaluation.recommended_show <= evaluation.recommended_auto
    assert evaluation.recommended_auto >= 0.4
    row = next(r for r in evaluation.thresholds if r.threshold == evaluation.recommended_auto)
    assert row.auto_wrong == 0


def test_old_cycles_get_the_evaluated_recognition() -> None:
    bench = trained(COTTON, QUICK, runs=2)
    history = bench.tracker.history
    for c in history:  # as stored before 0.2.4
        c.recognised, c.known_programs = None, []
    evaluation = evaluate(history, bench.tracker.programs)
    assert fill_missing(history, evaluation) == 4
    assert all(c.recognition_retro for c in history)
    accuracy = bench.tracker.accuracy()
    assert (accuracy.total.cycles, accuracy.total.hits) == (4, 4)
    # Cycles with recorded recognition are left alone.
    assert fill_missing(history, evaluation) == 0


def test_full_history_evaluates_in_seconds() -> None:
    bench = trained(COTTON, QUICK, runs=10)
    started = time.perf_counter()
    evaluation = evaluate(bench.tracker.history, bench.tracker.programs)
    assert len(evaluation.cycles) == 20
    assert time.perf_counter() - started < 10


@pytest.mark.parametrize(("price", "expected"), [(None, None), (0.3, 0.3)])
def test_cost_follows_the_price(price: float | None, expected: float | None) -> None:
    bench = trained(COTTON, runs=1)
    bench.tracker.detector.price = price
    bench.run(COTTON, seed=3)
    cycle = bench.tracker.last_cycle
    if expected is None:
        assert cycle.cost is None
    else:
        assert cycle.cost == pytest.approx(cycle.energy_wh / 1000 * expected, rel=0.02)


def test_price_change_during_a_cycle() -> None:
    bench = trained(COTTON, runs=1)
    detector = bench.tracker.detector
    detector.price = 0.2
    rest, _ = bench.start(COTTON, 5, minutes=30)
    energy_before = detector.cycle.energy_wh
    cost_before = detector.cycle.cost
    detector.price = 0.4
    bench.finish(rest)
    cycle = bench.tracker.last_cycle
    assert cycle.cost == pytest.approx(cost_before + (cycle.energy_wh - energy_before) / 1000 * 0.4, rel=0.02)
