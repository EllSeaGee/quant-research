"""Materializer tests (Contract section 8.10, 8.12): fill-independence of the
geometry stream and pre-anchor substrate sufficiency. (Second-MR reachability,
Contract section 8.11, is a Phase-3 / entry_sim concern and is not built here.)"""

import inspect

import pytest

from quant_research.setups import validators as V

from tests.fixtures import pipeline as P

VARIANTS = ["timeout", "invalidated_floor", "invalidated_reclaim"]


@pytest.mark.parametrize("variant", VARIANTS)
def test_fill_independence_stream_is_deterministic(variant):
    """Contract section 8.10: the materialized SetupUpdate stream is a function of
    bars only. Since no fill / EntryConfig / FillModel enters the materializer or
    constructor, the stream is byte-identical across repeated materializations and
    could not depend on any fill signal."""
    pipe = P.build_pipeline(variant)
    s1 = P.materialized_stream(pipe)
    s2 = P.materialized_stream(pipe)
    assert P.first_stream_diff(s1, s2) is None


def test_constructor_has_no_fill_or_config_parameter():
    """Structural guarantee behind fill-independence: the constructor seam exposes
    no fill / EntryConfig / stop / size parameter (Detector Spec section 8.7)."""
    sig = inspect.signature(pipe_ctor().compute_update)
    params = set(sig.parameters)
    forbidden = {"fill", "fills", "entry_config", "config", "stop", "size", "fill_model"}
    assert not (params & forbidden), f"constructor leaks a forbidden param: {params & forbidden}"


def pipe_ctor():
    from quant_research.setups.boundary import TrivialBoundaryConstructor
    return TrivialBoundaryConstructor()


@pytest.mark.parametrize("variant", VARIANTS)
def test_pre_anchor_substrate_sufficiency(variant):
    """Contract section 8.12: pre_anchor_lookback is large enough that the
    constructor's window (ATR period + pullback anchor) at every bar in the window
    never reaches before the first stored pre-anchor bar (no substrate underrun)."""
    pipe = P.build_pipeline(variant)
    opening = pipe.opening
    first_pre = opening.pre_anchor_bars[0].bar_index
    atr_period = opening.atr_period
    terminated = pipe.detection.terminated_at_bar
    for t in range(opening.entry_eligible_bar, terminated + 1):
        # earliest bar the constructor could touch at t: ATR window start (minus one
        # bar for the first TR's prev_close), and the pullback anchor.
        earliest_needed = min(t - atr_period, opening.pullback_start_bar)
        assert earliest_needed >= first_pre, (
            f"substrate underrun at t={t}: needs {earliest_needed}, "
            f"first pre-anchor bar is {first_pre}")
    # 7.13 also holds structurally
    assert V.validate_pre_anchor_substrate(opening).passed


def test_materialization_equivalence_property():
    """Contract section 7.14 / 8.1: the materialized stream equals the generation-time
    truncated stream (the checkable equivalence property)."""
    pipe = P.build_pipeline("timeout")
    full_bars = P.substrate_of(pipe)
    gen = P.truncated_stream(pipe.opening, full_bars, pipe.detection.terminated_at_bar,
                             pipe.constructor, pipe.maturity_fn)
    mat = P.materialized_stream(pipe)
    assert V.validate_materialization_equivalence(gen, mat).passed
