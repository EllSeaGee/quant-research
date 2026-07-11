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
from dataclasses import dataclass
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


# =============================================================================
# Phase 2 — the real estimator-C constructor (Detector Spec v1.1 sections 8-9)
# =============================================================================

# Provisional normalisation constants for the barcount maturity path (section
# 8.5). They live with the maturity function because normalisation is a property
# of *which* maturity drives alpha, not of alpha's shape (which is the
# constructor's concern). Both are [PROVISIONAL — sign-off].
_M_START = 2       # ~= N_pivot; the "2-bar stage" after confirmation
_M_FULL = 8


def _clip01(x: float) -> float:
    return 0.0 if x < 0.0 else (1.0 if x > 1.0 else x)


@dataclass(frozen=True)
class BoundaryParams:
    """Estimator-C + alpha-offset parameters (Detector Spec v1.1 sections 8-9).

    ALL values here are PROVISIONAL and will be recalibrated in characterization
    (Detector Spec section 14) — which is exactly why geometry is materialized
    from bars on demand (Option B), not persisted: recalibration forces no
    regeneration of stored artifacts.
    """
    w_fit: int = 8               # estimator-C fit window (section 8.2)
    warm_up_bars: int = 1        # a line needs >= 2 points (section 8.2)
    alpha0: float = 0.9          # early offset midpoint (section 8.5)
    alpha_end: float = -0.2      # slightly inside the boundary at full maturity
    # decay shape f(m_hat): "linear" (default) or "convex" (section 8.5)
    decay_shape: str = "linear"
    convex_power: float = 2.0    # exponent when decay_shape == "convex"

    def alpha(self, m_hat: float) -> float:
        """alpha(m_hat) = alpha0 + (alpha_end - alpha0) * f(m_hat) (section 8.5).
        f is linear by default; convex (m_hat**p) is the leading sensitivity
        candidate and is exercised so selection is a config flip, not a rewrite."""
        m = _clip01(m_hat)
        if self.decay_shape == "convex":
            f = m ** self.convex_power
        else:
            f = m  # linear default
        return self.alpha0 + (self.alpha_end - self.alpha0) * f


def _fit_projected(points: list[tuple[int, float]], x_target: int):
    """OLS fit over (bar_index, price) points, projected to ``x_target``.
    Returns (projected_price, rms_residual). A single point degenerates to a flat
    line at that price with zero dispersion (the warm-up caller handles None)."""
    xs = [float(x) for x, _ in points]
    ys = [y for _, y in points]
    return primitives.ols_project(xs, ys, float(x_target))


class RealBoundaryConstructor:
    """Estimator C: a robust short-window local OLS fit to the countertrend-side
    boundary extrema, projected to t+1, with the maturity-decaying alpha offset
    resting the MR trigger just beyond it and clamped to the retracement floor
    (Detector Spec v1.1 sections 8-9).

    Countertrend side = pullback **lows** for LONG, pullback **highs** for SHORT.
    With-trend (far) side = the opposite extrema (section 9); emitted as a
    candidate stop-volatility unit until RQ1 decides its survival.

    Constructor rules honoured (section 8.7): never reads a fill / EntryConfig /
    stop / size (geometry is a pure function of bars); never uses a bar with
    bar_index > t. The SAME instance is used at generation and on-demand
    materialization (Contract 6.1 rule 2) — there is no approximate materializer.
    """

    def __init__(self, params: BoundaryParams | None = None):
        self.params = params or BoundaryParams()

    def compute_update(self, opening: DetectedSetupOpening,
                       bars_up_to_t: Sequence[Bar], t: int,
                       maturity_fn: MaturityFn) -> SetupUpdate:
        p = self.params
        # No-look-ahead guard: the constructor may see only bars <= t.
        window = [b for b in bars_up_to_t if b.bar_index <= t]
        if not window or window[-1].bar_index != t:
            raise ValueError(
                f"constructor requires a bar at t={t}; got up to "
                f"{window[-1].bar_index if window else None}")

        direction = opening.direction
        is_long = direction is Direction.LONG
        ps = opening.pullback_start_bar
        pullback_bars = [b for b in window if ps <= b.bar_index <= t]
        if not pullback_bars:
            raise ValueError(
                f"no pullback bars in [{ps}, {t}] within the substrate window")

        # --- running literal extreme L(t) on the countertrend side (section 8.1) ---
        if is_long:
            ext_bar = min(pullback_bars, key=lambda b: b.low)
            running_extreme_price = ext_bar.low
        else:
            ext_bar = max(pullback_bars, key=lambda b: b.high)
            running_extreme_price = ext_bar.high
        running_extreme = CausalPrice(price=running_extreme_price,
                                      defining_bar=ext_bar.bar_index, known_at_bar=t)

        # --- V(t): mean true range of the pullback bars so far (section 8.3) ---
        v = primitives.mean_true_range_between(window, ps, t)

        # --- competing ATR unit (section 7) ---
        atr = primitives.atr_ending_at(window, t, opening.atr_period)

        # --- estimator C: OLS fit to the last W_fit countertrend-side extrema ---
        fit_bars = pullback_bars[-p.w_fit:]
        n_extrema = len(fit_bars)
        if n_extrema <= p.warm_up_bars:
            # warm-up: single extreme, flat line to t+1, no dispersion (section 8.2)
            boundary_price = running_extreme_price
            fit_dispersion = None
        else:
            ct_points = [(b.bar_index, b.low if is_long else b.high) for b in fit_bars]
            boundary_price, fit_dispersion = _fit_projected(ct_points, t + 1)
        countertrend_boundary_next = ProjectedLevel(
            price=boundary_price, computed_at_bar=t, active_at_bar=t + 1)

        # --- alpha(m_hat) offset; m_hat comes normalised from the maturity_fn ---
        m_hat = maturity_fn(opening, window, t)
        alpha = p.alpha(m_hat)
        if is_long:
            raw_trigger = boundary_price - alpha * v
            trigger_price = max(raw_trigger, opening.retracement_floor)
        else:
            raw_trigger = boundary_price + alpha * v
            trigger_price = min(raw_trigger, opening.retracement_floor)
        mr_trigger_next = ProjectedLevel(price=trigger_price,
                                         computed_at_bar=t, active_at_bar=t + 1)

        # --- BOTH maturities emitted every update (Contract 7.11) ---
        maturity_barcount = t - ps
        budget = (2.0 / 3.0) * abs(opening.impulse_end.price - opening.impulse_origin.price)
        maturity_retracement = (abs(opening.impulse_end.price - running_extreme_price) / budget
                                if budget > 0 else 0.0)

        # --- optional far-side (with-trend) boundary + d_struct (section 9) ---
        with_trend_boundary_next = None
        d_struct = None
        if n_extrema > p.warm_up_bars:
            far_points = [(b.bar_index, b.high if is_long else b.low) for b in fit_bars]
            far_price, _ = _fit_projected(far_points, t + 1)
            with_trend_boundary_next = ProjectedLevel(
                price=far_price, computed_at_bar=t, active_at_bar=t + 1)
            # d_struct = channel height between with_trend boundary and running
            # extreme (Contract 7.15): LONG wt - L; SHORT L - wt.
            d_struct = (far_price - running_extreme_price if is_long
                        else running_extreme_price - far_price)

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
# These return the NORMALISED maturity m_hat in [0, 1] (Detector Spec section
# 8.5) so alpha can be driven by either measure; swapping the function is the
# "config flip, not a rewrite" the spec requires. BOTH maturity *fields* are
# still emitted on every SetupUpdate regardless of which function drives alpha.

def maturity_barcount_fn(opening: DetectedSetupOpening,
                         bars_up_to_t: Sequence[Bar], t: int) -> float:
    """Barcount maturity path (Detector Spec section 8.4/8.5), normalised:
    m_hat = clip((barcount - m_start)/(m_full - m_start), 0, 1)."""
    barcount = t - opening.pullback_start_bar
    denom = (_M_FULL - _M_START) or 1
    return _clip01((barcount - _M_START) / denom)


def maturity_retracement_fn(opening: DetectedSetupOpening,
                            bars_up_to_t: Sequence[Bar], t: int) -> float:
    """Retracement maturity path (section 8.4/8.5), normalised: the fraction of
    the 2/3 budget consumed by the running extreme at t, clipped to [0, 1].
    Causal (uses only bars <= t)."""
    ps = opening.pullback_start_bar
    win = [b for b in bars_up_to_t if ps <= b.bar_index <= t]
    if not win:
        return 0.0
    if opening.direction is Direction.LONG:
        re = min(b.low for b in win)
    else:
        re = max(b.high for b in win)
    budget = (2.0 / 3.0) * abs(opening.impulse_end.price - opening.impulse_origin.price)
    return _clip01(abs(opening.impulse_end.price - re) / budget if budget > 0 else 0.0)
