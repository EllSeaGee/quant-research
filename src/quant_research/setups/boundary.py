"""BoundaryConstructor implementations, behind the seam (Contract section 6.1).

Phase 1 ships a deliberately **trivial** constructor whose sole purpose is the
Contract section 11.1 *interface pressure-test*: it confirms the
``BoundaryConstructor`` / ``SetupUpdate`` / ``GeometryMaterializer`` interfaces
expose everything a real constructor needs, before the real estimator C is built
(Phase 2). It is not a placeholder for real geometry — it is a probe of the
interface.

The trivial constructor (per Implementation Plan Phase 1):
  * ``countertrend_boundary_next`` — flat at the running literal extreme,
    projected to t+1.
  * ``mr_trigger_next`` — running_extreme -/+ c*ATR (LONG/SHORT), clamped to
    ``retracement_floor`` (never crosses it, Contract section 7.6).
  * ``fit_dispersion`` — None during warm-up (<2 pullback bars); a simple RMS of
    countertrend-side extrema about the flat boundary thereafter.
  * BOTH maturity features on every update (Contract section 7.11), regardless of
    which one a real ``alpha`` would consume.
  * ``with_trend_boundary_next`` / ``d_struct`` — the far-side flat extreme and
    the implied channel height; None during warm-up.

Constructor rules it must honour (Detector Spec section 8.7):
  * never read a fill / EntryConfig / stop / size — geometry is a pure function
    of bars (fill-independence, Contract section 8.10);
  * never use a bar with bar_index > t (the materializer restricts the window;
    the constructor must not reach around it — enforced here defensively).
"""

import math
from typing import Sequence

from .contract import (
    Bar,
    CausalPrice,
    DetectedSetupOpening,
    Direction,
    MaturityFn,
    ProjectedLevel,
    SetupUpdate,
)
from . import primitives


class TrivialBoundaryConstructor:
    """Interface-pressure-test constructor. See module docstring."""

    def __init__(self, offset_c: float = 0.5, warm_up_bars: int = 1):
        self.offset_c = offset_c
        self.warm_up_bars = warm_up_bars

    # -- BoundaryConstructor Protocol -------------------------------------
    def compute_update(self, opening: DetectedSetupOpening,
                       bars_up_to_t: Sequence[Bar], t: int,
                       maturity_fn: MaturityFn) -> SetupUpdate:
        # Defensive no-look-ahead guard: the constructor may see only bars <= t.
        window = [b for b in bars_up_to_t if b.bar_index <= t]
        if not window or window[-1].bar_index != t:
            raise ValueError(
                f"constructor requires a bar at t={t}; got up to "
                f"{window[-1].bar_index if window else None}")

        direction = opening.direction
        ps = opening.pullback_start_bar
        pullback_bars = [b for b in window if ps <= b.bar_index <= t]
        if not pullback_bars:
            raise ValueError(
                f"no pullback bars in [{ps}, {t}] within the substrate window")

        # --- running literal extreme on the countertrend side ---
        if direction is Direction.LONG:
            ext_bar = min(pullback_bars, key=lambda b: b.low)
            running_extreme_price = ext_bar.low
        else:
            ext_bar = max(pullback_bars, key=lambda b: b.high)
            running_extreme_price = ext_bar.high
        running_extreme = CausalPrice(price=running_extreme_price,
                                      defining_bar=ext_bar.bar_index,
                                      known_at_bar=t)

        # --- V(t): mean true range of the pullback bars so far ---
        v = primitives.mean_true_range_between(window, ps, t)

        # --- competing ATR unit ---
        atr = primitives.atr_ending_at(window, t, opening.atr_period)

        # --- flat countertrend boundary projected to t+1 ---
        countertrend_boundary_next = ProjectedLevel(
            price=running_extreme_price, computed_at_bar=t, active_at_bar=t + 1)

        # --- mr trigger = boundary -/+ c*ATR, clamped to the floor ---
        floor = opening.retracement_floor
        if direction is Direction.LONG:
            raw = running_extreme_price - self.offset_c * atr
            trigger_price = max(raw, floor)
        else:
            raw = running_extreme_price + self.offset_c * atr
            trigger_price = min(raw, floor)
        mr_trigger_next = ProjectedLevel(price=trigger_price,
                                         computed_at_bar=t, active_at_bar=t + 1)

        # --- fit_dispersion: None during warm-up, else RMS about the flat line ---
        n_pullback = len(pullback_bars)
        if n_pullback < self.warm_up_bars + 1:
            fit_dispersion = None
        else:
            if direction is Direction.LONG:
                resid = [b.low - running_extreme_price for b in pullback_bars]
            else:
                resid = [b.high - running_extreme_price for b in pullback_bars]
            fit_dispersion = math.sqrt(sum(r * r for r in resid) / len(resid))

        # --- BOTH maturities (Contract section 7.11) ---
        maturity_barcount = t - ps
        budget = (2.0 / 3.0) * abs(opening.impulse_end.price - opening.impulse_origin.price)
        maturity_retracement = (abs(opening.impulse_end.price - running_extreme_price) / budget
                                if budget > 0 else 0.0)

        # --- optional far-side (with-trend) boundary + d_struct ---
        with_trend_boundary_next = None
        d_struct = None
        if n_pullback >= self.warm_up_bars + 1:
            if direction is Direction.LONG:
                far_price = max(b.high for b in pullback_bars)
                d = far_price - running_extreme_price
            else:
                far_price = min(b.low for b in pullback_bars)
                d = running_extreme_price - far_price
            with_trend_boundary_next = ProjectedLevel(
                price=far_price, computed_at_bar=t, active_at_bar=t + 1)
            d_struct = d

        return SetupUpdate(
            setup_id=opening.setup_id,
            bar_index=t,
            running_extreme=running_extreme,
            mean_true_range_pullback=v,
            countertrend_boundary_next=countertrend_boundary_next,
            mr_trigger_next=mr_trigger_next,
            fit_dispersion=fit_dispersion,
            maturity_barcount=maturity_barcount,
            maturity_retracement=maturity_retracement,
            with_trend_boundary_next=with_trend_boundary_next,
            d_struct=d_struct,
            atr=atr,
        )


# --- injectable maturity functions (the live offset selects one) ------------

def maturity_barcount_fn(opening: DetectedSetupOpening,
                         bars_up_to_t: Sequence[Bar], t: int) -> float:
    """Barcount maturity path (Detector Spec section 8.4): bars since pullback start."""
    return float(t - opening.pullback_start_bar)


def maturity_retracement_fn(opening: DetectedSetupOpening,
                            bars_up_to_t: Sequence[Bar], t: int) -> float:
    """Retracement maturity path: fraction of the 2/3 budget consumed by the
    running extreme at t. Causal (uses only bars <= t)."""
    ps = opening.pullback_start_bar
    window = [b for b in bars_up_to_t if ps <= b.bar_index <= t]
    if not window:
        return 0.0
    if opening.direction is Direction.LONG:
        re = min(b.low for b in window)
    else:
        re = max(b.high for b in window)
    budget = (2.0 / 3.0) * abs(opening.impulse_end.price - opening.impulse_origin.price)
    return abs(opening.impulse_end.price - re) / budget if budget > 0 else 0.0
