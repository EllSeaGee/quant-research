"""Causality assertions (Contract section 8.2) — all 15 section-7 invariants hold
across generated lifecycles; plus the no-look-ahead property that the materializer
never consumes a bar with bar_index > t (Contract section 8.3)."""

import pytest

from quant_research.setups import validators as V
from quant_research.setups.boundary import maturity_retracement_fn
from quant_research.setups.materializer import OnDemandGeometryMaterializer

from tests.fixtures import pipeline as P

VARIANTS = ["timeout", "invalidated_floor", "invalidated_reclaim"]


@pytest.mark.parametrize("variant", VARIANTS)
def test_all_invariants_hold_for_every_detected_setup(variant):
    dets = P.all_detections(variant)
    assert dets, "no setups detected"
    from quant_research.setups.adapter import InMemoryBarProvider
    from quant_research.setups.path_recorder import PathRecorder
    from quant_research.setups.geometry_access import build_default_access, PersistedSetup
    from tests.fixtures import synthetic

    bars, meta = synthetic.make_long_series(variant)
    provider = InMemoryBarProvider({("ES", "1d"): bars})
    recorder = PathRecorder()
    for det in dets:
        fp = recorder.record(provider, "ES", "1d", det.opening.setup_id,
                             det.opening.entry_eligible_bar, meta.data_end_index)
        access = build_default_access()
        access.register(PersistedSetup(det.opening, fp, det.terminated_at_bar,
                                       det.termination_reason))
        lc = access.get_lifecycle(det.opening.setup_id)
        fails = V.failures(V.validate_lifecycle(lc))
        assert not fails, (f"invariant failures for {det.opening.setup_id}: "
                           f"{[(f.invariant, f.message) for f in fails]}")


def test_pivot_causal_prices_strictly_greater():
    """Opening impulse endpoints are pivots: known_at_bar > defining_bar (7.1)."""
    for det in P.all_detections("timeout"):
        o = det.opening
        assert V.validate_causal_price(o.impulse_origin, is_pivot=True).passed
        assert V.validate_causal_price(o.impulse_end, is_pivot=True).passed
        # known_at_bar == defining_bar + N (N=2)
        assert o.impulse_end.known_at_bar == o.impulse_end.defining_bar + 2
        assert o.impulse_origin.known_at_bar == o.impulse_origin.defining_bar + 2


class _MaxBarSpy:
    """Wraps a constructor and records the max bar_index it is handed per call."""
    def __init__(self, inner):
        self.inner = inner
        self.violations = []

    def compute_update(self, opening, bars_up_to_t, t, maturity_fn):
        if bars_up_to_t:
            mx = max(b.bar_index for b in bars_up_to_t)
            if mx > t:
                self.violations.append((t, mx))
        return self.inner.compute_update(opening, bars_up_to_t, t, maturity_fn)


def test_materializer_never_passes_bar_beyond_t():
    """Contract section 8.3 / convention 2: the materializer restricts the window to
    bar_index <= t for every t."""
    from tests.fixtures import synthetic
    from quant_research.setups.adapter import InMemoryBarProvider
    from quant_research.setups.detector import Detector
    from quant_research.setups.path_recorder import PathRecorder
    from quant_research.setups.boundary import TrivialBoundaryConstructor

    bars, meta = synthetic.make_long_series("timeout")
    provider = InMemoryBarProvider({("ES", "1d"): bars})
    det = [d for d in Detector().detect(provider, "ES", "1d", meta.data_end_index)
           if abs(d.opening.impulse_end.price - 124.4) < 0.05][0]
    fp = PathRecorder().record(provider, "ES", "1d", det.opening.setup_id,
                               det.opening.entry_eligible_bar, meta.data_end_index)
    spy = _MaxBarSpy(TrivialBoundaryConstructor())
    OnDemandGeometryMaterializer().materialize(
        det.opening, fp, det.terminated_at_bar, det.termination_reason,
        spy, maturity_retracement_fn)
    assert not spy.violations, f"materializer passed bars beyond t: {spy.violations}"
