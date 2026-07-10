"""End-to-end Phase-1 pipeline helpers + the reusable two-mode truncation harness.

The harness is deliberately shared across phases (per the credit-economy note):
Phase 2 will point it at the real estimator C without change.
"""

from dataclasses import dataclass
from typing import Sequence

from quant_research.setups.adapter import InMemoryBarProvider
from quant_research.setups.boundary import (
    TrivialBoundaryConstructor,
    maturity_retracement_fn,
)
from quant_research.setups.contract import (
    Bar,
    BoundaryConstructor,
    DetectedSetupOpening,
    ForwardPath,
    MaturityFn,
    SetupUpdate,
)
from quant_research.setups.detector import DetectionResult, Detector
from quant_research.setups.geometry_access import GeometryAccess, PersistedSetup
from quant_research.setups.materializer import OnDemandGeometryMaterializer, _substrate_bars
from quant_research.setups.path_recorder import PathRecorder

from . import synthetic


@dataclass
class Pipeline:
    provider: InMemoryBarProvider
    detection: DetectionResult
    forward_path: ForwardPath
    access: GeometryAccess
    constructor: BoundaryConstructor
    maturity_fn: MaturityFn
    data_end_index: int

    @property
    def opening(self) -> DetectedSetupOpening:
        return self.detection.opening

    @property
    def lifecycle(self):
        return self.access.get_lifecycle(self.opening.setup_id)


def _pick_impulse_setup(results, end_price_hint=124.4):
    matches = [r for r in results if abs(r.opening.impulse_end.price - end_price_hint) < 0.05]
    if not matches:
        raise AssertionError(f"no detected setup near end_price {end_price_hint}")
    return matches[0]


def build_pipeline(variant: str = "timeout") -> Pipeline:
    """Detect the main (124) LONG setup for a variant, record its path, and wire a
    GeometryAccess (Option B) with the trivial constructor + retracement maturity."""
    bars, meta = synthetic.make_long_series(variant)
    provider = InMemoryBarProvider({("ES", "1d"): bars})
    detector = Detector()
    results = detector.detect(provider, "ES", "1d", meta.data_end_index)
    detection = _pick_impulse_setup(results)

    recorder = PathRecorder()
    fp = recorder.record(provider, "ES", "1d", detection.opening.setup_id,
                         detection.opening.entry_eligible_bar, meta.data_end_index)

    constructor = TrivialBoundaryConstructor()
    maturity_fn = maturity_retracement_fn
    access = GeometryAccess(constructor, maturity_fn,
                            materializer=OnDemandGeometryMaterializer())
    access.register(PersistedSetup(detection.opening, fp,
                                   detection.terminated_at_bar,
                                   detection.termination_reason))
    return Pipeline(provider=provider, detection=detection, forward_path=fp,
                    access=access, constructor=constructor, maturity_fn=maturity_fn,
                    data_end_index=meta.data_end_index)


def all_detections(variant: str = "timeout") -> list[DetectionResult]:
    bars, meta = synthetic.make_long_series(variant)
    provider = InMemoryBarProvider({("ES", "1d"): bars})
    return Detector().detect(provider, "ES", "1d", meta.data_end_index)


# --------------------------------------------------------------------------
# Two-mode truncation harness (Contract section 8.1)
# --------------------------------------------------------------------------

def full_history_stream(opening: DetectedSetupOpening, full_bars: Sequence[Bar],
                        terminated_at_bar: int, constructor: BoundaryConstructor,
                        maturity_fn: MaturityFn) -> list[SetupUpdate]:
    """Mode-A reference: at each bar t, hand the constructor the ENTIRE bar series
    (including bars with bar_index > t). A causal constructor must ignore the
    future bars and emit exactly what it would on truncated history. This is the
    stress input that would expose a repainting constructor."""
    out = []
    for t in range(opening.entry_eligible_bar, terminated_at_bar + 1):
        out.append(constructor.compute_update(opening, list(full_bars), t, maturity_fn))
    return out


def truncated_stream(opening: DetectedSetupOpening, full_bars: Sequence[Bar],
                     terminated_at_bar: int, constructor: BoundaryConstructor,
                     maturity_fn: MaturityFn) -> list[SetupUpdate]:
    """Mode-A truncated: at each bar t, hand the constructor only bars <= t."""
    out = []
    for t in range(opening.entry_eligible_bar, terminated_at_bar + 1):
        up_to_t = [b for b in full_bars if b.bar_index <= t]
        out.append(constructor.compute_update(opening, up_to_t, t, maturity_fn))
    return out


def materialized_stream(pipeline: Pipeline) -> list[SetupUpdate]:
    """Mode-B: the on-demand materializer's stream (from persisted substrate)."""
    return list(pipeline.lifecycle.updates)


def substrate_of(pipeline: Pipeline) -> list[Bar]:
    return _substrate_bars(pipeline.opening, pipeline.forward_path)


def first_stream_diff(a: Sequence[SetupUpdate], b: Sequence[SetupUpdate]):
    """Return (index, ua, ub) of the first differing update, or None if identical."""
    if len(a) != len(b):
        return ("len", len(a), len(b))
    for i, (ua, ub) in enumerate(zip(a, b)):
        if ua != ub:
            return (i, ua, ub)
    return None
