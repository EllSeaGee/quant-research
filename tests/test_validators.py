"""Phase 0 — validators run on hand-built valid and invalid instances and
correctly classify both, including a lifecycle whose stream is (wrongly)
truncated at a fill (flagged by 7.3 / 7.12)."""

from dataclasses import replace

import pytest

from quant_research.setups import validators as V
from quant_research.setups.contract import (
    CausalPrice,
    Direction,
    ProjectedLevel,
    SetupLifecycle,
    TerminationReason,
)
from tests.fixtures import builders as B


# --- valid instances all pass --------------------------------------------

def test_valid_lifecycle_passes_all_invariants():
    lc = B.make_lifecycle()
    entry = B.make_simulated_entry()
    results = V.validate_lifecycle(lc, entry=entry)
    fails = V.failures(results)
    assert not fails, f"unexpected failures: {[(f.invariant, f.message) for f in fails]}"


def test_valid_short_lifecycle_passes():
    # build a SHORT lifecycle with mirrored monotonicity/floor
    opening = B.make_opening(direction=Direction.SHORT)
    # For SHORT the floor sits above impulse_end; rebuild with mirror semantics.
    span = opening.impulse_end.price - opening.impulse_origin.price
    floor = opening.impulse_end.price + (2.0 / 3.0) * abs(span)
    opening = replace(opening, retracement_floor=floor,
                      impulse_origin=replace(opening.impulse_origin, price=130.0))
    # SHORT running extreme is a running max => non-decreasing; triggers <= floor
    eeb = opening.entry_eligible_bar
    updates = []
    for k in range(5):
        re = opening.impulse_end.price + 3.0 + k * 0.5
        updates.append(B.make_update(
            opening.setup_id, eeb + k, running_extreme_price=re, floor=floor,
            direction=Direction.SHORT, pullback_start_bar=opening.pullback_start_bar,
            impulse_end_price=opening.impulse_end.price,
            impulse_origin_price=opening.impulse_origin.price, with_trend=False,
        ))
    lc = SetupLifecycle(opening=opening, updates=tuple(updates),
                        terminated_at_bar=updates[-1].bar_index,
                        termination_reason=TerminationReason.TIMEOUT)
    fails = V.failures(V.validate_lifecycle(lc))
    assert not fails, f"unexpected SHORT failures: {[(f.invariant, f.message) for f in fails]}"


def test_valid_forward_path_passes():
    assert V.validate_forward_path(B.make_forward_path()).passed


def test_truncated_forward_path_passes_when_flagged():
    path = B.make_forward_path(truncated=True, short_by=5)
    assert V.validate_forward_path(path).passed


# --- specific invariant violations are caught ------------------------------

def test_71_causal_price_pivot_requires_strict():
    bad = CausalPrice(price=100.0, defining_bar=10, known_at_bar=10)  # equal, not strict
    assert V.validate_causal_price(bad, is_pivot=True).passed is False
    assert V.validate_causal_price(bad, is_pivot=False).passed is True


def test_71_projected_level_requires_future_active():
    bad = ProjectedLevel(price=100.0, computed_at_bar=10, active_at_bar=10)
    assert V.validate_projected_level(bad).passed is False


def test_72_update_knowledge_time_mismatch_caught():
    lc = B.make_lifecycle()
    u = lc.updates[1]
    bad_u = replace(u, mr_trigger_next=replace(u.mr_trigger_next,
                                               computed_at_bar=u.bar_index - 1))
    assert V.validate_update_knowledge_time(bad_u).passed is False


def test_73_stream_truncated_at_fill_is_flagged():
    """A lifecycle whose stream is wrongly truncated at a fill bar (last update
    earlier than terminated_at_bar) must be flagged by 7.3 and 7.12."""
    lc = B.make_lifecycle(n_updates=6)
    truncated = replace(lc, updates=lc.updates[:3])  # stops before terminated_at_bar
    assert V.validate_stream_span(truncated).passed is False
    assert V.validate_termination_consistency(truncated).passed is False


def test_73_gap_in_stream_flagged():
    lc = B.make_lifecycle()
    with_gap = replace(lc, updates=lc.updates[:2] + lc.updates[3:])
    assert V.validate_stream_span(with_gap).passed is False


def test_74_detection_readiness_violation():
    opening = B.make_opening()
    bad = replace(opening, entry_eligible_bar=opening.detection_bar + 2)
    assert V.validate_detection_readiness(bad).passed is False
    bad2 = replace(opening, detection_bar=opening.impulse_end.known_at_bar - 1)
    assert V.validate_detection_readiness(bad2).passed is False


def test_75_running_extreme_monotonicity_violation():
    lc = B.make_lifecycle(direction=Direction.LONG)
    u = lc.updates[2]
    bumped = replace(u, running_extreme=replace(u.running_extreme,
                                                price=u.running_extreme.price + 100))
    bad_lc = replace(lc, updates=lc.updates[:2] + (bumped,) + lc.updates[3:])
    assert V.validate_running_extreme_monotonicity(bad_lc).passed is False


def test_76_retracement_floor_violation():
    lc = B.make_lifecycle()
    u = lc.updates[1]
    below = replace(u, mr_trigger_next=replace(u.mr_trigger_next,
                                               price=lc.opening.retracement_floor - 1.0))
    bad_lc = replace(lc, updates=(lc.updates[0], below) + lc.updates[2:])
    assert V.validate_retracement_floor(bad_lc).passed is False


def test_79_no_stop_or_size_guard_detects_forbidden_field():
    from dataclasses import dataclass

    @dataclass(frozen=True)
    class Leaky:
        setup_id: str
        candidate_stop: float

    assert V.validate_no_stop_or_size(Leaky("x", 1.0)).passed is False
    # real contract dataclasses pass
    assert V.validate_no_stop_or_size(B.make_opening()).passed is True
    assert V.validate_no_stop_or_size(B.make_simulated_entry()).passed is True


def test_710_fill_causality_violations():
    entry = B.make_simulated_entry(mr_filled=True, mr_fill_bar=40)  # before eeb=51
    assert V.validate_fill_causality(entry, 51).passed is False
    # unfilled with geometry present
    ok_unfilled = B.make_simulated_entry(mr_filled=False)
    assert V.validate_fill_causality(ok_unfilled, 51).passed is True


def test_711_both_maturities_required():
    lc = B.make_lifecycle()
    u = lc.updates[0]
    bad = replace(u, maturity_retracement=None)
    bad_lc = replace(lc, updates=(bad,) + lc.updates[1:])
    assert V.validate_both_maturities(bad_lc).passed is False


def test_712_termination_reason_must_be_two_valued():
    lc = B.make_lifecycle()
    # only INVALIDATED / TIMEOUT are valid members; construct valid ones both pass
    assert V.validate_termination_consistency(
        replace(lc, termination_reason=TerminationReason.INVALIDATED)).passed is True
    assert V.validate_termination_consistency(
        replace(lc, termination_reason=TerminationReason.TIMEOUT)).passed is True


def test_713_pre_anchor_substrate_violations():
    opening = B.make_opening(pre_anchor_lookback=45)
    # lookback mismatch
    bad = replace(opening, pre_anchor_lookback=44)
    assert V.validate_pre_anchor_substrate(bad).passed is False
    # window not abutting anchor
    shifted = replace(opening, pre_anchor_bars=tuple(
        B.make_bar(b.bar_index - 3) for b in opening.pre_anchor_bars))
    assert V.validate_pre_anchor_substrate(shifted).passed is False


def test_714_materialization_equivalence():
    lc = B.make_lifecycle()
    assert V.validate_materialization_equivalence(lc.updates, lc.updates).passed is True
    perturbed = list(lc.updates)
    u = perturbed[2]
    perturbed[2] = replace(u, atr=u.atr + 0.001)
    assert V.validate_materialization_equivalence(lc.updates, perturbed).passed is False


def test_715_d_struct_consistency():
    lc = B.make_lifecycle(with_trend=True)
    assert V.validate_d_struct_consistency(lc).passed is True
    u = lc.updates[1]
    bad = replace(u, d_struct=u.d_struct + 5.0)
    bad_lc = replace(lc, updates=(lc.updates[0], bad) + lc.updates[2:])
    assert V.validate_d_struct_consistency(bad_lc).passed is False
