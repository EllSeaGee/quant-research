"""Phase-2 boundary-constructor tests (Detector Spec v1.1 sections 8-9).

Covers the real estimator C: the OLS fit to the countertrend-side extrema
projected to t+1, the maturity-decaying alpha offset and its endpoints, the
warm-up rule, the retracement-floor clamp, both-maturities emission, the
with-trend boundary / d_struct, causal truncation-invariance, and the sanity
check that the real constructor is materially different from the trivial one
(Implementation Plan Phase 2 acceptance).

The constructor is exercised both on hand-built windows (for the deterministic
OLS / alpha / warm-up checks) and on the shared synthetic pipeline (for the
spine-level truncation and differ-from-trivial checks).
"""

import math

import pytest

from quant_research.setups.contract import Bar, CausalPrice, Direction
from quant_research.setups.boundary import (
    BoundaryParams,
    RealBoundaryConstructor,
    TrivialBoundaryConstructor,
    maturity_barcount_fn,
    maturity_retracement_fn,
    _clip01,
)
from quant_research.setups import primitives

from tests.fixtures import builders as B, pipeline as P


# ---------------------------------------------------------------------------
# helpers — a hand-built LONG opening + a controllable bar window
# ---------------------------------------------------------------------------

def _long_opening():
    # impulse_end=110, origin=90 => floor = 110 - (2/3)*20 = 96.6667;
    # pullback_start_bar=46, detection_bar=50, entry_eligible_bar=51.
    return B.make_opening(direction=Direction.LONG, detection_bar=50,
                          impulse_origin_price=90.0, impulse_end_price=110.0)


def _window(pullback_lows, *, pre_level=108.0, pre_start=32, ps=46, half=1.0):
    """A bar window: flat pre bars [pre_start, ps-1] at ``pre_level`` then pullback
    bars from ``ps`` whose lows are ``pullback_lows`` (highs = low + 2*half).
    Returns (bars, t) where t is the last pullback bar's index."""
    bars = []
    for i in range(pre_start, ps):
        bars.append(Bar(i, f"t{i}", pre_level, pre_level + half, pre_level - half,
                        pre_level, 1000.0))
    for k, lo in enumerate(pullback_lows):
        idx = ps + k
        hi = lo + 2 * half
        c = lo + half
        bars.append(Bar(idx, f"t{idx}", c, hi, lo, c, 1000.0))
    return bars, bars[-1].bar_index


def _ctor(params=None):
    return RealBoundaryConstructor(params)


# ---------------------------------------------------------------------------
# estimator C — OLS fit projected to t+1
# ---------------------------------------------------------------------------

def test_countertrend_boundary_is_ols_on_pullback_lows_projected_to_next():
    opening = _long_opening()
    lows = [107.0, 105.0, 103.0, 101.0]          # linear -2/bar
    bars, t = _window(lows)
    u = _ctor().compute_update(opening, bars, t, maturity_retracement_fn)
    # independent OLS on the countertrend-side lows over [ps, t]
    ps = opening.pullback_start_bar
    fit_bars = [b for b in bars if ps <= b.bar_index <= t]
    expected, rms = primitives.ols_project(
        [float(b.bar_index) for b in fit_bars], [b.low for b in fit_bars], float(t + 1))
    assert abs(u.countertrend_boundary_next.price - expected) < 1e-9
    assert u.countertrend_boundary_next.active_at_bar == t + 1
    assert u.countertrend_boundary_next.computed_at_bar == t
    # a perfectly linear series => zero residual dispersion
    assert u.fit_dispersion is not None and abs(u.fit_dispersion - rms) < 1e-9
    assert abs(u.fit_dispersion) < 1e-9


def test_fit_dispersion_is_rms_residual_and_positive_on_noisy_lows():
    opening = _long_opening()
    lows = [107.0, 104.0, 106.0, 101.0, 103.0]   # noisy, not collinear
    bars, t = _window(lows)
    u = _ctor().compute_update(opening, bars, t, maturity_retracement_fn)
    assert u.fit_dispersion is not None and u.fit_dispersion > 0


def test_fit_window_capped_at_w_fit():
    """Only the last W_fit countertrend-side extrema drive the fit (section 8.2)."""
    opening = _long_opening()
    lows = [120.0] + [107.0 - k for k in range(10)]   # first extreme is an old outlier
    bars, t = _window(lows)
    p = BoundaryParams(w_fit=8)
    u = _ctor(p).compute_update(opening, bars, t, maturity_retracement_fn)
    fit_bars = [b for b in bars if opening.pullback_start_bar <= b.bar_index <= t][-p.w_fit:]
    expected, _ = primitives.ols_project(
        [float(b.bar_index) for b in fit_bars], [b.low for b in fit_bars], float(t + 1))
    assert abs(u.countertrend_boundary_next.price - expected) < 1e-9


# ---------------------------------------------------------------------------
# warm-up (section 8.2)
# ---------------------------------------------------------------------------

def test_warm_up_single_extreme_is_flat_and_dispersion_none():
    opening = _long_opening()
    bars, t = _window([107.0])                    # a single pullback bar
    u = _ctor().compute_update(opening, bars, t, maturity_retracement_fn)
    assert t == opening.pullback_start_bar
    assert abs(u.countertrend_boundary_next.price - u.running_extreme.price) < 1e-9
    assert u.fit_dispersion is None
    # with-trend boundary / d_struct are None during warm-up
    assert u.with_trend_boundary_next is None
    assert u.d_struct is None


def test_fit_defined_from_second_pullback_bar():
    opening = _long_opening()
    bars, t = _window([107.0, 105.0])             # two pullback bars
    u = _ctor().compute_update(opening, bars, t, maturity_retracement_fn)
    assert u.fit_dispersion is not None
    assert u.with_trend_boundary_next is not None
    assert u.d_struct is not None


# ---------------------------------------------------------------------------
# alpha(m) offset (section 8.5)
# ---------------------------------------------------------------------------

def test_alpha_endpoints_and_monotonic_decay():
    p = BoundaryParams()
    assert abs(p.alpha(0.0) - p.alpha0) < 1e-12          # early: high offset
    assert abs(p.alpha(1.0) - p.alpha_end) < 1e-12       # late: slightly inside
    # decays monotonically from alpha0 toward alpha_end
    vals = [p.alpha(m / 10) for m in range(11)]
    assert all(b <= a + 1e-12 for a, b in zip(vals, vals[1:]))
    assert p.alpha(1.0) < 0  # allows entry slightly inside the boundary at maturity


def test_alpha_clips_out_of_range_maturity():
    p = BoundaryParams()
    assert p.alpha(-5.0) == p.alpha(0.0)
    assert p.alpha(5.0) == p.alpha(1.0)


def test_convex_decay_shape_holds_offset_higher_than_linear_midrange():
    linear = BoundaryParams(decay_shape="linear")
    convex = BoundaryParams(decay_shape="convex", convex_power=2.0)
    # at a mid maturity the convex shape keeps the offset closer to alpha0 (higher)
    assert convex.alpha(0.5) > linear.alpha(0.5)
    # endpoints coincide
    assert abs(convex.alpha(0.0) - linear.alpha(0.0)) < 1e-12
    assert abs(convex.alpha(1.0) - linear.alpha(1.0)) < 1e-12


def test_mr_trigger_equals_boundary_minus_alpha_v_long():
    opening = _long_opening()
    lows = [107.0, 105.0, 103.0]
    bars, t = _window(lows)
    ctor = _ctor()
    u = ctor.compute_update(opening, bars, t, maturity_retracement_fn)
    v = primitives.mean_true_range_between(bars, opening.pullback_start_bar, t)
    m_hat = maturity_retracement_fn(opening, bars, t)
    alpha = ctor.params.alpha(m_hat)
    expected = max(u.countertrend_boundary_next.price - alpha * v, opening.retracement_floor)
    assert abs(u.mr_trigger_next.price - expected) < 1e-9


# ---------------------------------------------------------------------------
# floor clamp (section 8.6 / Contract 7.6)
# ---------------------------------------------------------------------------

def test_mr_trigger_clamped_to_floor_on_deep_pullback():
    opening = _long_opening()                     # floor ~ 96.6667
    # lows dive toward the floor; boundary - alpha*V would cross it
    lows = [104.0, 101.0, 99.0, 97.5, 97.0]
    bars, t = _window(lows)
    u = _ctor().compute_update(opening, bars, t, maturity_retracement_fn)
    assert u.mr_trigger_next.price >= opening.retracement_floor - 1e-9


# ---------------------------------------------------------------------------
# both maturities emitted every update (Contract 7.11)
# ---------------------------------------------------------------------------

def test_both_maturities_emitted():
    opening = _long_opening()
    bars, t = _window([107.0, 105.0, 103.0])
    u = _ctor().compute_update(opening, bars, t, maturity_retracement_fn)
    assert u.maturity_barcount == t - opening.pullback_start_bar
    budget = (2.0 / 3.0) * (opening.impulse_end.price - opening.impulse_origin.price)
    expected_ret = (opening.impulse_end.price - u.running_extreme.price) / budget
    assert abs(u.maturity_retracement - expected_ret) < 1e-9


def test_maturity_fn_choice_is_a_config_flip_not_a_field_change():
    """Swapping the maturity_fn changes only which measure drives alpha; BOTH
    maturity fields are still emitted identically (section 8.4)."""
    opening = _long_opening()
    bars, t = _window([107.0, 105.0, 103.0])
    u_ret = _ctor().compute_update(opening, bars, t, maturity_retracement_fn)
    u_bc = _ctor().compute_update(opening, bars, t, maturity_barcount_fn)
    assert u_ret.maturity_barcount == u_bc.maturity_barcount
    assert abs(u_ret.maturity_retracement - u_bc.maturity_retracement) < 1e-12
    # the two normalised maturities generally differ, so the triggers differ
    assert u_ret.mr_trigger_next.price != u_bc.mr_trigger_next.price


# ---------------------------------------------------------------------------
# with-trend boundary + d_struct (section 9 / Contract 7.15)
# ---------------------------------------------------------------------------

def test_with_trend_boundary_and_d_struct_match_channel_height():
    opening = _long_opening()
    bars, t = _window([107.0, 105.0, 103.0])
    u = _ctor().compute_update(opening, bars, t, maturity_retracement_fn)
    assert u.with_trend_boundary_next is not None
    implied = u.with_trend_boundary_next.price - u.running_extreme.price  # LONG
    assert abs(u.d_struct - implied) < 1e-9


# ---------------------------------------------------------------------------
# running_extreme is the literal running min (monotone), known at t
# ---------------------------------------------------------------------------

def test_running_extreme_is_literal_min_low_known_at_t():
    opening = _long_opening()
    bars, t = _window([107.0, 105.0, 108.0, 103.0])   # note a bounce up mid-way
    u = _ctor().compute_update(opening, bars, t, maturity_retracement_fn)
    ps = opening.pullback_start_bar
    expected = min(b.low for b in bars if ps <= b.bar_index <= t)
    assert abs(u.running_extreme.price - expected) < 1e-9
    assert u.running_extreme.known_at_bar == t


# ---------------------------------------------------------------------------
# no-look-ahead guard
# ---------------------------------------------------------------------------

def test_constructor_requires_a_bar_at_t():
    opening = _long_opening()
    bars, t = _window([107.0, 105.0])
    # drop the bar at t: the constructor must refuse (it may see only bars <= t and
    # requires the bar AT t to compute the update)
    trimmed = [b for b in bars if b.bar_index < t]
    with pytest.raises(ValueError):
        _ctor().compute_update(opening, trimmed, t, maturity_retracement_fn)


def test_constructor_ignores_bars_beyond_t():
    """Handed future bars, the constructor must emit exactly what it would on
    history truncated at t (causal purity, section 8.7)."""
    opening = _long_opening()
    bars, t = _window([107.0, 105.0, 103.0, 101.0, 99.0])
    mid = t - 2
    trunc = [b for b in bars if b.bar_index <= mid]
    full = bars  # includes bars > mid
    u_trunc = _ctor().compute_update(opening, trunc, mid, maturity_retracement_fn)
    u_full = _ctor().compute_update(opening, full, mid, maturity_retracement_fn)
    assert u_trunc == u_full


# ---------------------------------------------------------------------------
# spine-level: truncation invariance + materially different from trivial
# ---------------------------------------------------------------------------

VARIANTS = ["timeout", "invalidated_floor", "invalidated_reclaim"]


@pytest.mark.parametrize("variant", VARIANTS)
def test_real_constructor_truncation_invariant_over_stream(variant):
    pipe = P.build_pipeline(variant)
    full_bars = P.substrate_of(pipe)
    ref = P.full_history_stream(pipe.opening, full_bars, pipe.detection.terminated_at_bar,
                                pipe.constructor, pipe.maturity_fn)
    trunc = P.truncated_stream(pipe.opening, full_bars, pipe.detection.terminated_at_bar,
                               pipe.constructor, pipe.maturity_fn)
    assert P.first_stream_diff(ref, trunc) is None


def test_real_constructor_differs_materially_from_trivial():
    """Sanity check (Phase-2 acceptance): estimator C adds signal, not noise — its
    geometry is materially different from the trivial flat-at-running-extreme
    constructor on the same setup (a difference test, NOT byte-identity)."""
    pipe = P.build_pipeline("timeout")
    full_bars = P.substrate_of(pipe)
    real = P.truncated_stream(pipe.opening, full_bars, pipe.detection.terminated_at_bar,
                              RealBoundaryConstructor(), maturity_retracement_fn)
    trivial = P.truncated_stream(pipe.opening, full_bars, pipe.detection.terminated_at_bar,
                                 TrivialBoundaryConstructor(), maturity_retracement_fn)
    # at least one update's countertrend boundary or trigger differs materially
    diffs = [abs(a.countertrend_boundary_next.price - b.countertrend_boundary_next.price)
             + abs(a.mr_trigger_next.price - b.mr_trigger_next.price)
             for a, b in zip(real, trivial)]
    assert max(diffs) > 1e-6, "real constructor produced trivial-identical geometry"
