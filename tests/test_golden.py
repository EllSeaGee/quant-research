"""Golden synthetic test (Contract section 8.6). On a hand-built series with known
impulse/pullback geometry the detector emits the expected impulse_origin,
impulse_end, ATR, and retracement_floor, and the materialized stream emits the
expected running_extreme / mr_trigger_next sequence — recomputed independently
from the bars via the Phase-2 estimator C — within tick tolerance."""

from quant_research.setups.adapter import InMemoryBarProvider
from quant_research.setups import primitives
from quant_research.setups.boundary import BoundaryParams, _clip01

from tests.fixtures import pipeline as P, synthetic

TOL = 1e-6


def test_opening_geometry_matches_construction():
    pipe = P.build_pipeline("timeout")
    o = pipe.opening
    # impulse_end = pivot high 124 (close) + HALF; impulse_origin = pivot low 113 - HALF
    assert abs(o.impulse_end.price - (synthetic.END_PRICE + synthetic.HALF)) < TOL
    assert abs(o.impulse_origin.price - (synthetic.ORIGIN_PRICE - synthetic.HALF)) < TOL
    assert o.impulse_end.defining_bar == synthetic.END_BAR
    assert o.impulse_origin.defining_bar == synthetic.ORIGIN_BAR
    assert o.detection_bar == synthetic.DETECTION_BAR
    assert o.entry_eligible_bar == synthetic.ENTRY_ELIGIBLE_BAR
    # retracement_floor = end - (2/3)(end - origin), using the detector's causal prices
    expected_floor = o.impulse_end.price - (2.0 / 3.0) * (o.impulse_end.price - o.impulse_origin.price)
    assert abs(o.retracement_floor - expected_floor) < TOL


def test_running_extreme_and_mr_trigger_stream_match_independent_recompute():
    """Recompute estimator C (OLS on pullback lows projected to t+1) and the
    alpha-offset MR trigger independently from the bars, and confirm the real
    constructor's stream matches within tick tolerance (Detector Spec v1.1 s.8)."""
    pipe = P.build_pipeline("timeout")
    bars, meta = synthetic.make_long_series("timeout")
    by_index = {b.bar_index: b for b in bars}
    o = pipe.opening
    lc = pipe.lifecycle
    ps = o.pullback_start_bar
    bp = BoundaryParams()
    budget = (2.0 / 3.0) * abs(o.impulse_end.price - o.impulse_origin.price)

    for u in lc.updates:
        t = u.bar_index
        pb = [by_index[i] for i in range(ps, t + 1)]
        # expected running_extreme = min low over pullback bars [ps, t]
        expected_re = min(b.low for b in pb)
        assert abs(u.running_extreme.price - expected_re) < TOL, f"running_extreme at {t}"

        # expected atr (simple mean TR over atr_period ending at t)
        window = [by_index[i] for i in range(0, t + 1)]
        expected_atr = primitives.atr_ending_at(window, t, o.atr_period)
        assert abs(u.atr - expected_atr) < TOL, f"atr at {t}"

        # expected countertrend boundary: OLS on the last W_fit pullback lows -> t+1
        fit_bars = pb[-bp.w_fit:]
        if len(fit_bars) <= bp.warm_up_bars:
            expected_boundary = expected_re
        else:
            expected_boundary, _ = primitives.ols_project(
                [float(b.bar_index) for b in fit_bars],
                [b.low for b in fit_bars], float(t + 1))
        assert abs(u.countertrend_boundary_next.price - expected_boundary) < TOL, \
            f"countertrend_boundary at {t}"

        # expected mr_trigger = max(boundary - alpha(m_hat)*V, floor)  [LONG]
        v = primitives.mean_true_range_between(window, ps, t)
        m_hat = _clip01(abs(o.impulse_end.price - expected_re) / budget) if budget > 0 else 0.0
        alpha = bp.alpha(m_hat)
        expected_trigger = max(expected_boundary - alpha * v, o.retracement_floor)
        assert abs(u.mr_trigger_next.price - expected_trigger) < TOL, f"mr_trigger at {t}"

        # projection horizon t+1; both maturities present
        assert u.mr_trigger_next.active_at_bar == t + 1
        assert u.countertrend_boundary_next.active_at_bar == t + 1
        assert u.maturity_barcount == t - ps
        assert u.maturity_retracement is not None


def test_running_extreme_monotonic_nonincreasing_long():
    pipe = P.build_pipeline("timeout")
    prices = [u.running_extreme.price for u in pipe.lifecycle.updates]
    for a, b in zip(prices, prices[1:]):
        assert b <= a
