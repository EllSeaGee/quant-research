"""Causal primitives shared by the detector and boundary constructor.

Everything here is a pure function of bars and is strictly causal: given a
window of bars, it uses only those bars. The strength-N pivot, True Range, and
ATR definitions follow Detector Spec v1 sections 3 and 7. These are defined once
because impulse endpoints, minor pivots, and trend segmentation all rest on the
same pivot primitive (Detector Spec section 3).

Bars are addressed by their canonical ``bar_index`` (not list position). Helper
lookups build an index map so callers can pass any ascending, contiguous window.
"""

import math
from typing import Sequence

from .contract import Bar


def index_map(bars: Sequence[Bar]) -> dict[int, int]:
    """Map bar_index -> list position for an ascending bar window."""
    return {b.bar_index: i for i, b in enumerate(bars)}


def true_range(bar: Bar, prev_close: float | None) -> float:
    """Gap-absorbing True Range (Detector Spec section 7, FROZEN method choice):
    max(high-low, |high-prev_close|, |low-prev_close|). Uses only this bar and the
    previous close. If prev_close is None (no prior bar), falls back to high-low."""
    hl = bar.high - bar.low
    if prev_close is None:
        return hl
    return max(hl, abs(bar.high - prev_close), abs(bar.low - prev_close))


def true_range_series(bars: Sequence[Bar]) -> list[float]:
    """TR for each bar in an ascending, contiguous window, using the immediately
    preceding bar's close as prev_close (first bar uses high-low)."""
    out: list[float] = []
    prev_close: float | None = None
    for b in bars:
        out.append(true_range(b, prev_close))
        prev_close = b.close
    return out


def atr_ending_at(bars: Sequence[Bar], t: int, period: int) -> float:
    """Simple-average ATR over the ``period`` bars ending at bar_index ``t``,
    using only bars with bar_index <= t. Causal at t.

    The averaging convention is the simple mean of True Range (a VALUE; 14 is the
    provisional period, Detector Spec section 7). TR needs the prior bar's close,
    so the window silently extends one bar back for the prev_close of its first
    bar when available.
    """
    imap = index_map(bars)
    if t not in imap:
        raise ValueError(f"bar_index {t} not present in window")
    pos = imap[t]
    # bars for which we want TR: the `period` bars ending at t
    first_pos = max(0, pos - period + 1)
    window = bars[first_pos:pos + 1]
    # prev_close for the first bar in window, if a prior bar exists
    prev_close = bars[first_pos - 1].close if first_pos - 1 >= 0 else None
    trs: list[float] = []
    pc = prev_close
    for b in window:
        trs.append(true_range(b, pc))
        pc = b.close
    return sum(trs) / len(trs) if trs else 0.0


def mean_true_range_between(bars: Sequence[Bar], start_index: int, t: int) -> float:
    """Mean True Range of the pullback bars from ``start_index`` through ``t``
    inclusive (V(t), Detector Spec section 8.3). The first pullback bar's TR uses
    the preceding bar's close (the impulse-end bar's close) as prev_close, which
    is known; causal at t."""
    imap = index_map(bars)
    if start_index not in imap or t not in imap:
        # tolerate start before window; clamp to available
        positions = [i for i, b in enumerate(bars) if start_index <= b.bar_index <= t]
    else:
        positions = list(range(imap[start_index], imap[t] + 1))
    if not positions:
        return 0.0
    trs: list[float] = []
    for p in positions:
        pc = bars[p - 1].close if p - 1 >= 0 else None
        trs.append(true_range(bars[p], pc))
    return sum(trs) / len(trs)


def is_pivot_high(bars: Sequence[Bar], pos: int, n: int) -> bool:
    """Bar at list position ``pos`` is a strength-N pivot high: strictly greater
    high than the N bars on each side (strict inequality — ties are not pivots,
    Detector Spec section 3). Requires N bars of context on each side."""
    if pos - n < 0 or pos + n >= len(bars):
        return False
    h = bars[pos].high
    for i in range(1, n + 1):
        if not (h > bars[pos - i].high and h > bars[pos + i].high):
            return False
    return True


def is_pivot_low(bars: Sequence[Bar], pos: int, n: int) -> bool:
    """Mirror of :func:`is_pivot_high` using lows and strict less-than."""
    if pos - n < 0 or pos + n >= len(bars):
        return False
    lo = bars[pos].low
    for i in range(1, n + 1):
        if not (lo < bars[pos - i].low and lo < bars[pos + i].low):
            return False
    return True


# =============================================================================
# Phase 2 additions — estimator C fit, Keltner band, impulse texture, weekly swing
# All remain pure functions of bars and strictly causal (Detector Spec v1.1).
# =============================================================================

def ols_fit(xs: Sequence[float], ys: Sequence[float]) -> tuple[float, float]:
    """Ordinary least-squares line ``y = slope*x + intercept`` through the mean of
    the points (Detector Spec section 8.2 default estimator-C variant). Fitting
    through the mean lets individual extrema penetrate the line on both sides.

    With a single point (or all-equal x) the slope is 0 and the intercept is the
    mean y — a flat line, matching the warm-up "flat at the single extreme" rule.
    """
    n = len(xs)
    if n == 0:
        raise ValueError("ols_fit requires at least one point")
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    sxx = sum((x - mean_x) ** 2 for x in xs)
    if sxx == 0.0:
        return 0.0, mean_y
    sxy = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    slope = sxy / sxx
    intercept = mean_y - slope * mean_x
    return slope, intercept


def ols_project(xs: Sequence[float], ys: Sequence[float],
                x_target: float) -> tuple[float, float]:
    """Fit an OLS line to ``(xs, ys)`` and return ``(projected_y, rms_residual)``.

    ``projected_y`` is the fitted line evaluated at ``x_target`` (the t+1 horizon,
    Detector Spec section 8.2). ``rms_residual`` is the root-mean-square of the
    extrema about the fitted line (``fit_dispersion``, section 8.2).
    """
    slope, intercept = ols_fit(xs, ys)
    projected = intercept + slope * x_target
    resid = [y - (intercept + slope * x) for x, y in zip(xs, ys)]
    rms = math.sqrt(sum(r * r for r in resid) / len(resid)) if resid else 0.0
    return projected, rms


def ema_ending_at(bars: Sequence[Bar], t: int, period: int) -> float | None:
    """Exponential moving average of ``close`` at bar_index ``t`` (Detector Spec
    section 4, sub-test 1b centerline). Seeded by the simple average of the first
    ``period`` closes in the provided window, standard recursion (alpha =
    2/(period+1)) thereafter. Uses only bars with bar_index <= t; returns ``None``
    if fewer than ``period`` such bars exist (insufficient history)."""
    closes = [b.close for b in bars if b.bar_index <= t]
    if len(closes) < period:
        return None
    alpha = 2.0 / (period + 1)
    ema = sum(closes[:period]) / period
    for c in closes[period:]:
        ema = alpha * c + (1 - alpha) * ema
    return ema


def keltner_proximity_pass(bars: Sequence[Bar], end_pos: int, *, is_long: bool,
                           ema_period: int, atr_period: int,
                           k_keltner: float, k_tol: float) -> bool:
    """Sub-test 1b (Detector Spec section 4): does ``impulse_end`` reach within
    ``k_tol*ATR`` of the ``k_keltner*ATR`` Keltner band?

    LONG: ``end.high >= EMA + (k_keltner - k_tol)*ATR``. Mirror for SHORT with the
    lower band and ``end.low <=``. Evaluated at ``impulse_end_bar`` using only bars
    <= that bar. Returns ``False`` if EMA/ATR history is insufficient (1a can still
    carry extent via the OR-logic in section 4)."""
    end_bar = bars[end_pos].bar_index
    ema = ema_ending_at(bars, end_bar, ema_period)
    if ema is None:
        return False
    try:
        atr20 = atr_ending_at(bars, end_bar, atr_period)
    except ValueError:
        return False
    effective = (k_keltner - k_tol) * atr20
    if is_long:
        return bars[end_pos].high >= ema + effective
    return bars[end_pos].low <= ema - effective


def impulse_efficiency(bars: Sequence[Bar], origin_pos: int, end_pos: int) -> float:
    """Criterion 2 ratio (Detector Spec section 4, v1.1): ``net_displacement /
    sum(TR(t))`` over the impulse leg ``[origin_pos, end_pos]``. TR is the frozen
    section-7 gap-absorbing True Range, summed per-bar (not averaged). Uses the
    bar before ``origin_pos`` for the first TR's prev_close when available."""
    if end_pos < origin_pos:
        return 0.0
    net_displacement = abs(bars[end_pos].close - bars[origin_pos].close)
    total_tr = 0.0
    for pos in range(origin_pos, end_pos + 1):
        pc = bars[pos - 1].close if pos - 1 >= 0 else None
        total_tr += true_range(bars[pos], pc)
    if total_tr == 0.0:
        return 0.0
    return net_displacement / total_tr


def intra_impulse_retrace_ratio(bars: Sequence[Bar], origin_pos: int, end_pos: int,
                                origin_price: float, *, is_long: bool) -> float:
    """Criterion 3 ratio (Detector Spec section 4, v1.1): ``max_adverse_run /
    running_extent`` computed on **intrabar highs/lows** over the impulse leg.

    LONG: ``running_extent(t) = running_high(t) - origin_price`` where
    ``running_high`` is the highest intrabar high reached so far; ``max_adverse_run``
    is the deepest giveback from that running peak measured against subsequent
    intrabar lows. Mirror for SHORT. Returns 0 if the leg never makes progress."""
    max_adverse_run = 0.0
    peak_extent = 0.0
    if is_long:
        running_high = bars[origin_pos].high
        for pos in range(origin_pos, end_pos + 1):
            running_high = max(running_high, bars[pos].high)
            peak_extent = max(peak_extent, running_high - origin_price)
            giveback = running_high - bars[pos].low
            max_adverse_run = max(max_adverse_run, giveback)
    else:
        running_low = bars[origin_pos].low
        for pos in range(origin_pos, end_pos + 1):
            running_low = min(running_low, bars[pos].low)
            peak_extent = max(peak_extent, origin_price - running_low)
            giveback = bars[pos].high - running_low
            max_adverse_run = max(max_adverse_run, giveback)
    if peak_extent <= 0.0:
        return float("inf")
    return max_adverse_run / peak_extent


def resample_weekly(bars: Sequence[Bar], bars_per_week: int = 5) -> list[Bar]:
    """Resample daily bars into weekly bars by fixed ``bars_per_week`` grouping on
    bar_index (Detector Spec section 10; exact session/roll boundaries are a
    [BIND — codebase] value, ~5/week assumed here for synthetic daily series).

    A weekly bar's ``high``/``low`` are the group extrema, ``close`` the last
    close, and ``bar_index`` the week number ``daily_bar_index // bars_per_week`` of
    its first daily bar; only fully-formed weeks are emitted (no partial current
    week leaks future information)."""
    if not bars:
        return []
    groups: dict[int, list[Bar]] = {}
    for b in bars:
        groups.setdefault(b.bar_index // bars_per_week, []).append(b)
    weekly: list[Bar] = []
    for week in sorted(groups):
        grp = groups[week]
        if len(grp) < bars_per_week:
            continue  # partial (current) week — do not emit
        weekly.append(Bar(
            bar_index=week,
            timestamp=grp[0].timestamp,
            open=grp[0].open,
            high=max(g.high for g in grp),
            low=min(g.low for g in grp),
            close=grp[-1].close,
            volume=None,
        ))
    return weekly
