"""Keystone spine test (Contract section 8.1) — two-mode repaint / truncation
invariance over the geometry STREAM.

For each setup the emitted stream of (running_extreme, mean_true_range_pullback,
countertrend_boundary_next, mr_trigger_next, fit_dispersion, maturity_barcount,
maturity_retracement, with_trend_boundary_next, d_struct, atr) must be
byte-identical whether construction sees full history or history truncated at
each bar's bar_index — across the ENTIRE opportunity window through
terminated_at_bar (including bars after any fill). This runs in two modes:
  (a) generation-time construction (full-history vs truncated), and
  (b) the on-demand materializer, whose stream must equal (a).

A repainting negative control proves the harness actually bites.
"""

from typing import Sequence

import pytest

from quant_research.setups.contract import (
    Bar,
    CausalPrice,
    DetectedSetupOpening,
    Direction,
    MaturityFn,
    ProjectedLevel,
    SetupUpdate,
)
from quant_research.setups.boundary import (
    TrivialBoundaryConstructor,
    maturity_retracement_fn,
)

from tests.fixtures import pipeline as P

VARIANTS = ["timeout", "invalidated_floor", "invalidated_reclaim"]


@pytest.mark.parametrize("variant", VARIANTS)
def test_mode_a_full_vs_truncated_byte_identical(variant):
    pipe = P.build_pipeline(variant)
    full_bars = P.substrate_of(pipe)
    ref = P.full_history_stream(pipe.opening, full_bars, pipe.detection.terminated_at_bar,
                                pipe.constructor, pipe.maturity_fn)
    trunc = P.truncated_stream(pipe.opening, full_bars, pipe.detection.terminated_at_bar,
                               pipe.constructor, pipe.maturity_fn)
    diff = P.first_stream_diff(ref, trunc)
    assert diff is None, f"repaint: full-history stream diverges from truncated at {diff}"


@pytest.mark.parametrize("variant", VARIANTS)
def test_mode_b_materializer_matches_generation(variant):
    pipe = P.build_pipeline(variant)
    full_bars = P.substrate_of(pipe)
    trunc = P.truncated_stream(pipe.opening, full_bars, pipe.detection.terminated_at_bar,
                               pipe.constructor, pipe.maturity_fn)
    materialized = P.materialized_stream(pipe)
    diff = P.first_stream_diff(trunc, materialized)
    assert diff is None, f"mode-(b) materializer diverges from generation-time at {diff}"


def test_sample_includes_nonnull_pullback_count_and_full_span():
    """The sample must include a setup with non-null pullback_count_in_trend (the
    repaint-prone component) and must exercise the full post-window span."""
    dets = P.all_detections("timeout")
    counts = [d.opening.features.pullback_count_in_trend for d in dets]
    assert any(c is not None for c in counts), "no non-null pullback_count in sample"
    # main setup fills-early exercise: stream continues to terminated_at_bar
    pipe = P.build_pipeline("timeout")
    lc = pipe.lifecycle
    assert lc.updates[-1].bar_index == pipe.detection.terminated_at_bar


# --- negative control: a repainting constructor MUST fail the harness --------

class _RepaintingConstructor(TrivialBoundaryConstructor):
    """Deliberately buggy: running_extreme is the min low over ALL provided
    pullback bars (ignoring t), so future bars leak in. The truncation harness
    must catch this."""

    def compute_update(self, opening, bars_up_to_t, t, maturity_fn):
        ps = opening.pullback_start_bar
        # BUG: does not cap at t — uses every provided pullback bar.
        pullback = [b for b in bars_up_to_t if b.bar_index >= ps]
        if opening.direction is Direction.LONG:
            re_price = min(b.low for b in pullback)
        else:
            re_price = max(b.high for b in pullback)
        base = super().compute_update(opening, [b for b in bars_up_to_t if b.bar_index <= t],
                                      t, maturity_fn)
        from dataclasses import replace
        return replace(base, running_extreme=CausalPrice(price=re_price,
                                                         defining_bar=t, known_at_bar=t))


def test_repaint_negative_control_is_caught():
    pipe = P.build_pipeline("timeout")
    full_bars = P.substrate_of(pipe)
    bad = _RepaintingConstructor()
    ref = P.full_history_stream(pipe.opening, full_bars, pipe.detection.terminated_at_bar,
                                bad, pipe.maturity_fn)
    trunc = P.truncated_stream(pipe.opening, full_bars, pipe.detection.terminated_at_bar,
                               bad, pipe.maturity_fn)
    diff = P.first_stream_diff(ref, trunc)
    assert diff is not None, "harness failed to catch a repainting constructor"
